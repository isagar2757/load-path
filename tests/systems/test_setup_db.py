"""A0: setup_db validators, indexes, seed. Plan Stage 0 check."""
import pytest
from pymongo.errors import WriteError

import contracts as c
import db
import setup_db

needs_atlas = pytest.mark.skipif(not db.mongo_uri(required=False), reason="MONGODB_URI not set")

# Own DB name so Sagar's capital_test runs cannot race Atlas drop/create.
A0_TEST_DB = "capital_test_a0"


@pytest.fixture
def test_db():
    client = db.client()
    client.drop_database(A0_TEST_DB)
    d = client[A0_TEST_DB]
    yield d
    client.drop_database(A0_TEST_DB)


@needs_atlas
def test_setup_db_runs_twice_without_error(test_db):
    setup_db.setup(A0_TEST_DB)
    setup_db.setup(A0_TEST_DB)

    owner = test_db.principals.find_one({"_id": "user:owner_a"})
    engineer = test_db.principals.find_one({"_id": "user:engineer_b"})
    assert owner is not None
    assert engineer is not None
    assert engineer["spend_limit"] < owner["spend_limit"]
    for aid in c.AGENT_IDS:
        assert test_db.principals.find_one({"_id": aid}) is not None
    assert test_db.policies.count_documents({"tool": "commit_budget", "status": "active"}) == 1
    assert test_db.policies.count_documents({"tool": "create_work_order", "status": "active"}) == 1


@needs_atlas
def test_principals_reject_missing_kind(test_db):
    setup_db.setup(A0_TEST_DB)
    with pytest.raises(WriteError) as ei:
        test_db.principals.insert_one({
            "_id": "user:bad_no_kind",
            "roles": ["owner"],
            "region": "r1",
            "spend_limit": 1.0,
            "active": True,
        })
    assert ei.value.code == 121


@needs_atlas
def test_setup_db_creates_indexes(test_db):
    setup_db.setup(A0_TEST_DB)
    for coll_name, keys, options in c.INDEXES:
        info = test_db[coll_name].index_information()
        key_tuple = tuple(keys)
        found = any(tuple(v["key"]) == key_tuple for v in info.values())
        assert found, f"missing index {keys} on {coll_name}: {info}"
        if options.get("unique"):
            match = next(v for v in info.values() if tuple(v["key"]) == key_tuple)
            assert match.get("unique") is True
