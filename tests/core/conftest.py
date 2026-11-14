import uuid
from datetime import UTC, datetime

import pytest

import contracts
import db



@pytest.fixture
def tdb():
    """Fresh `capital_test_<random>` with the contract indexes; dropped afterwards. Skips without Atlas.

    A unique name per test: both people run suites against the same cluster, and a shared `capital_test`
    was dropped and reseeded under a running suite (BulkWriteError, missing policies).
    """
    if not db.mongo_uri(required=False):
        pytest.skip("MONGODB_URI not set")
    d = db.get_db(f"{contracts.TEST_DB_NAME}_{uuid.uuid4().hex[:8]}")
    d.client.drop_database(d.name)
    for coll, keys, opts in contracts.INDEXES:
        d[coll].create_index(keys, **opts)
    yield d
    d.client.drop_database(d.name)


@pytest.fixture
def world(tdb):
    """One human, one agent, one running session, one active policy for the stub tool `write_scratch`."""
    now = datetime.now(UTC)
    principals = [
        contracts.Principal(id="user:owner_a", kind="human", roles=["owner"], region="r1",
                            spend_limit=1_000_000, active=True),
        contracts.Principal(id="agent:programming", kind="agent", roles=["programming"], region="r1",
                            spend_limit=0, active=True),
        contracts.Principal(id="agent:intake", kind="agent", roles=["intake"], region="r1",
                            spend_limit=0, active=True),
    ]
    tdb.principals.insert_many([p.model_dump(by_alias=True) for p in principals])
    tdb.policies.insert_one(contracts.Policy(
        tool="write_scratch", version=1, status="active", roles=["programming"],
        checks=[contracts.PolicyCheck(name="role")], author="user:owner_a", created_at=now,
    ).model_dump())
    sid = str(tdb.sessions.insert_one(contracts.Session(
        principal_id="user:owner_a", task="test", region="r1", budget_envelope=100.0,
        status="running", created_at=now, updated_at=now,
    ).model_dump()).inserted_id)
    return tdb, sid
