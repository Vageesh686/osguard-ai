"""Central paths and settings."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "kb"
RAW_DIR = KB_DIR / "raw"
INDEX_DIR = KB_DIR / "index"
CHROMA_DIR = INDEX_DIR / "chroma"
CHUNKS_PATH = INDEX_DIR / "chunks.jsonl"
SOURCES_PATH = KB_DIR / "sources.yaml"
RISK_TABLE = KB_DIR / "risk_table.yaml"
KNOWN_COMMANDS = KB_DIR / "known_commands.txt"   # produced by env_probe.ps1 -ExportCommands
PROMPT_DIR = ROOT / "app" / "prompts"
EVAL_DIR = ROOT / "eval"

EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-small-en-v1.5")
COLLECTION = "osguard"
TOP_K = 6
