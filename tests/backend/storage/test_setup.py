import pytest

from backend.storage import setup


def test_setup_prepares_both_domains_before_application_start(monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "database_url", lambda component: f"postgresql://test.invalid/{component}")
    def initialize(url, component):
        calls.append((url, component))
        return {"schema_version": 1, "initialized": False}
    monkeypatch.setattr(setup, "initialize_database", initialize)
    setup.prepare_deployment()
    assert calls == [("postgresql://test.invalid/clinical", "clinical"), ("postgresql://test.invalid/knowledge", "knowledge")]


def test_setup_checks_all_required_configuration_before_writing(monkeypatch):
    monkeypatch.setattr(setup, "database_url", lambda component: None if component == "knowledge" else "postgresql://test.invalid/clinical")
    monkeypatch.setattr(setup, "initialize_database", lambda *args: pytest.fail("No writes with incomplete configuration"))
    with pytest.raises(ValueError, match="both"):
        setup.prepare_deployment()


def test_setup_failure_blocks_deployment_without_resetting_database(monkeypatch):
    calls = []
    monkeypatch.setattr(setup, "database_url", lambda component: "postgresql://test.invalid/db")
    def incompatible(url, component):
        calls.append(component)
        raise ValueError("unrelated database")
    monkeypatch.setattr(setup, "initialize_database", incompatible)
    with pytest.raises(ValueError, match="unrelated"):
        setup.prepare_deployment()
    assert calls == ["clinical"]
