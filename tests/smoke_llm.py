from app.llm import generate_structured
from app.schemas import Extraction

result = generate_structured(
    "Classify this Windows problem and extract details: "
    "'Windows Update fails with error 0x80070005 (access denied) on Windows 11 23H2. "
    "I want updates to install again.'",
    Extraction,
    system="You are an expert Windows 11 support analyst.",
)
print(result.model_dump_json(indent=2))