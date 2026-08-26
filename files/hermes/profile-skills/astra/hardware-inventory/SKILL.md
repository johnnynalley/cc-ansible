---
name: hardware-inventory
description: Use for owned hardware, spare parts, and build inventory.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [hardware, inventory, builds, compatibility]
    related_skills: [hardware-planning, consequential-recommendation]
---

# Hardware Inventory

## Source Of Truth

Use `data/hardware-inventory/parts.csv` from Astra's imported-data working
directory. It is the writable Hermes copy of the preserved OpenClaw tracker.
Read and edit it with a CSV-aware parser. Never infer inventory from chat when
the tracker is available.

Every part must keep a status:

- Active: `active`, `testing`.
- Inactive: `available`, `backup`, `on_order`, `planned`, `retired`.

For active capacity, sum only active statuses. For total capacity, report the
active and inactive split. For spare capacity, use `available` and `backup`.
Report raw storage and, for mirrored storage, usable capacity separately.

## Update Rules

1. Answer the immediate inventory or build question first.
2. Inspect the CSV before deciding whether a record exists. No match means not
   tracked; it is not a command failure.
3. Preserve user labels. Add a normalized model only when verified.
4. Use `unknown` and `verified=no` rather than guessing condition, location,
   connectors, wattage, compatibility, or availability.
5. Probe a live system when access is available before leaving directly
   observable fields unknown. Record whether each part is socketed, soldered,
   swappable, fixed, standard, or proprietary.
6. Never assume an OEM PSU, adapter, or proprietary connector is compatible.
   Verify form factor, pinout, rails, and connectors first.
7. Change status and notes when a part is used, sold, loaned, reserved, or
   retired. Do not delete history.
8. Put future build candidates and unresolved checks under
   `data/hardware-inventory/build-plans/`.
9. Do not store serial numbers, receipts, addresses, or account secrets unless
   Johnny explicitly asks for an appropriate local record.
10. Track physical parts, not VM allocations or virtual disks.

After an edit, parse the full CSV, reject duplicate columns and rows whose
field count differs from the header, and report the row count.

