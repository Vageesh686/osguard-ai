"""Validated, allowlisted Microsoft documentation source configuration."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, HttpUrl

from osguard.schemas import StrictModel


DEFAULT_SOURCE_CONFIG = Path(__file__).resolve().parents[3] / "data" / "documentation_sources.json"
ALLOWED_SOURCE_HOSTS = {"learn.microsoft.com", "support.microsoft.com"}


class DocumentationSource(StrictModel):
    source_id: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9-]+$")
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    os_version: str | None = Field(default=None, max_length=120)
    category: str = Field(min_length=1, max_length=80)

    def validate_source_host(self) -> "DocumentationSource":
        hostname = (urlparse(str(self.url)).hostname or "").casefold()
        if hostname not in ALLOWED_SOURCE_HOSTS:
            raise ValueError("Documentation URLs must use an approved Microsoft host")
        if urlparse(str(self.url)).scheme != "https":
            raise ValueError("Documentation URLs must use HTTPS")
        return self


def load_sources(path: str | Path = DEFAULT_SOURCE_CONFIG) -> list[DocumentationSource]:
    """Load and validate only the explicitly configured documentation URLs."""
    records = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(records, list):
        raise ValueError("Documentation source config must be a JSON array")
    sources = [DocumentationSource.model_validate(record).validate_source_host() for record in records]
    identifiers = [source.source_id for source in sources]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("Documentation source IDs must be unique")
    return sources
