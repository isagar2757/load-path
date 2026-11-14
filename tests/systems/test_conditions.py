"""A5: propose/withdraw, approve, reject. Write then undo restores the collection; undo twice equals undo once."""
import pytest

from systems import conditions

KEY = "s1:5"
ARGS = {"asset_id": "b1", "rating": 62.0, "year": 2026, "idempotency_key": KEY}


def _all(d):
    return list(d.condition_records.find())


def _status(d):
    return d.condition_records.find_one({"_id": KEY})["status"]


def test_propose_is_idempotent_per_key(tdb):
    a = conditions.propose_condition(tdb, ARGS)
    b = conditions.propose_condition(tdb, ARGS)
    assert a["produced"] == b["produced"] == KEY
    assert _all(tdb) == [{"_id": KEY, "asset_id": "b1", "rating": 62.0, "year": 2026, "status": "pending"}]


def test_withdraw_restores_records(tdb):
    tdb.condition_records.insert_one({"_id": "b1:2025", "asset_id": "b1", "rating": 70.0, "year": 2025,
                                      "status": "approved"})
    before = _all(tdb)
    conditions.propose_condition(tdb, ARGS)
    conditions.withdraw_condition(tdb, {"idempotency_key": KEY, "produced": KEY})
    assert _all(tdb) == before


def test_withdraw_twice_equals_once(tdb):
    conditions.propose_condition(tdb, ARGS)
    conditions.withdraw_condition(tdb, {"idempotency_key": KEY, "produced": KEY})
    once = _all(tdb)
    conditions.withdraw_condition(tdb, {"idempotency_key": KEY, "produced": None})
    assert _all(tdb) == once


def test_withdraw_leaves_decided_record(tdb):
    conditions.propose_condition(tdb, ARGS)
    conditions.approve_condition(tdb, {"condition_id": KEY})
    conditions.withdraw_condition(tdb, {"idempotency_key": KEY, "produced": KEY})
    assert _status(tdb) == "approved"


def test_approve_sets_status(tdb):
    conditions.propose_condition(tdb, ARGS)
    assert conditions.approve_condition(tdb, {"condition_id": KEY}) == {"produced": KEY}
    assert _status(tdb) == "approved"


def test_reject_sets_status(tdb):
    conditions.propose_condition(tdb, ARGS)
    assert conditions.reject_condition(tdb, {"condition_id": KEY, "reason": "rating disputed"}) == {"produced": KEY}
    assert _status(tdb) == "rejected"


@pytest.mark.parametrize("args", [{}, {"reason": ""}, {"reason": "   "}, {"reason": None}])
def test_reject_without_reason_refused(tdb, args):
    conditions.propose_condition(tdb, ARGS)
    with pytest.raises(ValueError):
        conditions.reject_condition(tdb, {"condition_id": KEY, **args})
    assert _status(tdb) == "pending"


def test_decide_non_pending_refused(tdb):
    conditions.propose_condition(tdb, ARGS)
    conditions.approve_condition(tdb, {"condition_id": KEY})
    with pytest.raises(LookupError):
        conditions.reject_condition(tdb, {"condition_id": KEY, "reason": "late"})
    with pytest.raises(LookupError):
        conditions.approve_condition(tdb, {"condition_id": "missing"})
    assert _status(tdb) == "approved"
