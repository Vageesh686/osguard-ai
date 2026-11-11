from app.schemas import EnvSnapshot, Requirement
from app.stages.verify import compat

ENV = EnvSnapshot(os_build="10.0.22631.4037", powershell_version="5.1.22621.4111",
                  installed={"Python 3.12.4 (64-bit)": "3.12.4", "Git": "2.45.1"})


def R(name, spec):
    return Requirement(name=name, spec=spec)


def test_os_build_bare_number():
    assert compat.check_requirement(R("windows", ">=22000"), ENV).status == "pass"
    assert compat.check_requirement(R("windows", ">=26100"), ENV).status == "fail"


def test_os_full_version():
    assert compat.check_requirement(R("windows", ">=10.0.22000"), ENV).status == "pass"


def test_powershell_versions():
    assert compat.check_requirement(R("powershell", ">=5.1"), ENV).status == "pass"
    assert compat.check_requirement(R("powershell", ">=7.0"), ENV).status == "fail"
    assert compat.check_requirement(R("powershell", "5.1"), ENV).status == "pass"   # bare = minimum


def test_installed_software_substring_match():
    assert compat.check_requirement(R("python", ">=3.10"), ENV).status == "pass"
    assert compat.check_requirement(R("git", "<2.0"), ENV).status == "fail"


def test_missing_software_is_unknown():
    assert compat.check_requirement(R("nodejs", ">=18"), ENV).status == "unknown"


def test_unknown_env():
    assert compat.check_requirement(R("windows", ">=22000"), EnvSnapshot()).status == "unknown"


def test_parse_requirement_line():
    r = compat.parse_requirement_line("powershell>=5.1")
    assert (r.name, r.spec) == ("powershell", ">=5.1")
    r = compat.parse_requirement_line("Python 3.10")
    assert (r.name, r.spec) == ("Python", ">=3.10")


def test_overall_status():
    res = compat.check_requirements([R("windows", ">=22000"), R("powershell", ">=7")], ENV)
    assert compat.overall_status(res) == "fail"
