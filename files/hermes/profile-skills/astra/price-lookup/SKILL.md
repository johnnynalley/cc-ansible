---
name: price-lookup
description: Use for current product prices and public listings.
version: 1.0.0
author: ARK Infrastructure
license: Proprietary
platforms: [linux]
metadata:
  hermes:
    tags: [prices, shopping, listings, vehicles]
    related_skills: [financial-decision-support]
---

# Price Lookup

Classify the request as product comparison, used-goods discovery, or vehicle
listing discovery. Use native web search and browsing plus the configured eBay
source when useful. Vehicle appraisal and purchase recommendations belong to
`financial-decision-support`.

For vehicles, lock year, make, model, trim, body or cab, engine, drivetrain,
mileage, location, title status, seller type, asking price, defects,
modifications, and maintenance evidence. Reject parts, accessories, engines,
transmissions, wheels, models, category pages, and mismatched configurations.

Separate retail prices, private and dealer asks, sold evidence, and valuation
estimates. Before presenting results, count relevant matches, identify verified
and missing attributes, report source or credential failures, and inspect low
prices for deposits, payments, damage, stale snippets, or parts. Prefer no
trustworthy comparable over junk results.

Include source, price, condition, direct URL, exact-match attributes, and what
kind of price each number represents. Current prices require current sources.

