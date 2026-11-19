"""Small, testable boundary around LangChain's ChatGroq integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from osguard.config import GroqSettings, load_settings


class GroqProviderUnavailable(RuntimeError):
    """Raised when ChatGroq or one of its dependencies cannot be loaded."""


class GroqRequestError(RuntimeError):
    """Raised when a Groq request fails or returns an unusable response."""


def _load_chatgroq() -> Callable[..., Any]:
    try:
        from langchain_groq import ChatGroq
    except ImportError as exc:
        if "Application Control policy has blocked this file" in str(exc):
            message = (
                "Windows Application Control blocked a native dependency required by "
                "langchain-groq. Ask the device administrator for an approved Python "
                "environment or package."
            )
        else:
            message = (
                "Could not load langchain-groq or one of its dependencies. Install the "
                "project dependencies in an approved environment."
            )
        raise GroqProviderUnavailable(message) from exc
    return ChatGroq


def create_chat_model(
    settings: GroqSettings,
    *,
    model_factory: Callable[..., Any] | None = None,
) -> Any:
    """Create the configured ChatGroq model, with an injectable test factory."""
    factory = model_factory or _load_chatgroq()
    return factory(
        model=settings.model,
        api_key=settings.api_key,
        temperature=0,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )


def _request_failure_message(exc: Exception) -> str:
    name = type(exc).__name__
    if name == "RateLimitError":
        return "Groq rate limit reached after retries. Wait briefly, then try again."
    if name in {
        "APITimeoutError",
        "TimeoutError",
        "TimeoutException",
        "ReadTimeout",
        "ConnectTimeout",
    }:
        return "The Groq request timed out. Try again when the connection is stable."
    if name in {"APIConnectionError", "ConnectionError", "ConnectError", "NetworkError"}:
        return "Could not connect to Groq. Check network access and try again."
    return f"Groq request failed ({name}). Check the model ID and API configuration."


def ask_groq(
    prompt: str,
    *,
    settings: GroqSettings | None = None,
    model_factory: Callable[..., Any] | None = None,
) -> str:
    """Send one text prompt to Groq and return the model's text response."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("Prompt must contain non-whitespace text.")

    active_settings = settings or load_settings()
    try:
        model = create_chat_model(active_settings, model_factory=model_factory)
    except GroqProviderUnavailable:
        raise
    except Exception as exc:
        raise GroqRequestError(_request_failure_message(exc)) from exc

    try:
        response = model.invoke(prompt.strip())
    except Exception as exc:
        raise GroqRequestError(_request_failure_message(exc)) from exc

    content = getattr(response, "content", None)
    if not isinstance(content, str) or not content.strip():
        raise GroqRequestError("Groq returned an empty or non-text response.")
    return content.strip()
