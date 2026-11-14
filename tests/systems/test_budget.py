"""A2: commit_budget / release_budget. Write then undo restores the collection; undo twice equals undo once."""
from systems import budget

KEY = "s1:3"


def _committed(d):
    return list(d.budget_ledger.find({"status": "committed"}))


def test_commit_is_idempotent_per_key(tdb):
    a = budget.commit_budget(tdb, {"asset_id": "b1", "amount": 50.0, "idempotency_key": KEY})
    b = budget.commit_budget(tdb, {"asset_id": "b1", "amount": 50.0, "idempotency_key": KEY})
    assert a["produced"] == b["produced"] == KEY
    row = tdb.budget_ledger.find_one({"_id": KEY})
    assert (row["session_id"], row["asset_id"], row["amount"], row["status"]) == ("s1", "b1", 50.0, "committed")
    assert tdb.budget_ledger.count_documents({}) == 1


def test_release_restores_committed_lines(tdb):
    before = _committed(tdb)
    budget.commit_budget(tdb, {"asset_id": "b1", "amount": 50.0, "idempotency_key": KEY})
    budget.release_budget(tdb, {"idempotency_key": KEY, "produced": KEY})
    assert _committed(tdb) == before


def test_release_twice_equals_once(tdb):
    budget.commit_budget(tdb, {"asset_id": "b1", "amount": 50.0, "idempotency_key": KEY})
    budget.release_budget(tdb, {"idempotency_key": KEY, "produced": KEY})
    once = list(tdb.budget_ledger.find())
    budget.release_budget(tdb, {"idempotency_key": KEY, "produced": None})
    assert list(tdb.budget_ledger.find()) == once


def test_release_without_write_is_noop(tdb):
    budget.release_budget(tdb, {"idempotency_key": KEY, "produced": None})
    assert tdb.budget_ledger.count_documents({}) == 0
