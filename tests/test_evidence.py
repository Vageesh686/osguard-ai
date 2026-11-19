from app.schemas import Chunk
from app.stages.verify.evidence import command_in_docs


def ch(text):
    return Chunk(id="x", text=text, url="u", title="t")


def test_generic_cmdlets_pass_the_guard():
    assert command_in_docs('Get-Content "C:\\x.log" | Select-String error', [ch("nothing relevant")])


def test_tool_must_appear_in_docs():
    assert not command_in_docs("sfc /scannow", [ch("about chkdsk only")])
    assert command_in_docs("sfc /scannow", [ch("Use sfc to scan protected files")])


def test_exe_suffix_and_case():
    assert command_in_docs("DISM.exe /Online /Cleanup-Image /RestoreHealth", [ch("The DISM tool repairs images")])
