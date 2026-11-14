"""A3: work-order tools. `_id` is the gate's idempotency key; the order depends on its budget line."""
import contracts

STATUS_DRAFT, _, STATUS_CANCELLED = contracts.WorkOrderStatus.__args__


def create_work_order(db, args: dict) -> dict:
    key = args["idempotency_key"]
    db.work_orders.update_one({"_id": key}, {"$setOnInsert": {
        "session_id": key.rsplit(":", 1)[0], "asset_id": args["asset_id"], "budget_id": args["budget_id"],
        "status": STATUS_DRAFT, "depends_on": [args["budget_id"]],
    }}, upsert=True)
    return {"produced": key}


def snapshot(db, args: dict) -> dict | None:
    return db.work_orders.find_one({"_id": args["idempotency_key"]})


def cancel_work_order(db, undo_args: dict) -> dict:
    r = db.work_orders.update_one({"_id": undo_args["idempotency_key"], "status": {"$ne": STATUS_CANCELLED}},
                                  {"$set": {"status": STATUS_CANCELLED}})
    return {"cancelled": r.modified_count}
