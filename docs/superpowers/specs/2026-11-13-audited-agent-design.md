# Audited capital-program agents on Atlas — design (T4)

Status: built (event build, 2026-11-14) · approved v2, written before the event · no code existed before Sat 10:45. The sections below are the pre-event design; [Built and not built](#built-and-not-built) records what the code does.
Problem statement: **1. Agents You Can Audit**. Build window: Sat 2026-11-14 10:45 → 17:00 EST.
Guards: [AGENTS.md](../../../AGENTS.md). Plan: [event build](../plans/2026-11-14-event-build.md). Formulas: [formulas.md](../../formulas.md).

## Problem
A public agency picks which bridges to treat with a budget that never covers all of them, and the budget and the
condition data change mid-year. A council or auditor then asks: why this asset and not that one, who authorised the
spend, and what was undone when a fact turned out wrong. Today that answer is rebuilt by hand from several systems.

## What we build
Several agents plan and commit a bridge treatment program across three systems (asset register, budget ledger, work
orders). Every action is tied to a person, checked against policy in Atlas before it runs, and recorded. An owner can
reject a condition update with a reason; everything that depended on it is reverted and a new inspection is requested.

Out of scope: any safety or engineering judgment (agents take published ratings as given) · any vendor product name,
schema or screen · anything from an employer · a dashboard as the main feature.

## Open questions
| Question | State |
|---|---|
| Simulated work-order and budget systems count as "real actions" | UNVERIFIED. Ask a MongoDB judge on site |

Closed: LLM access. The build calls the Gemini API with `LLM_API_KEY` (`core/agents/llm.py`, `run_demo.py --llm`); scripted mode is the default and the tested path.

## Built and not built
Built: policy gate (`core/gate.py`), hash-chained ledger with `verify` (`core/ledger.py`), dependency-scoped revert and full rollback (`core/revert.py`), orchestrator and stop watcher (`core/orchestrator.py`), Intake, Planner, Programming and Work Order agents (`core/agents/`), simulated budget, work-order, inspection and condition systems (`systems/`), MILP and re-solve (`engine/plan.py`, `systems/plans.py`), control page with approve/reject, actor picker and stop (`web/`), demo script (`run_demo.py`).
Not built: Verifier agent, random forest condition check, policy replay, policy edit on the page, writes to `program_lines` (named in `contracts.py`, no tool writes it), multi-document transactions in revert (each undo is a single idempotent update). Data: the Ontario bridge conditions file (Highway 401, Toronto area), not the NBI.

## Architecture
**Deterministic code (never an LLM):**
- **Policy gate:** every tool call from every agent passes through it. Order: stop check → load principal and active
  policy (fresh read) → evaluate → write `decision` event → snapshot → execute → write `executed` event. Any error or
  missing policy is a deny.
- **Orchestrator:** a state machine. Agents hand off through `tasks` documents (claim, act, post result).
- **Ledger:** append-only, hash-chained per session.
- **Revert engine:** finds every transaction that depends on a rejected fact and compensates them newest first.
- **Solver:** MILP for treatment selection under the budget envelope. Code does all arithmetic.

**Agents (each its own principal, least privilege):**
| Agent | Does | May write | Denied |
|---|---|---|---|
| Intake | Proposes a condition update from an inspection record | `condition_records` (pending) | Approving or editing a rating |
| Planner | Builds solver inputs, runs the MILP, proposes a program, explains it | `plans`, `program_lines` (proposed) | Committing money |
| Programming | Commits budget for lines in the approved plan | `budget_ledger` | Exceeding spending limit or envelope |
| Work Order | Creates draft work orders for committed lines | `work_orders` | Acting without a commitment; releasing against an unapproved condition |
| Verifier (stretch) | Reads the systems back and reconciles | nothing | Any write |

**Humans:** owner/manager approves or rejects condition updates and releases; only a human with that role for the
asset's region can. A rejection requires a reason (schema-enforced).

**Policies (documents, versioned, one active per tool):** separation of duties · delegated spending limit ·
budget envelope · jurisdiction · provenance of condition records · release requires approved condition.

**Collections:** control: `principals`, `policies`, `sessions`, `tasks`, `audit_events`, `saga_stack` ·
domain: `assets`, `condition_records`, `plans`, `program_lines`, `budget_ledger`, `work_orders`, `inspection_requests`.
Schema validation on all control collections. Every domain write carries `depends_on` (the condition record or
upstream transaction it relied on).

**Atlas features used:** schema validation, change streams (stop signal, UI feed), unique indexes (chain integrity,
one active policy per tool), transactions where a revert touches several documents.

**UI:** one web page: live ledger feed, the owner's approve/reject control, a stop button, a policy edit. It is the
control surface for the run, not a chart page.

**Stack** (installed and smoke-tested in a throwaway environment on 2026-11-13, then deleted; wheels stay in the uv cache):
| Need | Choice | Version tested | Licence (package metadata) |
|---|---|---|---|
| Runtime | Python via `uv` | 3.13.3 | — |
| Atlas driver | `pymongo` (sync; one thread for the change stream) | 4.20.0 | Apache-2.0 |
| TLS roots | `certifi`, passed as `tlsCAFile` | 2026.10.23 | read LICENSE at install |
| MILP | `scipy.optimize.milp` (HiGHS inside SciPy; no separate solver package) | 1.18.1 | BSD-style; read LICENSE at install |
| Random forest | `scikit-learn` | 1.9.1 | BSD-3-Clause |
| Web server + live feed | `fastapi` + `uvicorn`, server-sent events | 0.162.7 / 0.54.0 | MIT / BSD-3-Clause |
| Shapes | `pydantic` | 2.14.3 | MIT |
| Page | one static HTML file, plain JavaScript, no build step | — | — |
| LLM | provider unknown; `anthropic` 2.8.0 and `openai` 3.51.0 are cached; one function hides the choice | — | Apache-2.0 |

Measured to the sandbox (AWS us-west-1) before the event: connect + ping 844 ms · read by `_id` median 83 ms · change stream
delivery 469 ms. The gate makes about five round trips per tool call, so expect roughly half a second per action.
**Without `certifi` the driver failed with `CERTIFICATE_VERIFY_FAILED` on macOS.** Never disable TLS verification.
Venue network latency: UNVERIFIED; re-measure on site.

Lanes meet only through collections, so a lane can be written in another language if its owner prefers; the solver
and model lane is Python.

**Data:** FHWA National Bridge Inventory, one state, one county for the live demo; loaded into Atlas after 10:45.
Raw files were downloaded before the event, unmodified, outside every repo, with URLs, dates and hashes recorded
alongside them: NBI 2025 (624,193 rows, 123 columns, the latest; no 2026 file exists) and NBI 2024
(623,218 rows), NBI 2016–2023 for history (2019–2025 share one layout), plus Ontario bridge conditions (5,053 rows, a condition index per year
2000–2020). The NBI files carry condition ratings, deck area, county, owner and improvement-cost columns; how well
the cost columns are filled is not checked. Any cost not taken from the data is an assumption and labelled as such.
Model accuracy is unknown until trained. The repo's README must name both sources and carry Ontario's attribution.

## Stages (main is demoable after each)
| Stage | Ends | Adds | Check |
|---|---|---|---|
| 0 Eligible | 11:15 | Public repo, licence, `.env.example`, validators, indexes, seed, agreed document shapes | Bad insert rejected (code 121); no secrets |
| 1 Skeleton | 12:00 | One agent, one tool through the gate, one event on the page | Deny leaves the target unchanged; decision event precedes the write |
| 2 Base | 13:15 | Programming + Work Order agents, hash chain, stop, full rollback | Stop from the page reverts to pre-run state within 2 s |
| 3 Approval | 14:00 | Owner approve/reject with reason, dependency-scoped revert, new inspection request | Reject reverts exactly the dependants, nothing else |
| 4 MILP | 14:45 | Planner solves on real data; plan-bound gate; re-solve after a rejection | Same inputs give the same plan; off-plan action denied |
| 5 Stretch | 15:30 | Random forest condition check (hold vs proceed), policy replay, Verifier | Model beats "same as last year" on held-out data, or is dropped |
| Freeze | 15:30 | Rehearse three times, README, video | Submit by 16:45 |

Record a fallback one-minute video when Stage 3 passes.
Cut order: Verifier → policy replay → random forest → MILP re-solve. Never cut Stages 0–3.

## Lanes
| Lane | Owns | Stage 0–2 | Stage 3–5 |
|---|---|---|---|
| A Control plane | gate, ledger, orchestrator, stop, revert engine | gate, ledger, stop, rollback | dependency revert, plan-bound gate |
| B Engines and systems | data load, domain collections with undo, solver, model | seed, three systems with undo | MILP, re-solve, random forest |
| C Agents and surface | agent loop, scripted mode, web page, demo, README, video | page with ledger feed and stop | approve/reject control, demo script, video |

Team of two: **Sagar** takes lane A plus the agent loop; **Arad** takes lane B plus the page; demo and README are
shared after the freeze. First 25 minutes together: agree every document shape and tool name; change them later only
by agreement. Merge to main through a PR at 12:00, 13:15, 14:00, 14:45, 15:30.
Tasks, file ownership, contracts and the gate checklist: [plan](../plans/2026-11-14-event-build.md).

## Demo (3 minutes)
| Time | On screen | Line |
|---|---|---|
| 0:00 | Real county bridge data, the budget | "Agencies can't fund every bridge, and can't always say who decided what." |
| 0:20 | Planner solves; agents commit; ledger fills with person, policy, reason | "Every action is checked in Atlas before it runs." |
| 0:55 | Planner tries to commit budget: denied. Over-limit commitment: denied | "Each agent can only do its own job." |
| 1:25 | Owner rejects a condition update with a reason; dependent orders and budget revert; plan re-solves; new inspection opens | "One wrong fact, and only what depended on it is undone." |
| 2:15 | Stop mid-run; rollback | "Stop it and undo it." |
| 2:35 | Edit a ledger entry; verify flags it | "The record shows if it was altered." |

One-minute video: the 0:20, 0:55 and 1:25 beats only.

A demo that breaks live costs more than Stage 5 adds.

## Acceptance criteria
| # | Criterion |
|---|---|
| AC1 | Every tool call has a `decision` event written before it executes, naming session, person, agent, policy version |
| AC2 | With Atlas unreachable or no matching policy, the action does not run |
| AC3 | An agent calling another agent's tool is denied and the target is unchanged |
| AC4 | Only a human owner/manager for the asset's region can approve; a rejection without a reason is refused by validation |
| AC5 | A rejection reverts every dependent transaction and no other, and opens an inspection request |
| AC6 | Stop halts all agents before their next action within 2 s and rolls the session back |
| AC7 | The ledger alone reproduces the run; an edited entry is flagged |
| AC8 | A solve stored in `plans` re-runs to the same result |
| AC9 | Public repo, open licence, no secrets, sandbox cluster only, README states what was built at the event and which inputs are assumptions |

## Verified on the sandbox (2026-11-13)
MongoDB 9.0.7 on M10 · change stream opens · `$jsonSchema` validator rejects an invalid insert (code 121) · multi-document transaction commits · DB user has role atlasAdmin.
