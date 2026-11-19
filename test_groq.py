"""Manual live Groq smoke check; pytest does not call the external API."""

from osguard.config import ConfigurationError, load_settings
from osguard.groq_client import GroqProviderUnavailable, GroqRequestError, ask_groq


def main() -> int:
    try:
        settings = load_settings()
        answer = ask_groq(
            "Reply with exactly: OSGuard Groq connection is working.",
            settings=settings,
        )
    except (ConfigurationError, GroqProviderUnavailable, GroqRequestError) as exc:
        print(f"Groq smoke check failed: {exc}")
        return 1

    print(f"Groq responded using model {settings.model}:")
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
