# How Load Path works

Concepts, the agents, and the evidence for each claim. Formulas: [formulas.md](formulas.md). Demo:
[demo-script.md](demo-script.md). State of branch `fix/stale-step`, 2026-11-14.

## 1. Concepts

| Concept | Meaning here | Code |
|---|---|---|
| Session | One run on behalf of one person (the owner). Holds the region, the budget envelope and a status | `sessions` collection |
| Principal | A person or an agent with roles, a region and a spend limit | `principals` |
| Tool | A named action that writes to a domain collection, with an undo | `systems/`, `contracts.TOOLS` |
| Policy | Per tool: which roles may call it and which checks must pass | `policies` |
| Gate | The only path from an actor to a tool. Allows or denies each call | `core/gate.py` |
| Ledger | Append-only events per session, linked by a hash chain | `core/ledger.py` |
| Saga stack | One entry per allowed write: how to undo it and what it depends on | `core/revert.py` |
| Agent | A module that reads the database and offers its next allowed steps | `core/agents/` |
| Turn loop | Asks each agent in order for one step per round | `core/orchestrator.py` |
| Plan | The set of (bridge, treatment) lines chosen by a solver within the envelope | `engine/plan.py` |

## 2. Path of one action

```
agent or person -> gate -> decision event -> saga entry armed -> tool writes -> executed event
                    |
                    +-- deny: decision event with the reason, nothing else happens
```

1. The gate reads the session, the actor and the tool's active policy fresh on every call.
2. It evaluates the policy checks in order. The first failing check is the deny reason.
3. It appends a `decision` event. If that append fails, the tool does not run.
4. On allow it arms a saga entry, takes a snapshot, runs the tool and appends `executed` (or `failed`).

A missing policy, an inactive actor, a session that is not `running`, or any exception is a deny.

| Check | Passes when |
|---|---|
| `role` | the actor is active and has one of the policy's roles |
| `spend_limit` | the amount is at most the session owner's spend limit |
| `envelope` | committed lines in the session plus the amount fit the budget envelope |
| `jurisdiction` | the asset is in the session's region; for a person, also in the person's region |
| `has_commitment` | a committed budget line exists for the asset in this session |
| `in_approved_plan` | the active plan has a line with the same asset and amount |
| `has_reason` | the reject carries a non-empty reason |

## 3. Ledger

Each event stores `seq`, `prev_hash` and `hash = SHA-256(prev_hash + canonical JSON of the event)`. The
session stores the last hash. `verify` recomputes the chain and returns the first position that is wrong.

It detects an edited event, a missing event and a removed tail. It does not prevent them: anyone with write
access to the database can still change a document.

## 4. Revert

Every allowed write records `produced` (the id it wrote) and `depends_on` (ids it relied on).

- **Reject a condition:** undo every entry that depends on it, directly or through another entry's `produced`,
  newest first. Entries outside that set are untouched. Then an inspection request opens and the plan is
  re-solved. If the re-plan is denied or fails, the session ends `failed`.
- **Stop:** undo every live entry of the session, newest first. Status ends `rolled_back`.
- Undo functions are idempotent. A failed undo ends the session `failed`; a person decides what happens next.

## 5. Plan

A mixed-integer program (`scipy.optimize.milp`): maximise total benefit, total cost within the envelope, at
most one treatment per bridge. Lines already committed are fixed. A bridge whose newest reading is pending or
rejected is left out. Each result stores a hash of its inputs.

## 6. Agents

An agent is a module with `AGENT_ID`, `MODEL`, `SYSTEM` (its prompt), `GOAL` and `options()`. `options()` only
reads; it returns the steps the agent may take now, best first.

| Agent | Tool | Offers a step when | Order of options | Model |
|---|---|---|---|---|
| intake | `propose_condition` | a bridge in scope has no reading in this session | asset id | none |
| planner | `propose_plan` | no active plan, or an approval is newer than the plan | one option | `gemini-3.5-flash-lite` |
| programming | `commit_budget` | a plan line in scope has no committed budget | benefit per dollar, then benefit | `gemini-3.5-flash-lite` |
| workorder | `create_work_order` | a committed line in scope has no live work order | oldest commitment | `gemini-3.5-flash-lite` |

A programming step for a bridge with a pending reading lists that reading in `depends_on`. A work-order step
lists its budget line. These links are what a rejection follows.

### Turn loop

`Orchestrator.run_agents(agents, scope, use_llm, max_rounds)`:

1. Each round, each agent in order is asked for one step (`choose`).
2. A returned step is written as a `tasks` document, claimed with one atomic update, and sent through the gate.
3. The task stores the result and how the step was chosen: `offered`, `picked`, `by`, `model`.
4. The loop ends when a round passes with no step, the session is not `running`, a step is denied by policy or
   fails, or `max_rounds` is reached.

A watcher thread handles Stop and rejections while the loop runs. A person can act at any moment, so:

- A turn waits while a rejection is being reverted and re-planned.
- An agent's choice can go stale while it chooses (a model call takes about a second). Before submitting, the
  loop takes the lock and asks the agent for its options again; a step no longer on offer is dropped.
- A person's action can still land between that re-check and the gate. The gate then denies the step with
  `session: status is reverting`. The loop records the deny, waits for the revert and carries on.

### Scripted mode and LLM mode

- **Scripted (default):** `choose` takes option 0, the code's best. No model is called.
- **LLM (`--llm`):** the options go to the model as a JSON block. The model returns
  `{"choice": <index>, "rationale": "<text>"}`.

| The model can | The model cannot |
|---|---|
| pick one listed option by index | name a tool |
| write the rationale stored in the ledger | set or change an argument or an amount |
| | add an option |

A reply is used only if it is a JSON object with an integer index in range and a non-empty string rationale.
Control characters are removed and 300 characters are kept. Otherwise option 0 is used and the fallback is
counted by cause, per agent:

| Cause | When |
|---|---|
| `no_key` | `LLM_API_KEY` is not set |
| `cap` | 30 calls or 30,000 tokens reached in the run |
| `timeout`, `http` | the call took over 10 seconds or failed |
| `empty`, `bad_json`, `bad_choice`, `bad_rationale` | the reply failed a check |

## 7. Evidence

Tests: `uv run pytest -q tests/core tests/engine`. Result on this branch, 2026-11-14: 114 passed.

| Claim | Test or run |
|---|---|
| A decision is recorded before any write; no policy, wrong role or stopped session is a deny | `tests/core/test_gate.py`: `test_decision_precedes_write`, `test_deny_without_policy`, `test_role_check_denies_wrong_actor`, `test_deny_when_session_not_running` |
| Each check denies with its own reason; a database error is a deny | `tests/core/test_checks.py`: `test_first_failing_check_is_the_reason`, `test_gate_denies_when_atlas_down` |
| The ledger detects an edit, a gap and a removed tail | `tests/core/test_ledger.py`: `test_verify_flags_edit`, `test_verify_flags_gap`, `test_verify_flags_truncated_tail` |
| A rejection reverts only dependants | `tests/core/test_revert_dependants.py`: `test_reject_reverts_only_dependants` |
| Rollback is newest first and safe to repeat | `tests/core/test_revert.py`: `test_rollback_newest_first_restores_and_logs`, `test_rollback_twice_is_once` |
| The solver respects the envelope, one treatment per bridge, and is repeatable | `tests/engine/test_plan.py`: `test_solve_respects_envelope`, `test_solve_picks_at_most_one_treatment_per_bridge`, `test_solve_is_repeatable` |
| Each agent's options and their order | `tests/core/test_agents_options.py` (one test per agent) |
| The model never supplies a tool or args; every invalid reply falls back | `tests/core/test_agents_llm.py`: `test_choose_never_takes_tool_or_args_from_model`, `test_choose_falls_back_to_code_ranked_default`, `test_over_cap_makes_no_call_and_counts_a_fallback` |
| The loop produces the expected task chain and ends by itself | `tests/core/test_orchestrator.py`: `test_run_agents_yields_task_chain_and_stops` |
| Stop during the loop rolls back; a denied re-plan ends `failed` | `tests/core/test_orchestrator.py`: `test_stop_mid_loop_rolls_back`, `test_denied_replan_ends_session_failed` |
| A step made stale by a person's action is dropped; a deny caused by a concurrent rejection does not end the loop | `tests/core/test_orchestrator.py`: `test_step_made_stale_while_the_agent_chose_is_not_submitted`, `test_loop_waits_for_a_revert_then_acts_on_what_is_left`, `test_deny_for_a_session_that_left_running_does_not_end_the_loop` |
| An early Reject on the page during the agents' turns ends cleanly | 2026-11-14, interactive runs with a driver that rejected the second reading right after its budget was committed, and before it: `demo ok` in scripted and LLM mode; ledger shows the commit, the reject, one `release_budget`, the inspection request and the re-plan, with no extra deny |
| The full flow runs in both modes | `uv run python run_demo.py --reset --auto --wait 0 --step 0` and the same with `--llm`: both print `demo ok` (2026-11-14; LLM run: 5 calls, 1,659 tokens, 0 fallbacks) |
| Model choice | 2026-11-14 live probe, two options with the better one listed second: `gemini-3.5-flash-lite` picked it 3 of 3 times in 0.67–1.18 s. `gemini-3.5-flash`: 2 of 3 replies invalid JSON, one took 3.18 s; not used |

## 8. Assumptions, mocks and limits

**Assumptions (not sourced figures)**
- Treatment gains and costs per m² (`TREATMENTS` in `engine/plan.py`). Benefit = rating gain × deck area; no
  traffic weight.
- The envelope (250,000,000), the spend limits, the region `r1` and the two probe amounts.
- Policies and roles are demo rules, not a real authority matrix.

**Mock**
- The two condition readings the intake agent proposes: newest published rating minus 5, dated 2026. They are
  labelled MOCK in the feed. The intake agent never calls a model.
- The budget ledger, work orders and inspection requests are simulated systems (collections), not external ones.
- The people and agent identities are fictional.

**Limits**
- Only programming chooses among several options. The planner and work-order agents usually have one, so the
  model only writes their rationale.
- In every demo run the model picked index 0, which is also the code's default. The live probe above is the
  evidence that it chooses.
- "Never state amounts not shown in the options" is a prompt instruction. No code checks the rationale text.
- A step denied by policy ends the loop pass. The retry described in formulas.md section 6 (up to 2) is not built.
- The two DENY beats in the demo are probes submitted by `run_demo.py`, not agent choices.
- Stop sets the session status directly; it does not go through the gate (tracker item X4).
- The tool takes published ratings as given. It makes no safety or engineering judgment.

**UNVERIFIED**
- The interactive run with a person clicking in a browser. The race runs above used a driver calling the same
  server routes, not the page. Verify: `uv run uvicorn web.server:app --port 8000`,
  then `uv run python run_demo.py --reset --llm` and the clicks in demo-script.md section 4.
- `tests/systems/`. Verify: `uv run pytest -q tests/systems`.
