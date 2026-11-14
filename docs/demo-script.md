# Demo script

A 3-minute live demo, a one-minute video and the policy table. Every on-screen value is from
`uv run python run_demo.py --reset --auto --wait 0 --step 0` (scripted agents, no model) on `main` against a
personal `CAPITAL_DB`, 2026-11-14. Timings are targets, not rehearsed.

## 1. Problem

Software agents now plan and spend public capital: they take in a bridge reading, solve the plan, commit budget
and open work orders in seconds. An auditor then asks three questions:

1. Why this bridge?
2. Who allowed the spend?
3. A reading was wrong. What rested on it, and was it undone?

Today the answers are rebuilt by hand from several systems, after the fact. Load Path makes every agent and human
action take one path, gate, ledger, revert, so the answers are recorded when the action happens.

## 2. Behind the scenes

| Fact | Where |
|---|---|
| The plan is a mixed-integer program (`scipy.optimize.milp`): maximise total benefit, total cost within the envelope, at most one treatment per bridge. Inputs are hashed (SHA-256) into the plan. | `engine/plan.py:34-66` |
| Treatment costs and gains are assumptions per m² of deck (minor 500, major 2,000, replacement 6,000). | `engine/plan.py:10-15` |
| Every tool call goes through `guarded_call`: session check, fresh read of actor and the active policy, checks, a `decision` event with `policy_id` and `policy_version`, then snapshot and execution. Any error before execution is a deny. | `core/gate.py:137-193` |
| No recorded decision, no execution: if the ledger write fails, the tool does not run. | `core/gate.py:185-191` |
| Each write carries an idempotency key `session:seq`; an undo finds the write by it. | `core/gate.py:196-201` |
| The model never supplies a tool or amount. Code builds numbered options; the model returns an index and a rationale (300 characters max). Bad JSON, out-of-range index, timeout or a cap falls back to option 0 and is counted. Limits: 10 s per call, 300 output tokens, 30 calls and 30,000 tokens per run. | `core/agents/__init__.py:32-75`, `core/agents/llm.py:14-17` |
| Ledger: each event's hash is SHA-256 of the previous hash plus the canonical JSON of the event; the session stores the head. `verify` returns `(False, n)` at the first broken position. It detects edits and gaps; it does not prevent them. | `core/ledger.py:42-44`, `core/ledger.py:79-95` |
| Revert is a saga: an entry is armed before the tool runs. Rejecting a reading undoes only entries whose `depends_on` reaches it, newest first, then opens an inspection request through the gate and re-solves the plan. | `core/revert.py:37-60`, `core/revert.py:73-107`, `core/orchestrator.py:67-80` |
| Stop rolls back every live saga entry, newest first; status ends `rolled_back` (or `failed` if an undo fails). | `core/orchestrator.py:82-90` |
| The page feed is a MongoDB change stream on `audit_events`. | `web/server.py:152` |

## 3. Policies and checks

Seeded by `setup_db.py:215-236` (all version 1, author `user:owner_a`). The gate always applies the policy's
role list (`core/gate.py:156`).

| Tool | Allowed role | Checks |
|---|---|---|
| `commit_budget` | programming | role, spend_limit, envelope, jurisdiction, in_approved_plan |
| `create_work_order` | workorder | role, has_commitment |
| `propose_condition` | intake | role, jurisdiction |
| `approve_condition` | owner | role, jurisdiction |
| `reject_condition` | owner | role, jurisdiction, has_reason |
| `request_inspection` | orchestrator | role |
| `propose_plan` | planner | role |

| Check | Blocks | Code |
|---|---|---|
| session | any call when the session is missing or not `running` | `core/gate.py:140-145` |
| policy | a tool with no active policy | `core/gate.py:152-154` |
| role | an actor with none of the policy's roles | `core/gate.py:41-44` |
| spend_limit | an amount above the session owner's limit (owner 100,000,000; engineer 10,000) | `core/gate.py:62-72`, `setup_db.py:14-15` |
| envelope | a commitment that takes committed spend past the session envelope | `core/gate.py:79-88` |
| jurisdiction | a bridge outside the session region, or a person outside the bridge's region | `core/gate.py:91-101` |
| in_approved_plan | a commitment whose bridge and amount match no line of the active plan | `core/gate.py:110-117` |
| has_commitment | a work order for a bridge with no committed budget | `core/gate.py:104-107` |
| has_reason | a rejection without a reason | `core/gate.py:120-123` |
| unknown check | any check name the gate does not implement: deny | `core/gate.py:160-162` |

## 4. Live demo (3 minutes)

Before speaking: page server running, `run_demo.py --reset` started, page open from the printed URL as
`user:owner_a`. The run waits at each human step (approve, reject, stop); pause there and name the check.

| Time | Do | On screen | Say |
|---|---|---|---|
| 0:00 | Nothing | Page, empty feed | "198 bridges on Highway 401, a budget that covers some. Agents do the planning and the spending. Three questions: why this bridge, who allowed it, what was undone when a fact was wrong." |
| 0:20 | Approve the pending reading | MOCK reading for 22X-0161/B1. After Approve: plan with 190 lines, 249,979,760 of 250,000,000 | "Pause: `approve_condition` needs the owner role and the right region. Both pass. Then the planner solves a mixed-integer program in code: 190 treatments inside the envelope." |
| 0:45 | Point at the commit row | Commit 1,618,200 for 22X-0161/B1, minor_rehab, benefit 32,364, benefit per dollar 0.02; work order opens | "Programming picks from plan lines ranked by benefit per dollar. The commit passed five checks: role, spend limit, envelope, jurisdiction, and the amount matches a plan line. The work order passed has_commitment." |
| 1:10 | Point at the two DENY rows | DENY `in_approved_plan` for 12,345; DENY `spend_limit` for 100,050,000 against 100,000,000 | "Two probes. An amount no plan line has: denied by in_approved_plan. An amount over the owner's limit: denied by spend_limit. Each deny is a ledger event with the policy version." |
| 1:30 | Switch actor to `user:engineer_b`, Approve | MOCK reading for 22X-0161/B2 pending; commit 1,844,400 and a work order already rest on it; DENY `role` | "Agents acted on this reading while it is pending, and recorded the dependency. The engineer tries to approve. The policy allows only the owner role: denied." |
| 1:55 | Switch to `user:owner_a`, reason "reading disputed, re-inspect", Reject | B2 budget released, B2 work order cancelled, B1 still committed, inspection opened, plan re-solved without B2 | "Pause: reject needs owner, region and a reason. The saga follows the dependency links and undoes only B2's work, newest first. B1 stays. An inspection opens and the plan is re-solved without B2." |
| 2:30 | Stop | Status `rolled_back`, 0 committed lines | "Stop compensates everything still live, newest first. Every undo is a ledger event." |
| 2:45 | Nothing | Feed | "The ledger is a SHA-256 hash chain. Edit one event and verify returns false and the position. Why: the plan line. Who: the gate decision. What was undone: the revert." |

Speaker rules: say "mock reading" when it appears; costs are assumptions; no statement about bridge safety.

## 5. One-minute video

One line per beat.

| Time | Shot | Voice-over |
|---|---|---|
| 0:00 | Empty page | "Agents now spend public money. Who allowed it, why this bridge, and what if a fact was wrong?" |
| 0:10 | Plan row, 190 lines | "Code solves a mixed-integer program: 190 bridge treatments inside a 250 million envelope." |
| 0:20 | Commit row, two DENY rows | "Every call passes a policy gate before it runs. Off-plan, denied. Over the limit, denied. Each decision is logged with its policy version." |
| 0:33 | Reject, B2 reverts, B1 stays | "The owner rejects a reading. Only the work built on it is undone, newest first." |
| 0:45 | Stop, `rolled_back` | "Stop rolls back the rest. Each step sits in a SHA-256 hash chain; one edit and verify fails." |
| 0:55 | Title | "Gate, ledger, revert. Load Path." |

## 6. Commands

```
uv run uvicorn web.server:app --port 8000                     # terminal 1
uv run python run_demo.py --reset                             # terminal 2, prints the page URL, waits for clicks
uv run python run_demo.py --reset --auto --wait 0 --step 0    # pre-flight, ends with: demo ok
```

Set `CAPITAL_DB` in `.env` to your own database first. Add `--llm` to let the agents' model pick among the options;
values in section 4 are from the scripted run. For recording, add `present=1` to the page URL.

## 7. UNVERIFIED

- Timings. Verify: run section 4 three times from `--reset`.
- Values with `--llm` (the model may pick another option). Verify: `uv run python run_demo.py --reset --auto --llm --wait 0 --step 0`.
