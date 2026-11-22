"""Prompt privacy checks for documentation URLs and local evidence."""

import json

import pytest

from osguard.agents._common import shared_evidence_json
from osguard.privacy import redact_sensitive_text
from osguard.schemas import RetrievedEvidence, RetrievalResult, ToolExecutionResult
from osguard.state import make_initial_state


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/help/troubleshoot",
        "https://learn.microsoft.com/test/cpu",
        "https://learn.microsoft.com/en-us/windows/?view=windows-11&source=docs",
    ],
)
def test_public_https_urls_survive_redaction(url):
    assert redact_sensitive_text(f"Documentation: {url}") == f"Documentation: {url}"


@pytest.mark.parametrize(
    "path",
    [
        r"C:\Users\Alice\Documents\diagnostic.txt",
        "C:/Users/Alice/Documents/diagnostic.txt",
        r"\\fileserver\share\Alice\diagnostic.txt",
        "/home/alice/private/diagnostic.txt",
    ],
)
def test_local_and_network_paths_remain_redacted(path):
    result = redact_sensitive_text(f"The log is at {path}")
    assert "<PATH>" in result
    assert "Alice" not in result and "alice" not in result
    assert "fileserver" not in result


def test_private_host_information_remains_redacted():
    result = redact_sensitive_text(
        "Computer name: WORKSTATION-7\n"
        "Dashboard: http://workstation.local/status\n"
        "Gateway: https://192.168.1.10/health"
    )
    assert "WORKSTATION-7" not in result
    assert "workstation.local" not in result
    assert "192.168.1.10" not in result
    assert result.count("<PRIVATE_URL>") == 2


def test_shared_diagnostic_evidence_preserves_provenance_and_masks_local_paths():
    url = "https://learn.microsoft.com/en-us/windows/?view=windows-11&source=docs"
    item = RetrievedEvidence(
        source_id="cpu-doc#cpu-doc-0000",
        title="CPU guidance",
        source_url=url,
        os_version="Windows 11",
        passage=r"Process logs at C:\Users\Alice\Documents\cpu.log can help.",
        metadata={
            "section": "Process guidance",
            "chunk_id": "cpu-doc-0000",
            "local_note": r"\\fileserver\share\Alice\cpu.log",
        },
    )
    state = make_initial_state("High CPU usage")
    state["retrieval_result"] = RetrievalResult(
        status="success", query="high CPU", backend="in_memory", evidence=[item]
    )
    state["retrieved_evidence"] = [item]
    state["tool_results"] = [ToolExecutionResult(
        tool_name="get_process_stats", status="success",
        summary=r"Log saved at C:\Users\Alice\Documents\cpu.log",
        data={"local_path": r"C:\Users\Alice\Documents\cpu.log"},
        evidence_id="tool-process-1",
    )]

    serialized = shared_evidence_json(state)
    payload = json.loads(serialized)
    passage = payload["documentation_passages"][0]
    assert passage["evidence_id"] == item.source_id
    assert passage["source_url"] == url
    assert passage["title"] == item.title
    assert passage["os_version"] == item.os_version
    assert passage["metadata"]["section"] == item.metadata["section"]
    assert passage["metadata"]["chunk_id"] == item.metadata["chunk_id"]
    assert payload["read_only_tool_results"][0]["evidence_id"] == "tool-process-1"
    assert "<PATH>" in serialized
    assert "Alice" not in serialized
    assert "fileserver" not in serialized
