"""A2: budget tools. `_id` is the gate's idempotency key `<session_id>:<seq>`, so a repeat call writes nothing."""
import contracts

STATUS_COMMITTED, STATUS_RELEASED = contracts.BudgetStatus.__args__


def _session_id(key: str) -> str:
    return key.rsplit(":", 1)[0]


def commit_budget(db, args: dict) -> dict:
    key = args["idempotency_key"]
    db.budget_ledger.update_one({"_id": key}, {"$setOnInsert": {
        "session_id": _session_id(key), "asset_id": args["asset_id"], "amount": args["amount"],
        "status": STATUS_COMMITTED, "depends_on": list(args.get("depends_on", [])),
    }}, upsert=True)
    return {"produced": key}


def snapshot(db, args: dict) -> dict | None:
    return db.budget_ledger.find_one({"_id": args["idempotency_key"]})


def release_budget(db, undo_args: dict) -> dict:
    r = db.budget_ledger.update_one({"_id": undo_args["idempotency_key"], "status": STATUS_COMMITTED},
                                    {"$set": {"status": STATUS_RELEASED}})
    return {"released": r.modified_count}
