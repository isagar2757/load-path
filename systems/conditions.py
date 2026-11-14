"""A5: condition tools. A proposal's `_id` is the gate's idempotency key; a decision is one update on a pending record."""
import contracts

STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED = contracts.ConditionStatus.__args__


def propose_condition(db, args: dict) -> dict:
    key = args["idempotency_key"]
    db.condition_records.update_one({"_id": key}, {"$setOnInsert": {
        "asset_id": args["asset_id"], "rating": args["rating"], "year": args["year"], "status": STATUS_PENDING,
    }}, upsert=True)
    return {"produced": key}


def snapshot(db, args: dict) -> dict | None:
    return db.condition_records.find_one({"_id": args["idempotency_key"]})


def withdraw_condition(db, undo_args: dict) -> dict:
    r = db.condition_records.delete_one({"_id": undo_args["idempotency_key"], "status": STATUS_PENDING})
    return {"withdrawn": r.deleted_count}


def _decide(db, condition_id: str, status: str) -> dict:
    r = db.condition_records.update_one({"_id": condition_id, "status": STATUS_PENDING},
                                        {"$set": {"status": status}})
    if r.matched_count == 0:
        raise LookupError(f"condition {condition_id} is not pending")
    return {"produced": condition_id}


def approve_condition(db, args: dict) -> dict:
    return _decide(db, args["condition_id"], STATUS_APPROVED)


def reject_condition(db, args: dict) -> dict:
    if not (args.get("reason") or "").strip():
        raise ValueError("reject_condition needs a non-empty reason")
    return _decide(db, args["condition_id"], STATUS_REJECTED)


def decision_snapshot(db, args: dict) -> dict | None:
    return db.condition_records.find_one({"_id": args["condition_id"]})
