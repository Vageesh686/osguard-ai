"""Single entry point for all LLM calls in OSGuard."""
import json
import logging
import os
import time
from typing import Optional, Type, TypeVar

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

load_dotenv()
log = logging.getLogger("osguard.llm")

T = TypeVar("T", bound=BaseModel)

MODEL = os.getenv("LLM_MODEL", "gemini-2.5-flash")
_client: Optional[genai.Client] = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        key = os.getenv("LLM_API_KEY")
        if not key:
            raise RuntimeError("LLM_API_KEY is not set. Check your .env file.")
        _client = genai.Client(api_key=key)
    return _client


def _call(prompt: str, system: Optional[str], temperature: float,
          json_mode: bool, retries: int = 4) -> str:
    """One API call with exponential backoff on rate limits / server errors."""
    config = types.GenerateContentConfig(
        temperature=temperature,
        system_instruction=system,
        response_mime_type="application/json" if json_mode else None,
    )
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            t0 = time.time()
            resp = _get_client().models.generate_content(
                model=MODEL, contents=prompt, config=config
            )
            usage = resp.usage_metadata
            log.info(
                "llm call ok model=%s %.1fs in=%s out=%s",
                MODEL, time.time() - t0,
                getattr(usage, "prompt_token_count", "?"),
                getattr(usage, "candidates_token_count", "?"),
            )
            if not resp.text:
                raise RuntimeError("Empty response (possibly blocked by safety filter).")
            return resp.text
        except errors.APIError as e:
            if e.code in (429, 500, 503) and attempt < retries:
                log.warning("API error %s, retrying in %.0fs", e.code, delay)
                time.sleep(delay)
                delay *= 2
                continue
            raise


def generate_text(prompt: str, system: Optional[str] = None,
                  temperature: float = 0.0) -> str:
    """Free-text generation (used by baselines)."""
    return _call(prompt, system, temperature, json_mode=False)


def generate_structured(prompt: str, schema: Type[T],
                        system: Optional[str] = None,
                        temperature: float = 0.0,
                        max_retries: int = 2) -> T:
    """Return a validated Pydantic object. On bad JSON or schema mismatch,
    feed the error back to the model and retry."""
    schema_text = json.dumps(schema.model_json_schema(), indent=2)
    full_prompt = (
        f"{prompt}\n\n"
        f"Respond with ONLY a JSON object that conforms to this JSON schema:\n"
        f"{schema_text}"
    )
    last_err = ""
    for attempt in range(max_retries + 1):
        p = full_prompt if not last_err else (
            f"{full_prompt}\n\nYour previous answer was invalid:\n{last_err}\n"
            f"Fix it and return only the corrected JSON."
        )
        raw = _call(p, system, temperature, json_mode=True)
        try:
            return schema.model_validate_json(raw)
        except ValidationError as e:
            last_err = str(e)
            log.warning("validation failed (attempt %d): %s", attempt + 1, last_err[:300])
    raise ValueError(f"Could not get valid {schema.__name__} after "
                     f"{max_retries + 1} attempts. Last error: {last_err[:500]}")