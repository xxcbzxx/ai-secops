"""Readiness checker regressions; all Docker/database commands are mocked."""
import json
from unittest.mock import Mock

import pytest

from scripts import selfcheck as check


@pytest.fixture(autouse=True)
def clear_results():
    check.results.clear()
    yield
    check.results.clear()


def container_records(extra=None):
    records = [{"Service": s, "Name": "test-" + s} for s in ["postgres", "qdrant"]]
    if extra:
        records.append({"Service": extra, "Name": "test-" + extra})
    return records


@pytest.mark.parametrize("health,expected", [("healthy", True), ("unhealthy", False),
                                             ("starting", False), (None, False)])
@pytest.mark.parametrize("array", [True, False])
def test_container_health_is_structured(monkeypatch, health, expected, array):
    records = container_records()
    output = json.dumps(records) if array else "\n".join(map(json.dumps, records))
    monkeypatch.setattr(check, "docker_compose", Mock(return_value=(0, output)))
    state = {"Running": True, "Status": "running"}
    if health:
        state["Health"] = {"Status": health}
    monkeypatch.setattr(check, "run", Mock(return_value=(0, json.dumps(state))))
    assert check.check_containers() is expected


@pytest.mark.parametrize("output", ["[]", "not JSON", "null", '{"Service":"postgres"}'])
def test_missing_or_malformed_container_state_fails(monkeypatch, output):
    monkeypatch.setattr(check, "docker_compose", Mock(return_value=(0, output)))
    assert check.check_containers() is False


@pytest.mark.parametrize("rc,state", [(1, "unavailable"), (0, "{}"),
                                      (0, '{"Running":false,"Status":"exited"}')])
def test_failed_or_stopped_inspection_fails(monkeypatch, rc, state):
    monkeypatch.setattr(check, "docker_compose", Mock(return_value=(0, json.dumps(container_records()))))
    monkeypatch.setattr(check, "run", Mock(return_value=(rc, state)))
    assert check.check_containers() is False


def test_unhealthy_optional_service_fails(monkeypatch):
    monkeypatch.setattr(check, "docker_compose", Mock(return_value=(0, json.dumps(container_records("ollama")))))
    def inspect(args):
        health = "unhealthy" if args[-1] == "test-ollama" else "healthy"
        return 0, json.dumps({"Running": True, "Status": "running", "Health": {"Status": health}})
    monkeypatch.setattr(check, "run", inspect)
    assert check.check_containers() is False


@pytest.mark.parametrize("list_rc,names,inspect_rc,bindings,expected", [
    (1, "error", 0, "{}", False),
    (0, "", 0, "{}", False),
    (0, "test-postgres", 1, "error", False),
    (0, "test-postgres", 0, "not JSON", False),
    (0, "test-postgres", 0, "[]", False),
    (0, "test-postgres", 0, "null", True),
    (0, "test-postgres", 0, "{}", True),
    (0, "test-postgres", 0, '{"5432/tcp":null}', True),
    (0, "test-postgres", 0, '{"5432/tcp":[{"HostPort":"5432"}]}', False),
])
def test_isolation_never_passes_unverified_state(monkeypatch, list_rc, names,
                                                inspect_rc, bindings, expected):
    monkeypatch.setattr(check, "docker_compose", Mock(return_value=(list_rc, names)))
    monkeypatch.setattr(check, "run", Mock(return_value=(inspect_rc, bindings)))
    assert check.check_isolation() is expected


@pytest.mark.parametrize("probe,rc,expected", [
    ({"status": "ready", "auth": "ok", "db": "ok"}, 0, True),
    ({"status": "ready", "auth": "missing", "db": "ok"}, 0, False),
    ({"status": "ok", "auth": "ok", "db": "ok"}, 0, False),
    ({"status": "ready", "auth": "ok", "db": "unreachable"}, 0, False),
    ({"status": "ready", "auth": "ok", "db": "ok"}, 1, False),
    ([], 0, False),
])
def test_ingest_requires_full_readiness(monkeypatch, probe, rc, expected):
    monkeypatch.setattr(check, "run", Mock(return_value=(0, "healthy")))
    compose = Mock(return_value=(rc, json.dumps(probe)))
    monkeypatch.setattr(check, "docker_compose", compose)
    monkeypatch.setattr(check, "psql", Mock(return_value=(0, "1")))
    assert check.check_ingest() is expected
    assert "/readyz" in compose.call_args.args[-1]


def test_deployed_unhealthy_ingest_fails(monkeypatch):
    monkeypatch.setattr(check, "run", Mock(return_value=(0, "unhealthy")))
    assert check.check_ingest() is False


@pytest.mark.parametrize("names_rc,names,expected,status", [
    (0, "", True, check.WARN),
    (0, "ai-secops-ingest-api-1", False, check.FAIL),
    (1, "", False, check.FAIL),
])
def test_absent_ingest_differs_from_failed_inspection(monkeypatch, names_rc, names, expected, status):
    monkeypatch.setattr(check, "run", Mock(side_effect=[(1, "error"), (names_rc, names)]))
    assert check.check_ingest() is expected
    assert check.results[-1]["status"] == status
