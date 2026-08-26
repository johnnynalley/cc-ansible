---
name: hardware-planning
description: Use for consequential hardware and deployment choices.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [hardware, planning, compatibility, testing]
    related_skills: [hardware-inventory, consequential-recommendation]
---

# Hardware Planning

Build one current-source-grounded recommendation from a stable requirement
ledger. A newly mentioned product updates the comparison; it does not reset
the task.

## Workflow

1. Read the active project reference and the hardware inventory when owned
   parts matter. Purchases, ownership, returns, deployments, and test results
   are state.
2. Record the objective, must-haves, exclusions, weighted preferences,
   deployment constraints, unknowns, current leader, and invalidated options.
3. Model each complete system: role, mobility, power, protocol or band,
   antenna or placement, host and peer dependencies, physical feasibility,
   external services, and mutually exclusive modes.
4. Verify volatile facts from current official compatibility matrices,
   configurators, release assets, and specifications; then independent
   measurements; then customer reports as failure signals. Timestamp current
   facts.
5. Compare equal dimensions: complete package, performance, power,
   reliability, setup burden, cost, returnability, and role fit. Separate fact,
   inference, and unknown.
6. Change the leader only when a requirement, verified fact, or weighting
   changed. After purchase, reversal requires a safety or compatibility defect,
   failure against a hard requirement, or a clearly larger benefit after cost
   and return friction.
7. When deployment performance is unknown, define the smallest reversible
   test with fixed conditions, observable success, and explicit branches. Do
   not invent numeric thresholds.
8. Persist purchases, decisions, rejected options, tests, and results in the
   project reference.

Lead with one recommendation, decisive reasons, material tradeoffs, what not
to buy yet, the exact next test, and the branch for each result.

