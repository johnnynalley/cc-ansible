---
name: consequential-recommendation
description: Use when advice may cause a consequential commitment.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [decision, purchase, compatibility, commitment]
    related_skills: [evidence-led-investigation, guided-operation]
---

# Consequential Recommendation

## Overview

Use this procedure when the user may spend money, alter infrastructure, expose
data, or make another hard-to-reverse commitment. The goal is one defensible
decision grounded in the user's actual constraints and current commitments,
not a shifting list of plausible products or architectures.

## When to Use

- Recommending hardware, software, subscriptions, providers, deployment
  architecture, or a security-sensitive action.
- Revisiting advice after the user bought, ordered, configured, or deployed
  something based on an earlier recommendation.
- Comparing options whose compatibility or benefit depends on exact variants.

Do not load this for low-cost, reversible preference questions with no material
downside.

## Procedure

1. **Create a constraint ledger.** Record the objective, non-negotiable
   requirements, environment, budget, physical limits, privacy constraints,
   owned items, ordered items, and decisions already made in the thread.
   Completion: the recommendation cannot silently discard a user commitment.
2. **Identify exact candidates.** Resolve model, revision, region, connector,
   firmware role, plan tier, or other variant that determines compatibility.
   Completion: evidence describes the item the user can actually buy or use,
   not a nearby family member.
3. **Verify decisive claims.** Use current primary sources for availability,
   price, compatibility, supported behavior, and safety limits. Marketplace
   copy may establish the seller's claim but not measured performance.
   Completion: fact, inference, and unknown are labeled separately.
4. **Compare complete systems.** Include required accessories, power, enclosure,
   mounting, subscriptions, workflow, maintenance, and deployment constraints.
   Do not rank a component specification as if it were end-to-end performance.
   Completion: each option is evaluated in the user's real installation.
5. **Apply commitment-aware ranking.** If the user already acted on prior
   advice, keep that option unless it is incompatible, unsafe, fails a hard
   requirement, or a materially better alternative justifies the switching
   cost. Do not reverse advice for marginal evidence. Completion: sunk effort
   and return or migration cost are explicit.
6. **Choose one recommendation.** State yes, no, or the leading option first.
   Include only hard gates that truly block success, then state what remains
   experimental. Completion: the user knows what to do next without comparing
   an unranked wall of alternatives.
7. **Define acceptance evidence.** Specify the test that would confirm success,
   the result that would reject the option, and what would remain inconclusive.
   Completion: post-purchase testing cannot be mistaken for pre-purchase proof.

## Common Pitfalls

1. Treating connector fit, a listing title, or a nominal gain number as proof
   of real-world performance.
2. Recommending a different purchase immediately after the user trusted the
   previous one without a material incompatibility or safety finding.
3. Comparing boards while ignoring enclosure, antenna, power, placement, and
   the network role they perform.
4. Giving every caveat equal weight until the recommendation disappears.
5. Using an available test as a purchase gate when it only approximates one
   leg of the final system.

## Verification Checklist

- [ ] User objective and hard constraints are explicit
- [ ] Owned, ordered, and deployed commitments are current
- [ ] Exact variants and decisive compatibility claims are verified
- [ ] Complete-system costs and constraints are compared
- [ ] One recommendation and only true blocking gates lead the answer
- [ ] Acceptance, rejection, and inconclusive outcomes are defined
- [ ] Any changed recommendation is justified by material new evidence
