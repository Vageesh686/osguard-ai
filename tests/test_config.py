import pytest

from osguard.config import ConfigurationError, load_settings


def test_load_settings_reads_groq_credentials_without_exposing_key_in_repr():
    settings = load_settings(
        environ={
            "LLM_PROVIDER": " Groq ",
            "GROQ_API_KEY": " test-secret ",
            "GROQ_MODEL": " example/model ",
        }
    )

    assert settings.provider == "groq"
    assert settings.api_key == "test-secret"
    assert settings.model == "example/model"
    assert "test-secret" not in repr(settings)


@pytest.mark.parametrize(
    "environ, missing_name",
    [
        ({"GROQ_MODEL": "example/model"}, "GROQ_API_KEY"),
        ({"GROQ_API_KEY": "test-secret"}, "GROQ_MODEL"),
        ({}, "GROQ_API_KEY"),
    ],
)
def test_load_settings_reports_missing_values(environ, missing_name):
    with pytest.raises(ConfigurationError, match=missing_name):
        load_settings(environ=environ)


def test_load_settings_rejects_non_groq_provider():
    with pytest.raises(ConfigurationError, match="configured for Groq"):
        load_settings(
            environ={
                "LLM_PROVIDER": "other",
                "GROQ_API_KEY": "test-secret",
                "GROQ_MODEL": "example/model",
            }
        )
