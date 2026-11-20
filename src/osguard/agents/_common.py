"""Shared structured-output and failure handling for specialist agents."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, TypeVar

from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, ValidationError

from osguard.config import ConfigurationError, GroqSettings, load_settings
from osguard.groq_client import GroqProviderUnavailable, create_chat_model
from osguard.schemas import SpecialistName, SpecialistResult, WorkflowError
from osguard.state import OSGuardState


StructuredModel = TypeVar("StructuredModel", bound=BaseModel)
ModelProvider = Callable[[], Any]


class InvalidSpecialistOutput(ValueError):
    """Raised when a provider response does not match its Pydantic contract."""


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
            chain = prompt | model_provider().with_structured_output(output_schema)
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
