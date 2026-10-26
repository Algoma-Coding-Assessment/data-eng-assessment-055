# Notes

National county layer of house price appreciation from FHFA's annual county HPI, with release history in PostGIS and answers to "who appreciated most, and where are the clusters".

Numbers below come from the two releases in `data/fhfa/`. "Old" is FHFA's release of 2025-03-25 (latest year 2024) and "next" is the release of 2026-03-31 (latest year 2025). The committed `output/rankings.csv` and `output/clusters.csv` are for the next release.

## How to rebuild

```
conda env create -f environment.yml && conda activate algoma-hpi   # or: pip install -r requirements.txt
docker compose up -d
python -m src.part1 [release_dir]      # layer files, FHFA figures only
python -m src.part2 [release_dir]      # layer files with Part 2 fills
python -m src.part3 data/fhfa          # load the old release into PostGIS
python -m src.part3 data/fhfa/next_release
python -m src.part4                    # rankings.csv, clusters.csv from the newest loaded release
pytest
```

The checks behind the decisions below are in the notebooks, cited by step:

| Notebook | Contents |
|---|---|
| [`notebooks/01_explore_data.ipynb`](notebooks/01_explore_data.ipynb) | Profile of every file in `data/` |
| [`notebooks/02_census_walkthrough.ipynb`](notebooks/02_census_walkthrough.ipynb) | How the Census files fit together, with a worked ZIP-to-county example |
| [`notebooks/03_part1_layer.ipynb`](notebooks/03_part1_layer.ipynb) | Part 1 prototype |
| [`notebooks/04_part2_fill.ipynb`](notebooks/04_part2_fill.ipynb) | Part 2 prototype, back-test, and a report for both releases |
| [`notebooks/05_part3_history.ipynb`](notebooks/05_part3_history.ipynb) | Part 3 prototype against PostGIS |
| [`notebooks/06_part4_answers.ipynb`](notebooks/06_part4_answers.ipynb) | Part 4 prototype, with maps |

## Decisions that most affect the numbers

### Part 1: the layer

Every county gets two numbers, computed from FHFA's `HPI` column for one latest year **L**:

```
hpi_yoy_pct     = (HPI[L] / HPI[L-1] - 1) * 100
hpi_cagr_5y_pct = ((HPI[L] / HPI[L-5]) ^ (1/5) - 1) * 100
```

For example, Autauga County, AL in the next release: HPI is 193.66 in 2020, 280.45 in 2024 and 285.46 in 2025, so YoY = 1.79% and 5-year CAGR = 8.07%. Only those three years are read; the years in between don't enter either formula.

**1. Which year is "latest"**
- **Chosen:** one year for the whole release, the newest year whose county coverage is at least 90% of the year before. That gives **2024** for the old release and **2025** for the next one.
- **Rejected:** each county's own last year with data. 154 counties (old) and 118 (next) have their last value before L. They would show, say, 2021 vs 2020 on a map labelled with the latest year, and nothing on the map would say so.
- **Checked:** 2025 is a complete year in the next release. Every county in the file has a 2025 row, 2,677 have a value (2024: 2,666), and the number of counties gaining or losing a value is in line with earlier years ([03, Step 2](notebooks/03_part1_layer.ipynb)). Each FHFA release re-estimates the whole history rather than updating some counties: 98,672 of the 102,710 county-years in both releases changed ([01, section 1, "Revisions between releases"](notebooks/01_explore_data.ipynb)).

**2. Missing years give a blank, never a substitute**
- **Chosen:** if HPI[L] or HPI[L-1] is missing, YoY is blank. If HPI[L] or HPI[L-5] is missing, the CAGR is blank.
- **Rejected:** using the nearest available year. About 400 county series have gaps; e.g. Coosa, AL has 2022, a blank 2023, then 2024. Bridging the gap would present a two-year change as a one-year change ([01, section 1, "Gaps inside series"](notebooks/01_explore_data.ipynb); [03, Step 3](notebooks/03_part1_layer.ipynb)).
- FHFA's own `Annual Change (%)` column agrees with the HPI ratio to rounding (max difference 0.017 pt), but it can't give the 5-year figure. Both metrics come from the `HPI` column so they're consistent ([01, section 1](notebooks/01_explore_data.ipynb)).

**3. `status` says which input is missing**

| Status | Meaning | Old (2024) | Next (2025) |
|---|---|---|---|
| `published` | HPI[L], HPI[L-1] and HPI[L-5] present: both values are FHFA's | 2,543 | 2,611 |
| `partial_no_yoy` | HPI[L-1] missing: CAGR only | 76 | 63 |
| `partial_no_cagr` | HPI[L-5] missing: YoY only | 2 | 1 |
| `no_prior_years` | both HPI[L-1] and HPI[L-5] missing | 4 | 2 |
| `no_latest` | the county is in FHFA's file but HPI[L] is blank | 154 | 118 |
| `not_in_fhfa` | the county isn't in FHFA's file | 365 | 349 |

A single "missing" status would hide *why* a county is blank, and whether its other value is still FHFA's own ([03, Step 4](notebooks/03_part1_layer.ipynb)).

**4. Which counties are in the layer**
- All **3,144** counties of the 2024 Census boundaries (50 states + DC) appear exactly once, with or without data, so the map has no holes.
- In the old release, FHFA still reports Connecticut's 8 pre-2022 counties, which don't exist in the 2024 boundaries (9 planning regions). In Part 1 the 9 regions are therefore `not_in_fhfa`, and Part 2 fills them ([03, Step 5](notebooks/03_part1_layer.ipynb)).

**5. The web GeoJSON (≤ 8 MB, no gaps or overlaps)**
- **Chosen:** simplify all counties together with `shapely.coverage_simplify` (tolerance 0.005°), so each shared border is simplified once and both neighbours keep it. Coordinates are rounded to 5 decimals (~1 m). The file is 6.5 MB, and after writing it is read back and checked: valid, no overlaps, and no new gaps.
- **Rejected:** simplifying each county on its own. The two copies of a shared border move differently and open slivers. Of the other tolerances, 0.002° breaks shared borders after rounding and 0.01° opens a new gap.
- The Census file itself already has 23 narrow openings between neighbouring counties: real water channels along coasts, because the file is clipped to the shoreline. The check is therefore "no gaps beyond those", not "zero gaps" ([03, Step 8](notebooks/03_part1_layer.ipynb)).
- `counties.parquet` keeps the full-resolution shapes. Both files are in WGS84 (EPSG:4326).

### Part 2: fewer blanks

Estimates fill **only blank values**. An FHFA figure is never overwritten, and `yoy_source` / `cagr_source` record where each value came from (`fhfa`, `ct_crosswalk`, `zip`). A filled county's status becomes `estimated_ct_crosswalk` or `estimated_zip`, and `coverage` gives the share of its homes behind the estimate.

1. **Connecticut crosswalk (old release).** Each planning region gets the housing-unit-weighted average of the old counties its towns came from, with weights from ACS town-level housing units.
   - Checked against FHFA's own region figures in the next release, for the same year: mean absolute error 0.26 pt (YoY) and 0.28 pt (CAGR), part of which is FHFA's own revision between releases ([04, Step 3](notebooks/04_part2_fill.ipynb)).
2. **ZIP estimates.** For a blank county, I take the housing-unit-weighted mean of FHFA's ZIP-level growth rates for the ZIPs that overlap it, computed from the same release and the same years. ZCTA housing units are split across counties by land share.
   - **Guard:** a ZCTA piece that would hold more homes than its whole county is dropped. Example: an El Paso ZCTA stretches into empty Hudspeth County, TX, and by land share would put 14,866 homes in a county with 1,133 ([02, Step 6](notebooks/02_census_walkthrough.ipynb); [04, Step 5](notebooks/04_part2_fill.ipynb)).
   - **Threshold:** a value is filled only if ZIPs with data cover **≥ 50% of the county's homes**. I chose it from a back-test on counties FHFA does publish ([04, Step 6](notebooks/04_part2_fill.ipynb)):

| ZIP coverage of county homes | median abs. error, YoY | median abs. error, 5-yr CAGR |
|---|---|---|
| < 25% | 6.7 pt | 1.2 pt |
| 25–50% | 3.3 pt | 0.6 pt |
| 50–75% | 1.8 pt | 0.34 pt |
| > 75% | 0.7 pt | 0.17 pt |

   Below 50% the YoY error is about as large as a typical county's change (median ~4%).
3. **Rejected: filling from neighbouring counties.** It would empty the map, but it copies neighbours' values into blanks, which manufactures exactly the spatial clusters Part 4 measures.

**Result** ([04, Step 8](notebooks/04_part2_fill.ipynb), status before and after each fill for both releases):

| | Old (2024) | Next (2025) |
|---|---|---|
| Counties filled by the CT crosswalk | 9 | 0 (FHFA publishes the regions) |
| Counties filled from ZIPs | 37 | 31 |
| Counties with no value at all, before → after | 523 → 480 | 469 → 442 |

Most remaining blanks are small counties with few sales, whose ZIPs have no index either. That is a limit of the data, not something I tried to hide.

### Part 3: history

- **A release is keyed by FHFA's publication date** (the "Last updated" line), so `hpi_as_of(d)` means "what FHFA had published by d", whatever day it was loaded. There is no load timestamp, which would change on every run.
- **FHFA values are stored as published**, blanks and the old release's CT county codes included. The layer is stored separately per release, and shapes once (`county_geom`), since both releases use the 2024 boundaries.
- **Idempotent load.** In one transaction per release: copy to a staging table, delete this release's rows that disappeared, and insert or update only rows that differ (`ON CONFLICT … WHERE … IS DISTINCT FROM`). A repeat load reports 0 inserted / 0 updated / 0 deleted, and the md5 fingerprints of all four tables are unchanged ([05, Step 5](notebooks/05_part3_history.ipynb)).
- **`hpi_revisions`** classifies each differing `(fips, year)` as `revised`, `added` or `removed`, with `pct_change` and a `rebased` flag. Almost everything changes between releases ([05, Step 7](notebooks/05_part3_history.ipynb)):
  - about 94k values were revised, with a median change of 0.44%;
  - 139 counties' series now start in a different year. Their whole level shifts (median 8%), so `pct_change` there reflects the new base, not new information.
- **`status_changes`** shows 208 counties. For example, the 9 CT regions go from `estimated_ct_crosswalk` to `published`, and 20 counties go from `published` to `no_latest`.

### Part 4: method

- **Metric: 5-year CAGR**, not YoY. YoY ranges from −24% to +53%, with the extremes in small counties and in series with gaps, and the top 50 by YoY share only 10 counties with the top 50 by CAGR ([06, Step 2](notebooks/06_part4_answers.ipynb)).
- **FHFA figures only.** ZIP estimates are excluded from both answers: their error is enough to move a county many places, and they are built from surrounding areas, which would bias the cluster test.
- **Small counties are kept**, with `housing_units` in `rankings.csv`, rather than cut off at an arbitrary size.
- **Clusters: Local Moran's I** ([06, Steps 3–5](notebooks/06_part4_answers.ipynb)):
  - queen contiguity: counties whose boundaries touch, computed in PostGIS;
  - 999 conditional permutations, p < 0.05, fixed seed, written in numpy;
  - touching counties with the same hot or cold label are joined into numbered regions (`region`: HH-1 is the largest hot spot).

## Part 4 answers (next release, 5-year CAGR 2020→2025)

### Which counties appreciated the most?

2,674 counties with FHFA's own figure are ranked in `output/rankings.csv`.

| Rank | County | 5-yr CAGR | Homes |
|---|---|---|---|
| 1 | Harrison County, MO | 18.9% | 4,008 |
| 2 | St. Clair County, MO | 16.7% | 5,290 |
| 3 | Adams County, ID | 16.6% | 2,674 |
| 4 | Essex County, VT | 16.5% | 4,952 |
| 5 | Perry County, TN | 16.1% | 4,866 |
| 6 | Macon County, GA | 15.8% | 5,135 |
| 7 | Gilliam County, OR | 15.5% | 1,138 |
| 8 | Iron County, MO | 15.5% | 4,682 |
| 9 | Deer Lodge County, MT | 15.3% | 5,540 |
| 10 | Nance County, NE | 15.1% | 1,606 |

- **The leaders are small, rural counties.** The top 100 have a median of 7,890 homes against 15,997 for all ranked counties, so treat individual ranks near the top as noisy.
- **By state**, the top 100 are concentrated in Tennessee (17), Michigan (16), Georgia (10) and Idaho (8).
- **The bottom** is Pecos, TX (0.6%), Lincoln, WV (0.7%) and a run of Louisiana parishes, including Orleans (2.0%).

### Where are the clusters?

Appreciation is strongly clustered: global Moran's I = 0.59. 447 counties are hot spots and 393 cold spots at p < 0.05. At p < 0.01, 228 and 203 remain, in the same regions ([06, Step 4](notebooks/06_part4_answers.ipynb)).

| Region | Counties | Where | Mean 5-yr CAGR |
|---|---|---|---|
| HH-1 | 184 | Southern Appalachians and Southeast: TN, GA, NC, SC | 10.9% |
| HH-2 | 55 | Northern Rockies: ID, MT, OR, UT | 11.2% |
| HH-3 | 49 | Upper Michigan and northern Wisconsin | 11.0% |
| HH-4 | 35 | Northern New England: ME, VT, NH | 11.5% |
| HH-5 | 31 | Northern Lower Michigan | 11.7% |
| LL-1 | 118 | Gulf Coast: LA, MS, AL, TX, including Orleans Parish | 5.3% |
| LL-2 | 48 | Iowa / Illinois farm belt | 6.9% |
| LL-3 | 42 | Northern California and Nevada, including San Francisco | 5.7% |
| LL-4 | 19 | Central Appalachia: WV, KY, OH, VA | 5.8% |
| LL-5 | 17 | Permian Basin: TX, NM, including Midland | 5.4% |

Smaller cold spots include Minneapolis–St Paul (Hennepin, Ramsey, Dakota). There are 55 outliers (`high_low` / `low_high`), e.g. McLean County, ND, a high county among low neighbours. The map is in [06, Step 5](notebooks/06_part4_answers.ipynb).

**The two answers differ on purpose.** Harrison County, MO is first in the ranking but `not_significant` as a cluster (p = 0.18): its neighbours aren't unusually high, so it is a one-county spike, not a regional pattern.

## What the layer can't tell an analyst

- **Price levels.** The HPI is an index of *change*, and its base year differs by county, so index levels can't be compared across counties. The layer only shows growth rates.
- **Real (inflation-adjusted) appreciation.** All figures are nominal.
- **The whole market.** FHFA's all-transactions index uses sales and appraisals on mortgages bought or guaranteed by Fannie Mae and Freddie Mac. Cash purchases, jumbo loans, and government-insured or private loans are missing. FHFA calls the annual county index *developmental*.
- **Precision.** FHFA publishes no sample sizes or confidence intervals. Small counties swing a lot from year to year (YoY from −24% to +53%), and FHFA blanks a county when its sample is too small, so the pattern of blanks is itself a sign of thin data.
- **Stability.** Each release re-estimates the whole history: 97% of values changed between these two releases, and recent years were revised the most. Use Part 3's `hpi_as_of` / `layer_as_of` to reproduce what was known at a given date.
- **Variation within a county.** A county figure averages very different neighbourhoods.
- **Estimated values.** About 0.3–0.6 pt typical error for CAGR and about 2 pt for YoY, from the back-test. They are marked by `status`, `*_source` and `coverage`, and excluded from Part 4.
- **About 440 counties (14%) still have no value**, mostly rural counties in the Plains, Texas and Alaska. They hold only about 1.5% of US housing units ([01, section 5](notebooks/01_explore_data.ipynb)).
- **Mixed geography vintages.** The ZCTA-to-county file is 2020 vintage (pre-2022 CT counties), the housing units are ACS 2020–2024, and the boundaries are 2024.

## How I used AI

> Draft written with the assistant from our session; edit into your own words before submitting.

I worked with Claude Code throughout. I used it to:
- profile the raw files ([01](notebooks/01_explore_data.ipynb));
- explain the Census files step by step ([02](notebooks/02_census_walkthrough.ipynb));
- write a prototype notebook for each part before any module code ([03](notebooks/03_part1_layer.ipynb)–[06](notebooks/06_part4_answers.ipynb));
- set up the conda environment, Docker and PostGIS;
- port the reviewed notebooks into `src/` and `sql/`.

I reviewed each notebook's outputs before asking for the module, and asked for an explanation of anything I didn't follow (the Census files, PostGIS, Local Moran's I).

**Where I overruled it:** its first `status` design had three values: `published` (at least one value present), `insufficient_data` and `not_in_fhfa`. I pointed out that each metric depends on specific years and asked for the status to say *which* input is missing. That gave the six statuses in Part 1, so the 64 counties with only one FHFA value are no longer labelled the same as fully published ones.

I also didn't accept its first "latest year = max year in the file" rule without checking. I had it verify that FHFA re-estimates the whole dataset each release (rather than updating some counties) and that 2025 is a complete year before building on it ([03, Step 2](notebooks/03_part1_layer.ipynb)).
