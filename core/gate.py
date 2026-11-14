"""Policy gate: the only path from an actor to a tool. Rules: docs/formulas.md section 1.

Order (spec, Architecture): session check → fresh read of actor and active policy → evaluate → `decision`
event → snapshot → execute → `executed` (or `failed`) event. Any missing piece or error before execution is a deny.
"""
import math
from collections.abc import Callable
from typing import Any, NamedTuple

from bson import ObjectId
from pymongo.errors import PyMongoError

import db as dbmod
from contracts import ToolResult
from core import ledger, revert


class Registered(NamedTuple):
    fn: Callable[[Any, dict], dict]
    snapshot: Callable[[Any, dict], dict | None]
    undo: Callable[[Any, dict], dict]
    undo_tool: str | None


REGISTRY: dict[str, Registered] = {}


def register_tool(name, fn, snapshot, undo, undo_tool) -> None:
    REGISTRY[name] = Registered(fn, snapshot, undo, undo_tool)


class Deny(Exception):
    pass


def _err(e: Exception) -> str:
    """Error text for the public ledger: driver messages can name hosts, so only their type is kept."""
    return type(e).__name__ if isinstance(e, PyMongoError) else f"{type(e).__name__}: {e}"


def _check_role(ctx: dict, params: dict) -> None:
    actor, policy = ctx["actor"], ctx["policy"]
    if not set(actor.get("roles", [])) & set(policy.get("roles", [])):
        raise Deny(f"role: {actor['_id']} has none of {policy.get('roles', [])}")


def _amount(ctx: dict, check: str) -> float:
    a = ctx["args"].get("amount")
    if isinstance(a, bool) or not isinstance(a, int | float) or not math.isfinite(a) or a <= 0:
        raise Deny(f"{check}: args.amount must be a positive number")
    return a


def _asset_id(ctx: dict, check: str):
    a = ctx["args"].get("asset_id")
    # Scalars only: a dict would be read as a query operator ($exists, $ne) and bypass the check.
    if isinstance(a, bool) or not isinstance(a, str | int) or a == "":
        raise Deny(f"{check}: args.asset_id must be a non-empty string or integer")
    return a


def _check_spend_limit(ctx: dict, params: dict) -> None:
    amount = _amount(ctx, "spend_limit")
    hid = ctx["session"]["principal_id"]
    human = ctx["db"].principals.find_one({"_id": hid})
    if human is None or human.get("kind") != "human" or not human.get("active"):
        raise Deny(f"spend_limit: session principal {hid} missing, inactive or not human")
    limit = human.get("spend_limit")
    if not isinstance(limit, int | float) or isinstance(limit, bool):
        raise Deny(f"spend_limit: {hid} has no spend_limit")
    if amount > limit:
        raise Deny(f"spend_limit: {amount} exceeds {hid} limit {limit}")


def _committed(ctx: dict, extra: dict | None = None) -> dict:
    return {"session_id": str(ctx["session"]["_id"]), "status": "committed", **(extra or {})}


def _check_envelope(ctx: dict, params: dict) -> None:
    amount = _amount(ctx, "envelope")
    rows = list(ctx["db"].budget_ledger.aggregate([
        {"$match": _committed(ctx)}, {"$group": {"_id": None, "total": {"$sum": "$amount"}}}]))
    used = rows[0]["total"] if rows else 0
    envelope = ctx["session"].get("budget_envelope")
    if not isinstance(envelope, int | float) or isinstance(envelope, bool):
        raise Deny("envelope: session has no budget_envelope")
    if used + amount > envelope:
        raise Deny(f"envelope: committed {used} + {amount} exceeds envelope {envelope}")


def _check_jurisdiction(ctx: dict, params: dict) -> None:
    aid = _asset_id(ctx, "jurisdiction")
    asset = ctx["db"].assets.find_one({"_id": aid}, {"region": 1})
    if asset is None:
        raise Deny(f"jurisdiction: asset {aid} not found")
    region = ctx["session"]["region"]
    if asset.get("region") != region:
        raise Deny(f"jurisdiction: asset {aid} in {asset.get('region')}, session in {region}")
    actor = ctx["actor"]
    if actor.get("kind") == "human" and actor.get("region") != asset["region"]:
        raise Deny(f"jurisdiction: {actor['_id']} region {actor.get('region')} is not {asset['region']}")


def _check_has_commitment(ctx: dict, params: dict) -> None:
    aid = _asset_id(ctx, "has_commitment")
    if ctx["db"].budget_ledger.find_one(_committed(ctx, {"asset_id": aid}), {"_id": 1}) is None:
        raise Deny(f"has_commitment: no committed budget line for asset {aid} in this session")


CHECKS: dict[str, Callable[[dict, dict], None]] = {
    "role": _check_role,
    "spend_limit": _check_spend_limit,
    "envelope": _check_envelope,
    "jurisdiction": _check_jurisdiction,
    "has_commitment": _check_has_commitment,
}


def _evaluate(d, session_id: str, actor_id: str, tool: str, args: dict, ctx: dict) -> None:
    """Fill `ctx` and raise `Deny` on the first failing condition. Every read is fresh; nothing is cached."""
    ctx["db"], ctx["args"] = d, args if isinstance(args, dict) else {}
    session = d.sessions.find_one({"_id": ObjectId(session_id)}) if ObjectId.is_valid(session_id) else None
    if session is None:
        raise Deny("session: not found")
    ctx["session"] = session
    if session["status"] != "running":
        raise Deny(f"session: status is {session['status']}")
    if tool not in REGISTRY:
        raise Deny(f"tool: {tool} is not registered")
    actor = d.principals.find_one({"_id": actor_id})
    if actor is None or not actor.get("active"):
        raise Deny(f"actor: {actor_id} missing or inactive")
    ctx["actor"] = actor
    policy = d.policies.find_one({"tool": tool, "status": "active"})
    if policy is None:
        raise Deny(f"policy: no active policy for {tool}")
    ctx["policy"] = policy
    _check_role(ctx, {})  # policy.roles always binds, whether or not `role` is listed in checks
    for check in policy.get("checks", []):
        if check["name"] == "role":
            continue
        fn = CHECKS.get(check["name"])
        if fn is None:
            raise Deny(f"{check['name']}: check not implemented")
        fn(ctx, check.get("params", {}))


def guarded_call(session_id: str, actor_id: str, tool: str, args: dict, rationale: str | None,
                 depends_on: list[str] | None = None, db=None) -> ToolResult:
    d = db if db is not None else dbmod.get_db()
    depends_on = list(depends_on or [])
    ctx: dict = {}
    try:
        _evaluate(d, session_id, actor_id, tool, args, ctx)
        decision, reason = "allow", None
    except Deny as e:
        decision, reason = "deny", str(e)
    except Exception as e:  # fail closed
        decision, reason = "deny", f"error: {_err(e)}"

    policy = ctx.get("policy") or {}
    base = {
        "principal_id": (ctx.get("session") or {}).get("principal_id", "unknown"),
        "actor_id": actor_id, "tool": tool, "args": args, "depends_on": depends_on,
        "policy_id": str(policy["_id"]) if policy else None, "policy_version": policy.get("version"),
    }
    try:
        dec = ledger.append(session_id, {**base, "type": "decision", "decision": decision,
                                         "reason": reason, "rationale": rationale}, db=d)
    except Exception as e:
        # No recorded decision, no execution.
        return ToolResult(allowed=False, reason=f"ledger: {_err(e)}"
                          + (f"; {reason}" if reason else ""), result=None, seq=None)
    if decision == "deny":
        return ToolResult(allowed=False, reason=reason, result=None, seq=dec["seq"])

    reg = REGISTRY[tool]
    # Idempotency key: tools store it under a unique index; undo finds the write by it, even for an armed entry.
    key = f"{session_id}:{dec['seq']}"
    targs = {**args, "idempotency_key": key}
    if reg.undo_tool:
        try:
            revert.arm(d, session_id, dec["seq"], tool, reg.undo_tool, key, depends_on)
        except Exception as e:
            msg = f"saga: {_err(e)}"  # no armed entry, no execution
            return ToolResult(allowed=True, reason=msg, result=None,
                              seq=_record_after(d, session_id, {**base, "type": "failed", "reason": msg}))
    before = None
    try:
        before = reg.snapshot(d, targs)
        result = reg.fn(d, targs)
    except Exception as e:  # the entry stays armed: outcome unknown, compensable
        msg = f"tool: {_err(e)}"
        return ToolResult(allowed=True, reason=msg, result=None,
                          seq=_record_after(d, session_id, {**base, "type": "failed", "reason": msg, "before": before}))
    if reg.undo_tool:
        revert.mark_done(d, session_id, dec["seq"], (result or {}).get("produced"))
    try:
        ev = ledger.append(session_id, {**base, "type": "executed", "before": before, "after": result}, db=d)
        return ToolResult(allowed=True, reason=None, result=result, seq=ev["seq"])
    except Exception as e:
        # The tool has written; never raise past that point. Record a bare `failed` event instead.
        msg = f"ledger: result not recordable ({_err(e)})"
        return ToolResult(allowed=True, reason=msg, result=None,
                          seq=_record_after(d, session_id, {**base, "type": "failed", "reason": msg}))


def _record_after(d, session_id: str, event: dict) -> int | None:
    """Append a post-execution event; on failure retry once without `before`/`after`, then give up (seq None)."""
    for ev in (event, {k: v for k, v in event.items() if k not in ("before", "after")}):
        try:
            return ledger.append(session_id, ev, db=d)["seq"]
        except Exception:
            continue
    return None
