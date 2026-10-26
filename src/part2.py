"""Part 2: fewer blanks.

    python -m src.part2 [release_dir]

You may add modules, helpers and dependencies. Keep this command working as described in the README.

Starts from the Part 1 layer and fills blank values, never overwriting an FHFA county figure:

1. Connecticut crosswalk. A release that reports CT's 8 pre-2022 counties (the old one) gets planning
   region values as a housing-unit-weighted average of the old counties its towns came from
   (town housing units from ACS county subdivisions).
2. ZIP estimates. A housing-unit-weighted average of the same release's ZIP-level values (same years
   L, L-1, L-5) over the ZCTAs overlapping the county. ZCTA homes are split across counties by land
   share; a piece that would hold more homes than its whole county is dropped as misallocated.

Either estimate is used only when the areas with data hold at least MIN_COVERAGE of the target's homes.
Neighbour-based filling is deliberately not done: it would manufacture the clusters Part 4 measures.

Added columns:
    yoy_source, cagr_source  fhfa | ct_crosswalk | zip | null (still blank)
    coverage                 share of the county's homes behind its weakest estimate (null if all FHFA)

New statuses (otherwise the Part 1 status is kept):
    estimated_ct_crosswalk   at least one value from the Connecticut crosswalk
    estimated_zip            at least one value from ZIPs (the other may still be FHFA's)
"""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src import part1

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

CENSUS = DATA_DIR / "census"
ACS_HOUSING_UNITS = CENSUS / "acsdt5y2024-b25001.dat"
CT_CROSSWALK = CENSUS / "ct_cou_to_cousub_crosswalk.xlsx"
ZCTA_COUNTY = CENSUS / "tab20_zcta520_county20_natl.txt"

# below this share of homes covered, the back-test error exceeds a typical county's annual change
MIN_COVERAGE = 0.5

# value column -> its source column
METRICS = {"hpi_yoy_pct": "yoy_source", "hpi_cagr_5y_pct": "cagr_source"}

LAYER_COLUMNS = ["geoid", "name", "state", "hpi_yoy_pct", "hpi_cagr_5y_pct", "status",
                 "yoy_source", "cagr_source", "coverage", "geometry"]


# --- inputs -----------------------------------------------------------------------------------


def read_housing_units() -> dict[str, pd.Series]:
    """ACS housing units by summary level: '050' county, '060' county subdivision, '860' ZCTA."""
    acs = pd.read_csv(ACS_HOUSING_UNITS, sep="|", dtype=str, usecols=["GEO_ID", "B25001_E001"])
    level = acs.GEO_ID.str[:3]
    code = acs.GEO_ID.str.split("US").str[1]
    units = pd.to_numeric(acs.B25001_E001)
    return {lvl: pd.Series(units[level == lvl].values, index=code[level == lvl].values) for lvl in ("050", "060", "860")}


def read_ct_crosswalk(town_units: pd.Series) -> pd.DataFrame:
    """One row per Connecticut town: old_county, new_county (planning region), town, units."""
    ct = pd.read_excel(CT_CROSSWALK, dtype=str)
    ct.columns = [c.splitlines()[0] for c in ct.columns]
    ct = ct.dropna(subset=["STATEFP", "COUSUBFP"])  # empty rows at the bottom of the sheet
    ct = ct[ct.COUSUBFP != "00000"]  # 'County subdivisions not defined' (water) placeholders
    xwalk = pd.DataFrame({
        "old_county": ct.STATEFP + ct.OLD_COUNTYFP,
        "new_county": ct.STATEFP + ct.NEW_COUNTYFP,
        "town": ct.STATEFP + ct.NEW_COUNTYFP + ct.COUSUBFP,  # rebuilt: the GEOID columns are Excel formulas
    })
    xwalk["units"] = xwalk.town.map(town_units)
    if xwalk.units.isna().any():
        raise ValueError(f"CT towns without ACS housing units: {sorted(xwalk.town[xwalk.units.isna()])}")
    return xwalk


def read_zcta_pieces(zcta_units: pd.Series, county_units: pd.Series) -> pd.DataFrame:
    """One row per ZCTA x county overlap with its estimated homes; misallocated pieces dropped."""
    rel = pd.read_csv(ZCTA_COUNTY, sep="|", dtype=str, encoding="utf-8-sig")
    rel = rel.dropna(subset=["GEOID_ZCTA5_20"])  # county land outside any ZCTA
    pieces = pd.DataFrame({
        "zcta": rel.GEOID_ZCTA5_20,
        "county": rel.GEOID_COUNTY_20,
        "land_share": pd.to_numeric(rel.AREALAND_PART) / pd.to_numeric(rel.AREALAND_ZCTA5_20),
    })
    pieces["units"] = pieces.zcta.map(zcta_units) * pieces.land_share
    misallocated = pieces.units > pieces.county.map(county_units)
    return pieces[~misallocated]


def read_zip_metrics(release_dir: Path, latest: int) -> pd.DataFrame:
    """Per ZIP: hpi_yoy_pct and hpi_cagr_5y_pct with the same exact-year rule as counties."""
    zips = pd.read_excel(release_dir / "hpi_at_zip5.xlsx", skiprows=5, usecols=range(6),
                         dtype={"Five-Digit ZIP Code": str})
    zips = zips.rename(columns={"Five-Digit ZIP Code": "fips", "Year": "year", "HPI": "hpi"})
    metrics = part1.compute_metrics(zips[["fips", "year", "hpi"]], latest)  # 'fips' holds ZIP codes here
    metrics.index.name = "zcta"
    return metrics


# --- estimates --------------------------------------------------------------------------------


def weighted_estimates(pieces: pd.DataFrame, values: pd.DataFrame, key: str, target: str,
                       target_units: pd.Series, min_coverage: float = MIN_COVERAGE) -> pd.DataFrame:
    """Housing-unit-weighted mean of `values` (indexed by `key`) for each `target` area.

    pieces has one row per (key, target) overlap with its `units`. For each metric the result has the
    estimate (null below min_coverage) and cov_<metric>, the share of the target's homes behind it.
    """
    out = {}
    for col in METRICS:
        p = pieces.join(values[col], on=key).dropna(subset=[col, "units"])
        p = p[p.units > 0]
        covered = p.groupby(target).units.sum()
        estimate = (p[col] * p.units).groupby(p[target]).sum() / covered
        coverage = (covered / target_units.reindex(covered.index)).clip(upper=1)
        out[col] = estimate.where(coverage >= min_coverage)
        out[col.replace("hpi_", "cov_")] = coverage
    return pd.DataFrame(out)


def fill_layer(base: gpd.GeoDataFrame, estimates: list[tuple[str, pd.DataFrame]]) -> gpd.GeoDataFrame:
    """Fill blank values from each (source name, estimates) in order; FHFA values are kept."""
    out = base.copy()
    out["coverage"] = np.nan
    for col, src in METRICS.items():
        out[src] = np.where(out[col].notna(), "fhfa", None)
        cov_col = col.replace("hpi_", "cov_")
        for name, est in estimates:
            value = out.geoid.map(est[col]).astype(float)  # an empty estimate table maps to object dtype
            take = out[col].isna() & value.notna()
            out.loc[take, col] = value[take]
            out.loc[take, src] = name
            coverage = out.geoid.map(est[cov_col]).astype(float)
            out.loc[take, "coverage"] = np.fmin(out.loc[take, "coverage"], coverage[take])
    sources = out[list(METRICS.values())]
    out.loc[(sources == "zip").any(axis=1), "status"] = "estimated_zip"
    out.loc[(sources == "ct_crosswalk").any(axis=1), "status"] = "estimated_ct_crosswalk"
    return out[LAYER_COLUMNS]


def check_filled(layer: gpd.GeoDataFrame, base: gpd.GeoDataFrame) -> None:
    """FHFA values untouched, published counties still published, sources agree with values."""
    for col, src in METRICS.items():
        kept = base[col].notna()
        if not (layer.loc[kept, col] == base.loc[kept, col]).all():
            raise AssertionError(f"an FHFA value in {col} was changed")
        if not (layer[col].notna() == layer[src].notna()).all():
            raise AssertionError(f"{src} does not match which {col} values are present")
    if not (layer.loc[base.status == "published", "status"] == "published").all():
        raise AssertionError("a published county lost its status")
    estimated = layer[list(METRICS.values())].isin(["ct_crosswalk", "zip"]).any(axis=1)
    if not (layer.coverage.notna() == estimated).all():
        raise AssertionError("coverage must be set exactly for rows with an estimate")


def build_layer(release_dir: Path) -> tuple[gpd.GeoDataFrame, int]:
    """The Part 2 layer for one FHFA release, and the latest year it uses."""
    base, latest = part1.build_layer(release_dir)
    county_metrics = part1.compute_metrics(part1.read_fhfa_county(release_dir / "hpi_at_county.xlsx"), latest)
    units = read_housing_units()

    xwalk = read_ct_crosswalk(units["060"])
    ct = weighted_estimates(xwalk, county_metrics, "old_county", "new_county",
                            xwalk.groupby("new_county").units.sum())

    pieces = read_zcta_pieces(units["860"], units["050"])
    zp = weighted_estimates(pieces, read_zip_metrics(release_dir, latest), "zcta", "county", units["050"])

    layer = fill_layer(base, [("ct_crosswalk", ct), ("zip", zp)])
    check_filled(layer, base)
    report = pd.DataFrame({"Part 1": base.status.value_counts(), "Part 2": layer.status.value_counts()})
    print(report.fillna(0).astype(int).to_string())
    return layer, latest


def main(release_dir: Path) -> None:
    layer, _ = build_layer(release_dir)
    part1.write_outputs(layer)


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR / "fhfa")
