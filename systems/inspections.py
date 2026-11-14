"""S6: inspection requests opened after a rejection. `_id` is the gate's idempotency key; no undo."""


def request_inspection(db, args: dict) -> dict:
    key = args["idempotency_key"]
    db.inspection_requests.update_one({"_id": key}, {"$setOnInsert": {
        "condition_id": args["condition_id"], "asset_id": args["asset_id"],
    }}, upsert=True)
    return {"produced": key}


def snapshot(db, args: dict) -> dict | None:
    return db.inspection_requests.find_one({"_id": args["idempotency_key"]})
