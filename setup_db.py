"""Create validators, indexes and seed data for database `capital`. Idempotent."""
from __future__ import annotations

from datetime import datetime, timezone

import contracts as c
import db

# Seed values (region / limits not fixed in formulas; engineer lower than owner).
REGION = "r1"
OWNER_SPEND = 100_000.0
ENGINEER_SPEND = 10_000.0
POLICY_AUTHOR = "user:owner_a"


def _policy_check_schema() -> dict:
    return {
        "bsonType": "object",
        "required": ["name"],
        "additionalProperties": False,
        "properties": {
            "name": {"enum": list(c.CHECK_NAMES)},
            "params": {"bsonType": "object"},
        },
    }


def _schemas() -> dict[str, dict]:
    """$jsonSchema bodies for control collections; additionalProperties: false."""
    return {
        "principals": {
            "bsonType": "object",
            "required": ["_id", "kind", "roles", "region", "spend_limit", "active"],
            "additionalProperties": False,
            "properties": {
                "_id": {"bsonType": "string", "pattern": r"^(user|agent):[a-z0-9_]+$"},
                "kind": {"enum": ["human", "agent"]},
                "roles": {"bsonType": "array", "items": {"bsonType": "string"}},
                "region": {"bsonType": "string"},
                "spend_limit": {"bsonType": ["double", "int", "long"]},
                "active": {"bsonType": "bool"},
            },
        },
        "policies": {
            "bsonType": "object",
            "required": ["tool", "version", "status", "roles", "checks", "author", "created_at"],
            "additionalProperties": False,
            "properties": {
                "_id": {},
                "tool": {"bsonType": "string"},
                "version": {"bsonType": ["int", "long"]},
                "status": {"enum": ["active", "retired"]},
                "roles": {"bsonType": "array", "items": {"bsonType": "string"}},
                "checks": {"bsonType": "array", "items": _policy_check_schema()},
                "author": {"bsonType": "string"},
                "created_at": {"bsonType": "date"},
            },
        },
        "sessions": {
            "bsonType": "object",
            "required": [
                "principal_id", "task", "region", "budget_envelope", "status",
                "audit_head", "created_at", "updated_at",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {},
                "principal_id": {"bsonType": "string"},
                "task": {"bsonType": "string"},
                "region": {"bsonType": "string"},
                "budget_envelope": {"bsonType": ["double", "int", "long"]},
                "status": {"enum": list(c.SESSION_STATUS)},
                "revert_for": {"bsonType": ["string", "null"]},
                "aborted_by": {"bsonType": ["string", "null"]},
                "audit_head": {"bsonType": "string"},
                "created_at": {"bsonType": "date"},
                "updated_at": {"bsonType": "date"},
            },
        },
        "tasks": {
            "bsonType": "object",
            "required": ["session_id", "type", "agent_id", "status", "created_at"],
            "additionalProperties": False,
            "properties": {
                "_id": {},
                "session_id": {"bsonType": "string"},
                "type": {"bsonType": "string"},
                "agent_id": {"bsonType": "string"},
                "status": {"enum": ["queued", "claimed", "done", "failed", "cancelled"]},
                "input": {"bsonType": "object"},
                "output": {"bsonType": ["object", "null"]},
                "created_at": {"bsonType": "date"},
            },
        },
        "audit_events": {
            "bsonType": "object",
            "required": [
                "session_id", "seq", "ts", "type", "principal_id", "actor_id",
                "prev_hash", "hash",
            ],
            "additionalProperties": False,
            "properties": {
                "_id": {},
                "session_id": {"bsonType": "string"},
                "seq": {"bsonType": ["int", "long"]},
                "ts": {"bsonType": "date"},
                "type": {"enum": list(c.EVENT_TYPES)},
                "principal_id": {"bsonType": "string"},
                "actor_id": {"bsonType": "string"},
                "tool": {"bsonType": ["string", "null"]},
                "args": {"bsonType": ["object", "null"]},
                "policy_id": {"bsonType": ["string", "null"]},
                "policy_version": {"bsonType": ["int", "long", "null"]},
                "decision": {"bsonType": ["string", "null"], "enum": ["allow", "deny", None]},
                "reason": {"bsonType": ["string", "null"]},
                "rationale": {"bsonType": ["string", "null"]},
                "before": {"bsonType": ["object", "null"]},
                "after": {"bsonType": ["object", "null"]},
                "depends_on": {"bsonType": "array", "items": {"bsonType": "string"}},
                "prev_hash": {"bsonType": "string"},
                "hash": {"bsonType": "string"},
            },
        },
        "saga_stack": {
            "bsonType": "object",
            "required": ["session_id", "seq", "tool", "undo_args", "state"],
            "additionalProperties": False,
            "properties": {
                "_id": {},
                "session_id": {"bsonType": "string"},
                "seq": {"bsonType": ["int", "long"]},
                "tool": {"bsonType": "string"},
                "undo_tool": {"bsonType": ["string", "null"]},
                "undo_args": {"bsonType": "object"},
                "produced": {"bsonType": ["string", "null"]},
                "depends_on": {"bsonType": "array", "items": {"bsonType": "string"}},
                "state": {"enum": ["armed", "done", "compensated", "comp_failed"]},
            },
        },
    }


def _ensure_validated(database, name: str, schema: dict) -> None:
    """Create or collMod. Atlas drop_database is eventually consistent, so list_collection_names can lie."""
    from pymongo.errors import OperationFailure

    validator = {"$jsonSchema": schema}
    kwargs = {
        "validator": validator,
        "validationLevel": "strict",
        "validationAction": "error",
    }
    try:
        database.command("collMod", name, **kwargs)
    except OperationFailure as err:
        # 26 NamespaceNotFound — create; 48 NamespaceExists with different options — collMod again
        if err.code == 26:
            try:
                database.create_collection(name, **kwargs)
            except OperationFailure as create_err:
                if create_err.code == 48:
                    database.command("collMod", name, **kwargs)
                else:
                    raise
        elif err.code == 48:
            database.command("collMod", name, **kwargs)
        else:
            raise


def _ensure_indexes(database) -> None:
    for coll_name, keys, options in c.INDEXES:
        database[coll_name].create_index(keys, **options)


def _seed_principals(database) -> None:
    humans = [
        {
            "_id": "user:owner_a",
            "kind": "human",
            "roles": ["owner"],
            "region": REGION,
            "spend_limit": OWNER_SPEND,
            "active": True,
        },
        {
            "_id": "user:engineer_b",
            "kind": "human",
            "roles": ["engineer"],
            "region": REGION,
            "spend_limit": ENGINEER_SPEND,
            "active": True,
        },
    ]
    agents = []
    for aid in c.AGENT_IDS:
        role = aid.split(":", 1)[1]
        agents.append({
            "_id": aid,
            "kind": "agent",
            "roles": [role],
            "region": REGION,
            "spend_limit": 0.0,
            "active": True,
        })
    for doc in humans + agents:
        # Validate against the pydantic contract before write.
        c.Principal.model_validate(doc)
        database.principals.replace_one({"_id": doc["_id"]}, doc, upsert=True)


def _seed_stage2_policies(database) -> None:
    now = datetime.now(timezone.utc)
    policies = [
        {
            "tool": "commit_budget",
            "version": 1,
            "status": "active",
            "roles": ["programming"],
            "checks": [
                {"name": "role", "params": {}},
                {"name": "spend_limit", "params": {}},
                {"name": "envelope", "params": {}},
                {"name": "jurisdiction", "params": {}},
            ],
            "author": POLICY_AUTHOR,
            "created_at": now,
        },
        {
            "tool": "create_work_order",
            "version": 1,
            "status": "active",
            "roles": ["workorder"],
            "checks": [
                {"name": "role", "params": {}},
                {"name": "has_commitment", "params": {}},
            ],
            "author": POLICY_AUTHOR,
            "created_at": now,
        },
    ]
    for doc in policies:
        c.Policy.model_validate(doc)
        existing = database.policies.find_one({"tool": doc["tool"], "status": "active"})
        if existing:
            database.policies.replace_one(
                {"_id": existing["_id"]},
                {**doc, "created_at": existing.get("created_at", now)},
            )
        else:
            database.policies.insert_one(doc)


def setup(db_name: str = c.DB_NAME) -> None:
    database = db.get_db(db_name)
    for name, schema in _schemas().items():
        _ensure_validated(database, name, schema)
    _ensure_indexes(database)
    _seed_principals(database)
    _seed_stage2_policies(database)


if __name__ == "__main__":
    setup()
    print(f"setup_db ok ({c.DB_NAME})")
