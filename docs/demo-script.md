# Demo script

Narration, a 3-minute live demo and a one-minute video. Every on-screen value is from
`uv run python run_demo.py --reset --auto --llm --wait 0 --step 0` on 2026-11-14.
Timings are targets, not rehearsed.

## 1. Scenario and problem

A road agency owns 198 bridges on one highway corridor. The budget never covers all of them. Condition readings
and budgets change during the year.

The agency lets software agents do the routine steps: take in a new reading, re-solve the treatment plan, commit
budget, open work orders.

Then a council member or an auditor asks three questions:

1. Why this bridge and not that one?
2. Who authorised the spend?
3. A reading turned out wrong. What was built on it, and was it undone?

Today the answer is rebuilt by hand from several systems. With agents acting in seconds the gap widens: an agent
can act on a fact nobody has approved yet.

## 2. What Load Path does

Every action, by an agent or a person, takes one route: gate, ledger and, if needed, revert.

| Question | Mechanism | What you see |
|---|---|---|
| Who authorised it? | Policy gate: every tool call is checked against the active policy and the session owner's limits before it runs | ALLOW or DENY with the reason, per call |
| Why this bridge? | Code builds and ranks the options; the model only picks an option number and writes the reason | `offered 3, picked 0, by model` and the rationale in the feed |
| What was undone? | Each write records what it depends on; rejecting a fact reverts only the work that rested on it | One bridge's budget and work order revert; the other bridge is untouched |
| Can it be stopped? | Stop rolls back everything still live in the session | Status `rolled_back`, 0 committed lines |

## 3. How it works

- **Four agents, one turn loop** (`core/agents/`, `core/orchestrator.py`). Each round asks intake, planner,
  programming and work-order in order for one step. The loop ends when no agent has an option.
- **Code does the arithmetic.** The plan is a mixed-integer program (`engine/plan.py`): maximise total benefit
  within the envelope, one treatment per bridge. Programming's options are plan lines ranked by benefit per
  dollar, then benefit.
- **The model is boxed in** (`core/agents/llm.py`). It returns an option index and a rationale. Tool and
  arguments come from the code-built option. Invalid JSON, an index out of range, a timeout or a cap returns the
  code's first choice, and the fallback is counted.
- **The gate decides** (`core/gate.py`). Role, spend limit, envelope, jurisdiction, in-approved-plan,
  has-commitment. A missing policy or any error is a deny.
- **The ledger** (`core/ledger.py`). Every decision and result is an event in a SHA-256 hash chain per session.
  It detects edits and gaps; it does not prevent them.
- **Revert** (`core/revert.py`). A saga stack of undo actions. A rejection follows the dependency links and
  undoes only that set, newest first, then opens an inspection request and re-solves the plan. A denied re-plan
  ends the session `failed`.
- **Data layer.** Policies, sessions, tasks, ledger and the simulated budget and work-order systems are
  collections in one Atlas database. The page feed is a change stream on the ledger.

## 4. Live demo (3 minutes)

Before speaking: page server running, `run_demo.py --reset --llm --pause` started, page open from the printed
URL as `user:owner_a`. With `--pause` the script waits for Enter in the terminal before each agent section, so
the speaker sets the pace. With `--pause page` it waits for the Continue button on the page instead, so
everything happens on the page; read "Enter" below as "Continue".

Scripted mode (no `--llm`) runs the same beats with code-written rationales and no model call. Use it if the
network or the model is slow.

| Time | Do | On screen | Say |
|---|---|---|---|
| 0:00 | Show the `rules` block the script printed in the terminal, then Enter | Terminal: active policies, the two people and their limits, the envelope. Then the page, empty feed | "An agency has 198 bridges and a budget that covers some of them. Agents now do the planning and the spending. Three questions follow: why this bridge, who said yes, and what was undone when a fact was wrong." |
| 0:20 | Approve the pending reading | Intake proposes a reading for 22X-0161/B1, labelled MOCK. After Approve: plan with 190 lines, 249,979,760 of a 250,000,000 envelope | "A new reading arrives. Nothing is planned on it until the owner approves. Then the planner solves the program in code: 190 treatments inside the envelope." |
| 0:45 | Point at the feed (runs by itself after Approve) | `agent:programming offered 3, picked 0, by model`; commit 2,179,210 for 22X-0161/B3; work order opens | "Programming had three plan lines to choose from. They tie on benefit per dollar, so it took the larger benefit and wrote why. The model picks from a list. It cannot invent a bridge or an amount." |
| 1:10 | Enter, then point at the two DENY rows | DENY `in_approved_plan` for 12,345; DENY `spend_limit` for 100,050,000 against a 100,000,000 limit | "Two probes. An amount that is not in the plan: denied. An amount above the owner's limit: denied. The gate decides, not the agent." |
| 1:30 | Enter; wait for the work-order row; switch actor to `user:engineer_b`, Approve | Second MOCK reading for 22X-0161/B2 pending; budget 1,844,400 and a work order already rest on it; DENY `role` | "A second reading arrives and agents act on it while it is still pending. The engineer tries to approve it. Wrong role: denied." |
| 1:55 | Switch to `user:owner_a`, type a reason, Reject | B2 budget released, B2 work order cancelled, B3 still committed, inspection request opened, plan re-solved without B2 | "The owner rejects the reading. Only what depended on it is undone: that bridge's budget and work order. The other bridge is untouched. An inspection is requested and the plan is re-solved without it." |
| 2:30 | Stop | Status `rolled_back`, committed lines 0 | "The owner can stop the whole session. Everything still live is rolled back, and every step of that is in the ledger." |
| 2:45 | Nothing | Feed | "Why this bridge: the rationale. Who said yes: the gate decision. What was undone: the revert. One path for every action." |

Speaker rules: say "mock reading" when it appears; costs are assumptions; no statement about bridge safety.

If Reject is clicked before the script asks for it, the run still ends cleanly: the script prints that beats 11
and 12 were skipped, checks the revert, and waits for Stop. Stop at any point rolls back and prints `demo ok`.

## 5. One-minute video

Five shots, one point each.

| Time | Shot | Voice-over |
|---|---|---|
| 0:00 | Title, then the empty page | "Agents can now spend public money. Who said yes? Why this bridge? And what happens when a fact turns out wrong?" |
| 0:12 | Programming's pick line and the commit row | "Why this bridge: code ranks the options, the agent picks one and writes the reason." |
| 0:24 | The two DENY rows | "Who said yes: every call goes through a policy gate. Off-plan, denied. Over the limit, denied." |
| 0:36 | Reject, then B2 reverting while B3 stays | "A fact turns out wrong: the owner rejects it, and only the work built on it is undone." |
| 0:50 | Stop, status `rolled_back`, then the logo | "One path for every action: gate, ledger, revert. Load Path." |

## 6. Commands

```
uv run uvicorn web.server:app --port 8000                          # terminal 1
uv run python run_demo.py --reset --llm --pause                    # terminal 2, prints the page URL; Enter per section
uv run python run_demo.py --reset --llm --pause page               # same, Continue button on the page per section
uv run python run_demo.py --reset --auto --llm --wait 0 --step 0   # pre-flight, ends with: demo ok
```

Set `CAPITAL_DB` in `.env` to your own database first. For recording, add `present=1` to the page URL.

## 7. UNVERIFIED

- Timings. Verify: run section 4 three times from `--reset`.
- A run with a person clicking in a browser. `--auto`, `--pause` with piped Enters, and a driver calling the
  page's server routes were run; the page itself was not. Verify: the first two commands in section 6, then the
  clicks in section 4.
- Ledger tamper check: not in this script. Covered by `tests/core/test_ledger.py`.
