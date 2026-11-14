# Formulas and rules — audited capital-program agents

Design notes only; no code. Implements the [spec](superpowers/specs/2026-11-13-audited-agent-design.md); task
numbers refer to the [plan](superpowers/plans/2026-11-14-event-build.md). Values marked **set at event** are
chosen from the data after 10:45 and listed in the README as assumptions.

## 1. Policy decision (gate, tasks S1–S2, S5, S7)
A call is `(session, actor, tool, args)`. Let `P` be the one active policy for `tool` and `H` the human the session acts for.

`allow` ⇔ every check named in `P.checks` is true. Otherwise `deny`, with the first failing check as the reason.
No active policy, inactive actor, session not `running`, or any exception ⇒ `deny`.

| Check | True when |
|---|---|
| `role` | `actor.active` and `actor.roles ∩ P.roles ≠ ∅` |
| `spend_limit` | `args.amount ≤ H.spend_limit` |
| `envelope` | `Σ amount of committed budget lines in the session + args.amount ≤ session.budget_envelope` |
| `jurisdiction` | `asset.region = session.region`; for a human approval also `asset.region = actor.region` |
| `has_commitment` | a `committed` budget line exists for `(session, asset)` |
| `in_approved_plan` | the session's approved plan has a line with the same asset and amount |

## 2. Ledger hash chain (task S1)
`h₀_prev = "0" × 64`
`hₙ = SHA-256( hₙ₋₁ ‖ canon(eₙ without hash) )`
`canon` = JSON with sorted keys, no whitespace, dates as ISO-8601 truncated to milliseconds, ObjectIds as hex.
`verify(session)` recomputes in `seq` order and returns the first `seq` where the stored hash differs or `seq` is not `n`.
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
           Σ_{i ∈ I(r)} cᵢ xᵢ ≤ K_r for each region r   regional cap (optional)
           xᵢ + xⱼ ≤ 1  for each (i, j) ∈ C  conflict pair: two works that must not run together (optional; C from adjacency or shared-corridor data, only if the data supports it)
           xᵢ = 1  for i ∈ F                 lines already committed and kept
           xᵢ = 0  for i ∈ X                 bridges whose condition is pending or rejected
```
- `E`, `K_r`: from the session and policy documents, so the solver and the gate read the same numbers.
- After a rejection: move that bridge's candidates into `X`, keep surviving commitments in `F`, re-solve.
- `bᵢ = Δᵢ · A · u` where `Δᵢ` is the rating gain the treatment gives, `A` the deck area, `u` a traffic weight. The treatment list, `Δᵢ`, `u` and any cost not present in the data: **set at event**.
- Candidate NBI inputs for `u` and the conflict set (column names read 2026-11-14 from the 2025 file header; fill rates UNVERIFIED): `ADT_029`, `FUTURE_ADT_114`, `PERCENT_ADT_TRUCK_109`, `DETOUR_KILOS_019`; cost: `TOTAL_IMP_COST_096`. Add a term only if the county's columns are populated; every weight is an assumption the README names.
- Budget commit is one atomic update guarded by `remaining ≥ amount` (no read-then-write), with the idempotency key under a unique index.
- Stretch gate rule (Stage 5, after the forest): deny `propose_plan` when a fixed-seed Monte Carlo of plan cost exceeds the envelope with probability above a policy threshold. Cost spread is an assumption; drop if unlabeled data cannot support it.
- Record with each plan: `inputs_hash = SHA-256(canon(candidates, E, K, F, X))`, policy versions, solver name and version, status, objective.
- Repeatability is a test (`test_solve_is_repeatable`), not an assumption. If ties make it fail, order candidates by id and add a tie-break term far smaller than the smallest benefit gap.
- "Why not bridge j?": re-solve with `xⱼ = 1` forced; report `z* − z*(xⱼ=1)`, the benefit the program would lose.

## 5. Condition check — random forest (task A7, stretch)
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
   deny  → reason returned to the agent → revised proposal, at most 2 retries → task failed, shown on the page
   tool error after the decision → no automatic retry of a write; session failed, a person decides
```
- Handoff payload is the `tasks.output` document, never free text between agents.
- A task is claimed with one atomic update (`queued` → `claimed`), so two workers cannot take it.
- Every hop (claim, proposal, decision, result) is a ledger event, so the relay itself is reconstructible.
- Order for one bridge: Intake → (owner decision or provisional) → Planner → Programming → Work Order → Verifier.

## 7. Data preparation checklist (task A4, after 10:45 only)
The raw files stay untouched outside the repo; preparation writes to Atlas.
1. Read the 2025 file with the single-quote text qualifier; drop rows whose field count differs from the header.
2. Pick one state and one county; key each bridge by state code + structure number.
3. Inspect the condition columns for non-numeric codes before converting; record how they are handled.
4. Measure how many rows have each cost column filled; decide then whether costs come from the data or are assumptions.
5. Check that the loaded count equals the filtered row count.
