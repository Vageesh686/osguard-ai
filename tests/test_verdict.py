from app.schemas import Action, EnvSnapshot
from app.stages.verify import effect, environment
from app.stages.verify.verdict import combine


def final(intent, env, ev, tier):
    return combine(intent, env, ev, tier, {}).final


def test_hard_stops():
    assert final("fail", "pass", "supported", "read_only") == "withhold"
    assert final("pass", "fail", "supported", "read_only") == "withhold"   # e.g. hallucinated command


def test_read_only_is_always_offered():
    assert final("pass", "pass", "supported", "read_only") == "recommend"
    assert final("pass", "pass", "unsupported", "read_only") == "recommend_with_warning"


def test_reversible_needs_evidence():
    assert final("pass", "pass", "supported", "reversible") == "recommend"
    assert final("pass", "pass", "weak", "reversible") == "recommend_with_warning"
    assert final("pass", "pass", "unsupported", "reversible") == "need_more_info"


def test_destructive_is_never_plain_recommend():
    assert final("pass", "pass", "supported", "destructive") == "recommend_with_warning"
    assert final("pass", "unknown", "supported", "destructive") == "need_more_info"
    assert final("pass", "pass", "weak", "destructive") == "need_more_info"
    assert final("pass", "pass", "unsupported", "destructive") == "withhold"


def test_environment_wmic_removed_on_24h2():
    act = Action(command="wmic os get caption", shell="cmd")
    eff = effect.analyze_command(act.command, "cmd")
    new = EnvSnapshot(os_build="10.0.26100.1", is_admin=True)
    old = EnvSnapshot(os_build="10.0.22631.1", is_admin=True)
    assert environment.check_environment(act, new, eff)[0] == "fail"
    assert environment.check_environment(act, old, eff)[0] == "pass"


def test_environment_admin_required():
    act = Action(command="sfc /scannow", shell="cmd")
    eff = effect.analyze_command(act.command, "cmd")
    v, reason, _ = environment.check_environment(act, EnvSnapshot(os_build="10.0.22631.1", is_admin=False), eff)
    assert v == "unknown" and "elevated" in reason
