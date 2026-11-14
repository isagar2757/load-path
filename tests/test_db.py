import certifi
import pytest

import db

needs_atlas = pytest.mark.skipif(not db.mongo_uri(required=False), reason="MONGODB_URI not set")


def test_client_uses_certifi(monkeypatch):
    seen = {}
    monkeypatch.setenv("MONGODB_URI", "mongodb://example.invalid")
    monkeypatch.setattr(db, "MongoClient", lambda uri, **kw: seen.update(uri=uri, **kw))
    db.client.cache_clear()
    try:
        db.client()
    finally:
        db.client.cache_clear()
    assert seen["uri"] == "mongodb://example.invalid"
    assert seen["tlsCAFile"] == certifi.where()


def test_missing_uri_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.setattr(db, "ENV_FILE", tmp_path / ".env")
    with pytest.raises(RuntimeError):
        db.mongo_uri()


@needs_atlas
def test_get_db_pings_sandbox():
    d = db.get_db("capital_test")
    assert d.name == "capital_test"
    assert d.client.admin.command("ping")["ok"] == 1
