"""Shared structured-output and failure handling for specialist agents."""

from __future__ import annotations

import json
import inspect
from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ValidationError

from osguard.config import ConfigurationError, GroqSettings, load_settings
from osguard.groq_client import GroqProviderUnavailable, create_chat_model
from osguard.privacy import redact_sensitive_text
from osguard.schemas import SpecialistName, SpecialistResult, WorkflowError
from osguard.state import OSGuardState


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
ModelProvider = Callable[[], Any]


class InvalidSpecialistOutput(ValueError):
    """Raised when a provider response does not match its Pydantic contract."""


def groq_structured_output(model: Any, schema: type[BaseModel]) -> Any:
    """Use Groq JSON Schema mode; preserve simple injected model test doubles."""
    structured = model.with_structured_output
    if "method" in inspect.signature(structured).parameters:
        # The current Pydantic contracts contain optional fields, so Groq's
        # strict mode requirements cannot be assumed for every schema.
        return structured(schema, method="json_schema", strict=False)
    return structured(schema)


def create_model_provider(
    *,
    settings: GroqSettings | None = None,
    model_factory: Callable[..., Any] | None = None,
    model: Any | None = None,
) -> ModelProvider:
    """Return a lazy, cached ChatGroq provider for one compiled workflow."""
    cached_model = model

    def provide_model() -> Any:
        nonlocal cached_model
        if cached_model is None:
            cached_model = create_chat_model(
                settings or load_settings(), model_factory=model_factory
            )
        return cached_model

    return provide_model


def create_structured_invoker(
    *,
    prompt: ChatPromptTemplate,
    output_schema: type[StructuredModel],
    model_provider: ModelProvider,
) -> Callable[[Mapping[str, Any]], StructuredModel]:
    """Build and cache one structured chain without creating another model client."""
    chain: Any | None = None

    def invoke(values: Mapping[str, Any]) -> StructuredModel:
        nonlocal chain
        if chain is None:
            chain = prompt | groq_structured_output(model_provider(), output_schema)
        raw_result = chain.invoke(dict(values))
        if isinstance(raw_result, output_schema):
            return raw_result
        try:
            return output_schema.model_validate(raw_result)
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidSpecialistOutput(
                f"{output_schema.__name__} response failed schema validation"
            ) from exc

    return invoke


def specialist_error_code(exc: Exception) -> str:
    """Map provider and schema errors to stable, non-sensitive error codes."""
    name = type(exc).__name__
    if isinstance(exc, (InvalidSpecialistOutput, ValidationError)) or name in {
        "OutputParserException",
        "JSONDecodeError",
    }:
        return "invalid_llm_output"
    if name == "RateLimitError":
        return "rate_limited"
    if isinstance(exc, ConfigurationError):
        return "configuration_error"
    if isinstance(exc, GroqProviderUnavailable):
        if "application control" in str(exc).casefold():
            return "application_control_blocked"
        return "provider_unavailable"
    if name in {
        "APITimeoutError",
        "TimeoutError",
        "TimeoutException",
        "ReadTimeout",
        "ConnectTimeout",
    }:
        return "provider_timeout"
    if name in {
        "APIConnectionError",
        "ConnectionError",
        "ConnectError",
        "NetworkError",
    }:
        return "provider_unavailable"
    return "specialist_failed"


def failure_update(
    *, specialist: SpecialistName, stage: str, exc: Exception
) -> dict[str, Any]:
    """Record a contained specialist failure and allow other agents to continue."""
    code = specialist_error_code(exc)
    messages = {
        "invalid_llm_output": "The specialist returned output that did not match its required schema.",
        "rate_limited": "Groq rate limit reached while running this specialist.",
        "provider_timeout": "The Groq request timed out while running this specialist.",
        "provider_unavailable": "Could not connect to Groq while running this specialist.",
        "configuration_error": "Groq configuration is missing or invalid; this specialist could not run.",
        "application_control_blocked": "Windows Application Control blocked a required native dependency; this specialist did not run.",
        "specialist_failed": "The specialist could not complete its analysis.",
    }
    label = specialist.value.replace("_", " ").title()
    return {
        "specialist_results": [
            SpecialistResult(
                specialist=specialist,
                status="failed",
                message=messages[code],
            )
        ],
        "completed_specialists": [specialist],
        "errors": [WorkflowError(stage=stage, code=code, message=f"{label}: {messages[code]}")],
    }


def completed_result(
    specialist: SpecialistName, message: str
) -> SpecialistResult:
    return SpecialistResult(
        specialist=specialist,
        status="completed",
        message=message,
    )


def shared_evidence_json(state: OSGuardState) -> str:
    """Serialize bounded shared provenance as explicitly untrusted prompt data."""
    retrieval = state.get("retrieval_result")
    evidence = (
        state.get("retrieved_evidence", [])
        if retrieval is not None and retrieval.status == "success" else []
    )
    tool_results = state.get("tool_results", [])
    payload = {
        "retrieval_status": retrieval.status if retrieval is not None else "not_run",
        "retrieval_message": retrieval.message if retrieval is not None else "",
        "documentation_passages": [
            {
                "evidence_id": item.source_id,
                "title": item.title,
                "source_url": item.source_url,
                "os_version": item.os_version,
                "metadata": item.metadata,
                "passage": item.passage[:1800],
            }
            for item in evidence[:8]
        ],
        "read_only_tool_results": [
            {
                "tool_name": item.tool_name,
                "status": item.status,
                "summary": item.summary,
                "evidence_id": item.evidence_id,
                "data": item.data,
            }
            for item in tool_results[:8]
        ],
    }
    return redact_sensitive_text(json.dumps(payload, ensure_ascii=False, default=str))[:18000]
