# Algoma Data Engineer Take-Home: National Housing Market Layer

**Expected time:** 2–3 hours, including time with AI assistants. Please don't spend more than three. You won't finish everything, so tell us in your PR what you chose to do and what you left out.
**Allowed tools:** anything, including AI assistants.
**Deadline:** Wednesday 2026-10-31, 5pm ET

## Background

Our analysts use a national county map of house price appreciation. You're building it from the public files in `data/`. `data/SOURCES.md` says where each one came from.

## Parts

**Part 1:** A county layer for the 50 states and DC, with appreciation over the latest year and over the last five years, for use on a web map.

**Part 2:** Fewer blank counties.

**Part 3:** Release history. `data/fhfa/` has more than one release.

**Part 4:** Which counties appreciated the most? Where are the clusters of high and low appreciation?

## What to hand in

- Code that rebuilds everything, matching the interfaces below.
- `NOTES.md`: the decisions that most affect the numbers (what you chose, what you rejected, and why), what the layer can't tell an analyst, your Part 4 answers, and how you used AI, including one place you overruled it.
- A pull request from a `submission` branch into `main`, written for a teammate. Commit as you go.

## How we evaluate

We run hidden checks against your code, outputs and database, and read your notes and PR. In the follow-up, you'll walk us through your submission and change it live, screen-shared, without an AI assistant.

## Interfaces (our checks depend on these)

Use Python 3.11+. `docker compose up -d` starts PostGIS (set `POSTGIS_PORT` if 5432 is taken). Read `DATABASE_URL`, defaulting to `postgresql://takehome:takehome@localhost:5432/takehome`.

| Command | Does |
| --- | --- |
| `python -m src.part1 [release_dir]` | Builds the layer for one FHFA release folder (default `data/fhfa`). Writes `output/counties.parquet` (full resolution) and `output/counties.geojson` (RFC 7946, at most 8 MB, no gaps or overlaps between counties) |
| `python -m src.part2 [release_dir]` | Rewrites both files with the Part 2 changes |
| `python -m src.part3 [release_dir]` | Builds that release and loads it into PostGIS. Running it twice for the same release changes nothing |
| `python -m src.part4` | Writes the Part 4 outputs |

A later part may run an earlier part's code.

**Layer properties:**

| Property | Meaning |
| --- | --- |
| `geoid` | Five-digit county FIPS from the boundary file |
| `name` | Census name with suffix |
| `state` | USPS code |
| `hpi_yoy_pct` | Percent change in FHFA's `HPI` from the year before the latest year to the latest year (`5.2` means 5.2%) |
| `hpi_cagr_5y_pct` | Compound annual growth of `HPI` over the five years ending in the latest year, in percent |
| `status` | `published` when the value is FHFA's own county figure. Any other values are yours to define in `NOTES.md` |

**Database objects:**

| Object | Returns |
| --- | --- |
| `hpi_as_of(d date)` | `fips, year, hpi`: FHFA county values as published, from the newest release published on or before `d` |
| `layer_as_of(d date)` | At least `geoid, status, hpi_yoy_pct, hpi_cagr_5y_pct`, as the layer was for that release |
| `hpi_revisions` | View from `sql/revisions.sql`: at least `fips, year, old_hpi, new_hpi` for the two most recent releases |
| `status_changes` | View from `sql/revisions.sql`: at least `geoid, old_status, new_status` |

**Part 4 outputs:** `output/rankings.csv` (your answer: one row per county in it, best first, with a `geoid` column) and `output/clusters.csv` (with `geoid` and `cluster` columns). Commit these. Don't commit the layer files.

`pytest` runs a few public format checks after `python -m src.part1`.

If something is unclear, decide, write down why, and keep going.
