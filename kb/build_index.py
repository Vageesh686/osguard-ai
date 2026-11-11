"""Build the OSGuard knowledge base.

    python -m kb.build_index                # fetch pages in kb/sources.yaml, chunk, embed, index
    python -m kb.build_index --skip-fetch   # reuse pages already saved in kb/raw/
    python -m kb.build_index --manual-dir kb/manual   # also index your own .md/.txt notes

Outputs:
    kb/raw/<slug>.json        fetched + parsed pages (git-ignored)
    kb/index/chunks.jsonl     all chunks (used for BM25)
    kb/index/chroma/          Chroma vector index
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import (CHROMA_DIR, CHUNKS_PATH, COLLECTION, EMBED_MODEL, INDEX_DIR,  # noqa: E402
                        RAW_DIR, SOURCES_PATH)

MAX_CHARS = 1200
HEADERS = {"User-Agent": "OSGuard-AI-student-project/0.1"}


def slugify(url: str) -> str:
    p = urlparse(url)
    return re.sub(r"[^a-z0-9]+", "-", (p.netloc + p.path).lower()).strip("-")[-80:]


def fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def parse_page(html: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (page title, [(section heading, section text), ...])."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "aside", "footer", "header", "form", "button", "svg"]):
        tag.decompose()
    main = soup.find("main") or soup.body or soup
    h1 = main.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(strip=True) if soup.title else "")

    sections: list[tuple[str, list[str]]] = [("Overview", [])]
    for el in main.find_all(["h2", "h3", "p", "li", "pre", "tr"]):
        if el.name in ("h2", "h3"):
            sections.append((el.get_text(" ", strip=True), []))
            continue
        if el.name != "pre" and el.find(["p", "li", "pre", "tr"]):
            continue                              # skip containers; keep leaf text only
        if el.name == "tr":
            text = " | ".join(c.get_text(" ", strip=True) for c in el.find_all(["td", "th"]))
        else:
            text = el.get_text(" ", strip=True) if el.name != "pre" else el.get_text("\n", strip=True)
        if text:
            sections[-1][1].append(text)
    return title, [(h, "\n".join(body)) for h, body in sections if body]


def chunk_section(title: str, heading: str, body: str) -> list[str]:
    prefix = f"{title} - {heading}\n"
    chunks, cur = [], ""
    for para in body.split("\n"):
        if cur and len(cur) + len(para) > MAX_CHARS:
            chunks.append(prefix + cur.strip())
            cur = ""
        cur += para + "\n"
    if cur.strip():
        chunks.append(prefix + cur.strip())
    return chunks


def fetch_sources() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(SOURCES_PATH.read_text(encoding="utf-8"))
    for src in cfg["sources"]:
        url = src["url"]
        try:
            html = fetch(url)
        except Exception as e:                                       # noqa: BLE001
            print(f"  [skip] {url}  ->  {e}")
            continue
        title, sections = parse_page(html)
        if not sections:
            print(f"  [skip] {url}  ->  no content parsed")
            continue
        out = {"url": url, "title": title, "category": src.get("category", "general"),
               "os_scope": src.get("os_scope", "windows-11"), "sections": sections}
        (RAW_DIR / f"{slugify(url)}.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        print(f"  [ok]   {title}  ({len(sections)} sections)")


def load_manual(manual_dir: Path) -> list[dict]:
    """Optional: your own notes. First line '# Title'; filename prefix 'category__name.md'."""
    pages = []
    for f in sorted(manual_dir.glob("*.*")):
        if f.suffix.lower() not in (".md", ".txt"):
            continue
        text = f.read_text(encoding="utf-8")
        category = f.stem.split("__")[0] if "__" in f.stem else "general"
        title = text.splitlines()[0].lstrip("# ").strip() if text.strip() else f.stem
        pages.append({"url": f"file://{f.name}", "title": title, "category": category,
                      "os_scope": "windows-11", "sections": [["Notes", text]]})
    return pages


def build_chunks(manual_dir: Path | None) -> list[dict]:
    pages = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(RAW_DIR.glob("*.json"))]
    if manual_dir and manual_dir.exists():
        pages += load_manual(manual_dir)
    chunks = []
    for page in pages:
        slug = slugify(page["url"]).split("-")[-3:]
        base = "-".join(slug)
        n = 0
        for heading, body in page["sections"]:
            for text in chunk_section(page["title"], heading, body):
                n += 1
                chunks.append({"id": f"{base}-{n}", "text": text, "url": page["url"], "title": page["title"],
                               "category": page["category"], "os_scope": page["os_scope"]})
    # ids must be unique
    seen = {}
    for c in chunks:
        if c["id"] in seen:
            seen[c["id"]] += 1
            c["id"] = f'{c["id"]}x{seen[c["id"]]}'
        else:
            seen[c["id"]] = 0
    return chunks


def index_chunks(chunks: list[dict]) -> None:
    import chromadb
    from sentence_transformers import SentenceTransformer

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_PATH.write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in chunks), encoding="utf-8")

    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    model = SentenceTransformer(EMBED_MODEL)
    for i in range(0, len(chunks), 64):
        batch = chunks[i:i + 64]
        embs = model.encode([c["text"] for c in batch], normalize_embeddings=True).tolist()
        col.add(ids=[c["id"] for c in batch], embeddings=embs,
                documents=[c["text"] for c in batch],
                metadatas=[{"category": c["category"], "url": c["url"], "title": c["title"]} for c in batch])
    print(f"Indexed {len(chunks)} chunks -> {CHUNKS_PATH} and {CHROMA_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true")
    ap.add_argument("--manual-dir", type=Path, default=None)
    args = ap.parse_args()
    if not args.skip_fetch:
        print("Fetching sources...")
        fetch_sources()
    chunks = build_chunks(args.manual_dir)
    if not chunks:
        sys.exit("No chunks produced. Check kb/sources.yaml and your network connection.")
    index_chunks(chunks)


if __name__ == "__main__":
    main()
