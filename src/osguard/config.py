"""Centralized runtime settings for OSGuard's Groq integration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required runtime configuration is missing or invalid."""


@dataclass(frozen=True, slots=True)
class GroqSettings:
    """Validated settings needed to create the configured Groq chat model."""

    provider: str
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float = 30.0
    max_retries: int = 2


def _project_env_path() -> Path:
    return Path(__file__).resolve().parents[2] / ".env"


def load_settings(
    *,
    environ: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> GroqSettings:
    """Load Groq settings from the process environment and project `.env`.

    An explicit ``environ`` mapping makes configuration tests deterministic and
    deliberately skips loading the real `.env` file.
    """
    if environ is None:
        load_dotenv(dotenv_path=env_file or _project_env_path(), override=False)
        values: Mapping[str, str] = os.environ
    else:
        values = environ

    provider = values.get("LLM_PROVIDER", "groq").strip().lower()
    if provider != "groq":
        raise ConfigurationError(
            f"Unsupported LLM_PROVIDER {provider!r}; this project is configured for Groq."
        )

    api_key = values.get("GROQ_API_KEY", "").strip()
    model = values.get("GROQ_MODEL", "").strip()
    missing = [
        name
        for name, value in (("GROQ_API_KEY", api_key), ("GROQ_MODEL", model))
        if not value
    ]
    if missing:
        raise ConfigurationError(
            "Set the following environment variable(s) in .env: " + ", ".join(missing)
        )

    return GroqSettings(
        provider=provider,
        api_key=api_key,
        model=model,
    )
