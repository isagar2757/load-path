"""A3: create_work_order / cancel_work_order. Write then undo restores the collection; undo twice equals undo once."""
from systems import workorders

KEY = "s1:4"
ARGS = {"asset_id": "b1", "budget_id": "s1:3", "idempotency_key": KEY}


def _open(d):
    return list(d.work_orders.find({"status": {"$ne": "cancelled"}}))


def test_create_is_idempotent_per_key(tdb):
    a = workorders.create_work_order(tdb, ARGS)
    b = workorders.create_work_order(tdb, ARGS)
    assert a["produced"] == b["produced"] == KEY
    row = tdb.work_orders.find_one({"_id": KEY})
    assert (row["session_id"], row["asset_id"], row["budget_id"], row["status"], row["depends_on"]) == \
        ("s1", "b1", "s1:3", "draft", ["s1:3"])
    assert tdb.work_orders.count_documents({}) == 1


def test_cancel_restores_open_orders(tdb):
    before = _open(tdb)
    workorders.create_work_order(tdb, ARGS)
    workorders.cancel_work_order(tdb, {"idempotency_key": KEY, "produced": KEY})
    assert _open(tdb) == before


def test_cancel_twice_equals_once(tdb):
    workorders.create_work_order(tdb, ARGS)
    workorders.cancel_work_order(tdb, {"idempotency_key": KEY, "produced": KEY})
    once = list(tdb.work_orders.find())
    workorders.cancel_work_order(tdb, {"idempotency_key": KEY, "produced": None})
    assert list(tdb.work_orders.find()) == once
