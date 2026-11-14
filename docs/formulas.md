# Formulas and rules — audited capital-program agents

Design notes; the code is the reference (`core/gate.py`, `core/ledger.py`, `core/revert.py`, `engine/plan.py`). Items marked **not built** were designed and not implemented. Implements the [spec](superpowers/specs/2026-11-13-audited-agent-design.md); task
numbers refer to the [plan](superpowers/plans/2026-11-14-event-build.md). Values marked **set at event** are
chosen from the data after 10:45 and listed in the README as assumptions.

## 1. Policy decision (gate, tasks S1–S2, S5, S7)
A call is `(session, actor, tool, args)`. Let `P` be the one active policy for `tool` and `H` the human the session acts for.

`allow` ⇔ `role` is true (always evaluated, listed in `P.checks` or not) and every other check named in `P.checks` is true, in list order. Otherwise `deny`, with the first failing check as the reason.
Session not found or not `running`, tool not registered, actor missing or inactive, no active policy, a check name with no implementation, or any exception ⇒ `deny`.
Checks that read `args.amount` deny unless it is a finite number > 0; checks that read `args.asset_id` deny unless it is a non-empty string or integer.

| Check | True when |
|---|---|
| `role` | `actor.roles ∩ P.roles ≠ ∅` (`actor.active` is checked before any check) |
| `spend_limit` | `H` = `session.principal_id` is an active human with a numeric `spend_limit`, and `args.amount ≤ H.spend_limit` |
| `envelope` | `Σ amount of committed budget lines in the session + args.amount ≤ session.budget_envelope` |
| `jurisdiction` | `asset.region = session.region`; for a human approval also `asset.region = actor.region` |
| `has_commitment` | a `committed` budget line exists for `(session, asset)` |
| `in_approved_plan` | the session's active plan (highest `seq`, `superseded = false`) has a line with the same `asset_id` and `cost = args.amount` |
| `has_reason` | `args.reason` is a string with at least one non-space character (`reject_condition`) |

## 2. Ledger hash chain (task S1)
`h₀_prev = "0" × 64`
`hₙ = SHA-256( hₙ₋₁ ‖ canon(eₙ without hash) )`
`canon` = JSON with sorted keys, no whitespace, dates as ISO-8601 truncated to milliseconds, ObjectIds as hex.
`verify(session)` recomputes in `seq` order and returns `(True, None)`, or `(False, n)` for the first position `n` where `seq ≠ n`, `prev_hash ≠ hₙ₋₁` or the stored hash differs. If the session document exists and its `audit_head` is not the last hash, it returns `(False, last + 1)` (events removed from the end).
Limit: the chain detects edits and gaps; it does not prevent them. Prevention needs an insert-only database role (not yet confirmed possible in the sandbox).

## 3. Dependency-scoped revert (task S6)
Each saga entry `s` has `s.produced` (the id it wrote) and `s.depends_on` (ids it relied on).
For a rejected condition `c`, the revert set `D(c)` is the smallest set such that:
- `s ∈ D(c)` if `c ∈ s.depends_on`;
- `s′ ∈ D(c)` if `s.produced ∈ s′.depends_on` for some `s ∈ D(c)`.

Compensate `D(c)` in descending `seq`. Entries outside `D(c)` are untouched. A whole-session rollback is the same procedure over every `done` entry.
Each undo is idempotent, so an entry found `armed` (outcome unknown) is compensated too.

## 4. Treatment selection — MILP (task A6)
Candidates `i ∈ I`, each a (bridge, treatment) pair with cost `cᵢ > 0` and benefit `bᵢ ≥ 0`. Decision `xᵢ ∈ {0,1}`.

```
maximise   Σᵢ bᵢ xᵢ
subject to Σᵢ cᵢ xᵢ ≤ E                      budget envelope
           Σ_{i ∈ I(a)} xᵢ ≤ 1   for each bridge a      one treatment per bridge
           xᵢ = 1  for i ∈ F                 lines already committed and kept
           xᵢ = 0  for i ∈ X                 bridges whose condition is pending or rejected
```
- `E` = `session.budget_envelope`, the number the gate's `envelope` check reads. Regional caps `K_r` and conflict pairs: **not built**.
- After a rejection: move that bridge's candidates into `X`, keep surviving commitments in `F`, re-solve.
- One candidate per (approved condition record, treatment): `cᵢ = round(rateₜ · A, 2)`, `bᵢ = round(min(Δₜ, 100 − rating) · A, 2)`, with `A` the deck area and `(Δₜ, rateₜ)` from `TREATMENTS` in `engine/plan.py` (assumptions, README). No traffic weight.
- Budget commit is one atomic upsert keyed by the idempotency key `<session_id>:<seq>` (`$setOnInsert`), so a repeat writes nothing. The envelope and spend limit are enforced by the gate checks in section 1, not in the write.
- Stretch Monte Carlo gate rule: **not built**.
- Recorded with each plan: `status` (`optimal` or `infeasible`), `objective`, `lines`, and `inputs_hash = SHA-256(JSON with sorted keys of {candidates sorted by (asset_id, treatment), envelope, fixed, excluded})`. Policy versions and solver version are not recorded.
- Repeatability is a test (`test_solve_is_repeatable`), not an assumption. If ties make it fail, order candidates by id and add a tie-break term far smaller than the smallest benefit gap.
- "Why not bridge j?" (re-solve with `xⱼ = 1` forced, report `z* − z*(xⱼ=1)`): **not built**.

## 5. Condition check — random forest (task A7, stretch; **not built**)
- **Sample:** a bridge present in year `t` and `t+1` with a newer inspection date in `t+1`. Bridges not re-inspected are excluded (an unchanged rating there is not evidence of no change).
- **Target:** the rating in `t+1`. **Features:** rating in `t`, age, traffic, structure type, deck area, owner.
- **Baseline:** predict the rating in `t`. Keep the model only if its held-out accuracy beats the baseline; report both.
- **Use:** for a proposed rating `y` and prediction `ŷ`, deviation `δ = |y − ŷ|`. `δ ≥ τ` ⇒ hold downstream tasks until the owner decides; otherwise proceed provisionally. `τ`: **set at event** from the held-out error distribution.
- The forest never allows or denies an action. It only chooses between "wait for the owner" and "proceed, revertible".
- Not yet confirmed: that a structure number identifies the same bridge across years.

## 6. Agent relay and feedback loop (task S4)
```
queued → claimed → (agent proposes a tool call) → gate
   allow → executed → task done → orchestrator queues the next agent's task
   deny  → task failed, the deny event is in the feed; no retry
   tool error after the decision → no automatic retry of a write; session failed, a person decides
```
- Handoff payload is the `tasks.output` document, never free text between agents.
- A task is claimed with one atomic update (`queued` → `claimed`), so two workers cannot take it.
- The gate writes a `decision` and an `executed` ledger event per call; the claim is recorded on the `tasks` document, not in the ledger.
- Order for one bridge: Intake → owner decision → Planner → Programming → Work Order. Verifier: **not built**.

## 7. Data preparation checklist (task A4, after 10:45 only)
Written for the NBI file; the build uses the Ontario bridge conditions file instead (`systems/assets.py`). The raw files stay untouched outside the repo; preparation writes to Atlas.
1. Read the 2025 file with the single-quote text qualifier; drop rows whose field count differs from the header.
2. Pick one state and one county; key each bridge by state code + structure number.
3. Inspect the condition columns for non-numeric codes before converting; record how they are handled.
4. Measure how many rows have each cost column filled; decide then whether costs come from the data or are assumptions.
5. Check that the loaded count equals the filtered row count.
