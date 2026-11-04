"""In-process API regressions. No service startup, secrets, or live database.

The pool double records transaction exits; these tests verify application
transaction boundaries, not PostgreSQL's own commit/rollback implementation.
"""
from contextlib import contextmanager
from unittest.mock import Mock, MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg

from backend.ingest import app as ingest


TOKEN = "synthetic-test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
ASSET = {"asset_uid": "test-asset", "kind": "vm", "name": "Test asset"}
FINDING = {"source": "test", "rule_id": "test-rule", "title": "Test finding",
           "severity": "low", "asset_uid": "test-asset"}


class Pool:
    def __init__(self):
        self.conn = MagicMock()
        self.exits = []
        self.failure = None
        self.commit_failure = None

    @contextmanager
    def connection(self):
        if self.failure:
            raise self.failure
        try:
            yield self.conn
        except Exception:
            self.exits.append("rollback")
            raise
        else:
            if self.commit_failure:
                self.exits.append("commit-failed")
                raise self.commit_failure
            self.exits.append("commit")


@pytest.fixture
def api(monkeypatch):
    tokens = ingest.Tokens()
    tokens.index = {TOKEN: ("test-producer", frozenset(
        {"assets", "services", "software", "findings"}))}
    pool = Pool()
    monkeypatch.setattr(ingest, "TOKENS", tokens)
    monkeypatch.setattr(ingest, "POOL", pool)
    # Deliberately no TestClient context manager: do not run production lifespan.
    client = TestClient(ingest.app, raise_server_exceptions=False)
    yield client, pool, tokens
    client.close()


@pytest.mark.parametrize("header", [None, "", "Basic test", "Bearer ",
                                     "Bearer unknown", "Bearer nonascii-é",
                                     "Bearer embedded space", "Bearer control\tvalue",
                                     f"Bearer {TOKEN}é", f"Bearer {TOKEN}\u00a0",
                                     f"Bearer {TOKEN}\t", f"Bearer {TOKEN} "])
def test_invalid_authentication_is_401(header):
    tokens = ingest.Tokens()
    tokens.index = {TOKEN: ("test", frozenset({"assets"}))}
    with pytest.raises(HTTPException) as exc:
        tokens.check(header, "assets")
    assert exc.value.status_code == 401
    assert exc.value.headers == {"WWW-Authenticate": "Bearer"}


def test_unconfigured_keys_fail_closed():
    with pytest.raises(HTTPException) as exc:
        ingest.Tokens().check(f"Bearer {TOKEN}", "assets")
    assert exc.value.status_code == 503


def test_scoped_key_is_required():
    tokens = ingest.Tokens()
    tokens.index = {TOKEN: ("test", frozenset({"findings"}))}
    with pytest.raises(HTTPException) as exc:
        tokens.check(f"Bearer {TOKEN}", "assets")
    assert exc.value.status_code == 403
    assert tokens.check(f"Bearer {TOKEN}", "findings") == "test"


def test_token_file_skips_invalid_syntax_without_logging_values(tmp_path, monkeypatch, caplog):
    path = tmp_path / "synthetic-tokens.txt"
    path.write_text("# comment\n\nmalformed\nbad:nonascii-é:assets\n"
                    "bad:embedded space:assets\n"
                    f"good:{TOKEN}:assets,findings\n")
    monkeypatch.setattr(ingest, "INGEST_TOKENS_FILE", str(path))
    tokens = ingest.Tokens()
    tokens.load()
    assert tokens.check(f"Bearer {TOKEN}", "findings") == "good"
    assert len(tokens.index) == 1
    assert TOKEN not in caplog.text
    assert "nonascii-é" not in caplog.text
    assert "embedded space" not in caplog.text


@pytest.mark.parametrize("path", ["/healthz", "/readyz"])
def test_healthy_probes(api, path):
    client, _, _ = api
    response = client.get(path)
    assert response.status_code == 200
    assert response.json()["auth"] == "ok"
    assert response.json()["db"] == "ok"


def test_readiness_requires_keys_but_liveness_still_answers(api):
    client, _, tokens = api
    tokens.index = {}
    assert client.get("/readyz").status_code == 503
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["auth"] == "missing"


def test_readiness_sanitizes_database_errors(api):
    client, pool, _ = api
    pool.failure = RuntimeError("synthetic-sensitive-connection-detail")
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "postgres unavailable"}
    assert "synthetic-sensitive" not in response.text
    assert client.get("/healthz").json()["status"] == "degraded"


def test_readiness_requires_open_pool(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setattr(ingest, "POOL", None)
    assert client.get("/readyz").status_code == 503


def test_http_missing_key_and_scope(api, monkeypatch):
    client, _, tokens = api
    upsert = Mock()
    monkeypatch.setattr(ingest, "run_upsert", upsert)
    assert client.post("/api/v1/assets", json=ASSET).status_code == 401
    tokens.index = {TOKEN: ("test", frozenset({"findings"}))}
    assert client.post("/api/v1/assets", json=ASSET, headers=HEADERS).status_code == 403
    upsert.assert_not_called()


@pytest.mark.parametrize("payload", [{}, {**ASSET, "kind": "invalid"},
                                      {**ASSET, "asset_uid": "BAD UID"}])
def test_invalid_asset_never_reaches_upsert(api, monkeypatch, payload):
    client, _, _ = api
    upsert = Mock()
    monkeypatch.setattr(ingest, "run_upsert", upsert)
    assert client.post("/api/v1/assets", json=payload, headers=HEADERS).status_code == 422
    upsert.assert_not_called()


@pytest.mark.parametrize("asset_row,service_row,expected", [
    ((11,), (22, 11), 201),  # matching asset and service
    ((11,), (22, 99), 422),  # service belongs to another asset
    ((11,), None, 422),     # service absent
    (None, (22, 11), 422),  # asset absent
])
def test_finding_target_integrity(api, monkeypatch, asset_row, service_row, expected):
    client, pool, _ = api
    cursor = pool.conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = [asset_row, service_row]
    upsert = Mock(return_value=(7, True))
    audit = Mock()
    monkeypatch.setattr(ingest, "run_upsert", upsert)
    monkeypatch.setattr(ingest, "audit", audit)
    response = client.post("/api/v1/findings",
                           json={**FINDING, "service_uid": "test-service"}, headers=HEADERS)
    assert response.status_code == expected
    if expected == 422:
        upsert.assert_not_called()
        audit.assert_not_called()
        assert pool.exits == ["rollback"]
    else:
        assert upsert.call_args.args[2]["ai"] == 11
        assert upsert.call_args.args[2]["si"] == 22
        assert "FOR SHARE" in cursor.execute.call_args.args[0]
        assert cursor.execute.call_args.args[1] == ("test-service",)
        audit.assert_called_once()
        assert pool.exits == ["commit"]


@pytest.mark.parametrize("target", ["asset", "service"])
def test_single_target_findings_remain_supported(api, monkeypatch, target):
    client, pool, _ = api
    cursor = pool.conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (11,) if target == "asset" else (22, 11)
    upsert = Mock(return_value=(7, True))
    monkeypatch.setattr(ingest, "run_upsert", upsert)
    monkeypatch.setattr(ingest, "audit", Mock())
    body = {k: v for k, v in FINDING.items() if k != "asset_uid"}
    body[target + "_uid"] = "test-" + target
    assert client.post("/api/v1/findings", json=body, headers=HEADERS).status_code == 201
    params = upsert.call_args.args[2]
    assert (params["ai"], params["si"]) == ((11, None) if target == "asset" else (None, 22))


@pytest.mark.parametrize("created,status,action", [(True, 201, "created"), (False, 200, "updated")])
@pytest.mark.parametrize("endpoint,payload,entity", [
    ("assets", ASSET, "asset"),
    ("services", {"asset_uid": "test-asset", "service_uid": "test-service", "name": "Test"}, "service"),
    ("software", {"asset_uid": "test-asset", "product": "Test", "vendor": "Test", "version": "1"}, "asset_software"),
    ("findings", FINDING, "finding"),
])
def test_each_upsert_audits_once_in_same_connection(api, monkeypatch, created, status, action,
                                                   endpoint, payload, entity):
    client, pool, _ = api
    cursor = pool.conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (11,)
    upsert = Mock(return_value=(7, created))
    monkeypatch.setattr(ingest, "run_upsert", upsert)
    response = client.post(f"/api/v1/{endpoint}", json=payload, headers=HEADERS)
    assert response.status_code == status
    assert response.json()["id"] == 7
    assert response.json()["created"] is created
    assert upsert.call_args.args[0] is pool.conn
    audit_calls = [c for c in cursor.execute.call_args_list if "INSERT INTO ops.audit_events" in c.args[0]]
    assert len(audit_calls) == 1
    params = audit_calls[0].args[1]
    assert params["actor"] == "ingest-api:test-producer"
    assert params["action"] == action
    assert params["etype"] == entity
    assert pool.exits == ["commit"]


def test_audit_failure_reaches_transaction_rollback(api, monkeypatch):
    client, pool, _ = api
    monkeypatch.setattr(ingest, "run_upsert", Mock(return_value=(7, True)))
    monkeypatch.setattr(ingest, "audit", Mock(side_effect=RuntimeError("synthetic failure")))
    response = client.post("/api/v1/assets", json=ASSET, headers=HEADERS)
    assert response.status_code == 500
    assert pool.exits == ["rollback"]
    assert "synthetic failure" not in response.text


def test_failed_upsert_does_not_audit(api, monkeypatch):
    client, pool, _ = api
    monkeypatch.setattr(ingest, "run_upsert", Mock(side_effect=HTTPException(409, "retry")))
    audit = Mock()
    monkeypatch.setattr(ingest, "audit", audit)
    assert client.post("/api/v1/assets", json=ASSET, headers=HEADERS).status_code == 409
    audit.assert_not_called()
    assert pool.exits == ["rollback"]


@pytest.mark.parametrize("error,status", [(psycopg.errors.UniqueViolation, 409),
                                          (psycopg.errors.ForeignKeyViolation, 422)])
def test_database_integrity_errors_are_mapped(error, status):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.execute.side_effect = error("fixture")
    with pytest.raises(HTTPException) as exc:
        ingest.run_upsert(conn, "fixture SQL", {})
    assert exc.value.status_code == status


def test_commit_failure_cannot_return_success(api, monkeypatch):
    client, pool, _ = api
    pool.commit_failure = RuntimeError("synthetic commit failure")
    monkeypatch.setattr(ingest, "run_upsert", Mock(return_value=(7, True)))
    monkeypatch.setattr(ingest, "audit", Mock())
    response = client.post("/api/v1/assets", json=ASSET, headers=HEADERS)
    assert response.status_code == 500
    assert pool.exits == ["commit-failed"]
    assert "synthetic commit failure" not in response.text


def test_nonascii_header_is_rejected_over_http(api, monkeypatch):
    client, _, _ = api
    upsert = Mock()
    monkeypatch.setattr(ingest, "run_upsert", upsert)
    response = client.post("/api/v1/assets", json=ASSET,
                           headers=[(b"authorization", b"Bearer invalid-\xc3\xa9")])
    assert response.status_code == 401
    upsert.assert_not_called()
