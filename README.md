# Load Path

> In a bridge, the load path is the route a load takes down to the ground. In ours, it is the route every agent action takes through the gate, the ledger and, if rejected, the revert.

MongoDB Agents in Context Toronto Hackathon, 2026-11-14. Team: Sagar Patel, Arad.

Work in progress; built during the event.

## Assumptions
Treatment gains and costs are assumptions, not sourced figures (`TREATMENTS` in `engine/plan.py`). Cost = rate × deck area. Benefit = rating gain × deck area, with the gain capped at 100 − current BCI; no traffic weight.

| Treatment | Rating gain (BCI points) | Cost per m² of deck |
|---|---|---|
| `minor_rehab` | 10 | 500 |
| `major_rehab` | 25 | 2000 |
| `replacement` | 60 | 6000 |
