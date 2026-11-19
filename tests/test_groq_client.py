import builtins
from types import SimpleNamespace

import pytest

from osguard.config import GroqSettings
from osguard.groq_client import (
    GroqProviderUnavailable,
    GroqRequestError,
    ask_groq,
    create_chat_model,
)


@pytest.fixture
def settings():
    return GroqSettings(
        provider="groq",
        api_key="test-secret",
        model="example/model",
    )


def test_create_chat_model_uses_centralized_groq_settings(settings):
    calls = []

    def fake_factory(**kwargs):
        calls.append(kwargs)
        return object()

    create_chat_model(settings, model_factory=fake_factory)

    assert calls == [
        {
            "model": "example/model",
            "api_key": "test-secret",
            "temperature": 0,
            "timeout": 30.0,
            "max_retries": 2,
        }
    ]


def test_create_chat_model_explains_application_control_block(settings, monkeypatch):
    original_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "langchain_groq":
            raise ImportError(
                "DLL load failed: An Application Control policy has blocked this file."
            )
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(GroqProviderUnavailable, match="Windows Application Control"):
        create_chat_model(settings)


def test_ask_groq_invokes_model_and_returns_trimmed_text(settings):
    prompts = []

    class FakeModel:
        def invoke(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="  Groq is responding.  ")

    answer = ask_groq(
        "  hello  ",
        settings=settings,
        model_factory=lambda **_kwargs: FakeModel(),
    )

    assert answer == "Groq is responding."
    assert prompts == ["hello"]


@pytest.mark.parametrize(
    "exception_name, expected_message",
    [
        ("RateLimitError", "rate limit"),
        ("APITimeoutError", "timed out"),
        ("APIConnectionError", "Could not connect"),
    ],
)
def test_ask_groq_translates_common_provider_errors(
    settings, exception_name, expected_message
):
    provider_error = type(exception_name, (Exception,), {})("provider details")

    class FakeModel:
        def invoke(self, _prompt):
            raise provider_error

    with pytest.raises(GroqRequestError, match=expected_message):
        ask_groq(
            "hello",
            settings=settings,
            model_factory=lambda **_kwargs: FakeModel(),
        )


def test_ask_groq_rejects_empty_prompt_before_creating_client(settings):
    def fail_if_called(**_kwargs):
        pytest.fail("The model factory should not be called for an empty prompt.")

    with pytest.raises(ValueError, match="non-whitespace"):
        ask_groq("  ", settings=settings, model_factory=fail_if_called)


def test_ask_groq_reports_model_configuration_errors(settings):
    class ValidationError(Exception):
        pass

    def invalid_factory(**_kwargs):
        raise ValidationError("invalid model options")

    with pytest.raises(GroqRequestError, match="ValidationError"):
        ask_groq("hello", settings=settings, model_factory=invalid_factory)


def test_ask_groq_rejects_empty_provider_response(settings):
    class FakeModel:
        def invoke(self, _prompt):
            return SimpleNamespace(content=" \n ")

    with pytest.raises(GroqRequestError, match="empty or non-text"):
        ask_groq(
            "hello",
            settings=settings,
            model_factory=lambda **_kwargs: FakeModel(),
        )
