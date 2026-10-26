"""Part 1: a layer analysts can trust.

    python -m src.part1 [release_dir]

You may add modules, helpers and dependencies. Keep this command working as described in the README.

Builds one feature per county (50 states + DC, from the 2024 Census boundaries) with FHFA's
appreciation over the latest year and over the last five years:

    hpi_yoy_pct     = (HPI[L] / HPI[L-1] - 1) * 100
    hpi_cagr_5y_pct = ((HPI[L] / HPI[L-5]) ** (1/5) - 1) * 100

L is one year for the whole release (the newest year with near-full coverage), never a county's
own last year with data. A missing input year gives a null value, never a substitute year.

status says which input is missing:
    published        HPI[L], HPI[L-1] and HPI[L-5] present: both values
    partial_no_yoy   HPI[L-1] missing: no hpi_yoy_pct
    partial_no_cagr  HPI[L-5] missing: no hpi_cagr_5y_pct
    no_prior_years   HPI[L-1] and HPI[L-5] missing: no values
    no_latest        HPI[L] missing: no values
    not_in_fhfa      county not in the FHFA county file
"""

import io
import re
import sys
from datetime import date, datetime
from pathlib import Path

import geopandas as gpd
import openpyxl
import pandas as pd
import shapely

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "output"

BOUNDARIES = DATA_DIR / "census" / "cb_2024_us_county_500k.zip"
TERRITORIES = {"60", "66", "69", "72", "78"}
WGS84 = 4326

# a year counts as the latest only if it covers at least this share of the previous year's counties
MIN_COVERAGE = 0.9

# GeoJSON: coverage simplification keeps shared borders shared (no gaps or overlaps).
# 0.005 deg is the most detail that stays a valid coverage after rounding and fits in 8 MB.
SIMPLIFY_TOLERANCE = 0.005
COORD_GRID = 1e-5  # ~1 m; rounding is applied before validation so we check what we write
GAP_WIDTH = 1e-3  # ~100 m; narrower openings between neighbours count as gaps
GEOJSON_MAX_BYTES = 8 * 1024 * 1024

LAYER_COLUMNS = ["geoid", "name", "state", "hpi_yoy_pct", "hpi_cagr_5y_pct", "status", "geometry"]


# --- FHFA -------------------------------------------------------------------------------------


def read_release_date(path: Path) -> date:
    """The 'Last updated: March 31, 2026.' line in the sheet preamble."""
    ws = openpyxl.load_workbook(path, read_only=True).worksheets[0]
    for (cell,) in ws.iter_rows(max_row=6, max_col=1, values_only=True):
        m = re.search(r"Last updated:\s*(.+?)\.?\s*$", str(cell or ""))
        if m:
            return datetime.strptime(m.group(1), "%B %d, %Y").date()
    raise ValueError(f"no 'Last updated' line in {path}")


def read_fhfa_county(path: Path) -> pd.DataFrame:
    """One row per county-year: fips, state, county, year, hpi (NaN where FHFA left it blank)."""
    # pandas skips the blank second row, so the header is reached with skiprows=5
    df = pd.read_excel(path, skiprows=5, dtype={"FIPS code": str})
    df = df.rename(columns={"State": "state", "County": "county", "FIPS code": "fips", "Year": "year", "HPI": "hpi"})
    df = df[["fips", "state", "county", "year", "hpi"]]
    if not df.fips.str.fullmatch(r"\d{5}").all():
        raise ValueError(f"unexpected FIPS codes in {path}")
    if df.duplicated(["fips", "year"]).any():
        raise ValueError(f"duplicate county-years in {path}")
    return df


def latest_year(hpi: pd.DataFrame, min_coverage: float = MIN_COVERAGE) -> int:
    """Newest year whose county coverage is at least min_coverage of the year before."""
    counts = hpi.dropna(subset=["hpi"]).groupby("year").fips.nunique()
    for year in sorted(counts.index, reverse=True):
        prev = counts.get(year - 1)
        if prev is None or counts[year] >= min_coverage * prev:
            return int(year)
        print(f"skipping {year}: {counts[year]} counties with HPI vs {prev} in {year - 1}")
    raise ValueError("no usable latest year")


def compute_metrics(hpi: pd.DataFrame, latest: int) -> pd.DataFrame:
    """Per FHFA county: hpi_yoy_pct, hpi_cagr_5y_pct and status, from exact years only."""
    wide = hpi.pivot(index="fips", columns="year", values="hpi").reindex(columns=[latest - 5, latest - 1, latest])
    hpi_l, hpi_l1, hpi_l5 = wide[latest], wide[latest - 1], wide[latest - 5]

    out = pd.DataFrame(index=wide.index)
    out["hpi_yoy_pct"] = (hpi_l / hpi_l1 - 1) * 100
    out["hpi_cagr_5y_pct"] = ((hpi_l / hpi_l5) ** (1 / 5) - 1) * 100

    has_l, has_l1, has_l5 = hpi_l.notna(), hpi_l1.notna(), hpi_l5.notna()
    status = pd.Series("no_latest", index=wide.index)
    status[has_l & ~has_l1 & ~has_l5] = "no_prior_years"
    status[has_l & ~has_l1 & has_l5] = "partial_no_yoy"
    status[has_l & has_l1 & ~has_l5] = "partial_no_cagr"
    status[has_l & has_l1 & has_l5] = "published"
    out["status"] = status
    return out


# --- boundaries and layer ---------------------------------------------------------------------


def read_boundaries() -> gpd.GeoDataFrame:
    """Counties in the 50 states + DC, in WGS84, with the layer's id and name columns."""
    bnd = gpd.read_file(BOUNDARIES, columns=["GEOID", "STATEFP", "NAMELSAD", "STUSPS"])
    bnd = bnd[~bnd.STATEFP.isin(TERRITORIES)].to_crs(WGS84)
    bnd = bnd.rename(columns={"GEOID": "geoid", "NAMELSAD": "name", "STUSPS": "state"})
    return bnd[["geoid", "name", "state", "geometry"]].sort_values("geoid").reset_index(drop=True)


def build_layer(release_dir: Path) -> tuple[gpd.GeoDataFrame, int]:
    """The full-resolution layer for one FHFA release, and the latest year it uses."""
    county_xlsx = release_dir / "hpi_at_county.xlsx"
    hpi = read_fhfa_county(county_xlsx)
    latest = latest_year(hpi)
    metrics = compute_metrics(hpi, latest)

    bnd = read_boundaries()
    unmatched = sorted(set(metrics.index) - set(bnd.geoid))
    if unmatched:
        print(f"FHFA counties with no 2024 boundary (not on the map): {unmatched}")

    layer = bnd.join(metrics, on="geoid")
    layer["status"] = layer.status.fillna("not_in_fhfa")
    layer = layer[LAYER_COLUMNS]
    check_layer(layer, bnd)
    print(f"{release_dir} (released {read_release_date(county_xlsx)}): "
          f"latest year {latest}, {len(layer)} counties")
    return layer, latest


def check_layer(layer: gpd.GeoDataFrame, bnd: gpd.GeoDataFrame) -> None:
    """One feature per boundary county, and every status agrees with which values are present."""
    if not (layer.geoid.is_unique and set(layer.geoid) == set(bnd.geoid)):
        raise AssertionError("layer must have exactly one feature per boundary county")
    present = {  # status: (hpi_yoy_pct present, hpi_cagr_5y_pct present)
        "published": (True, True),
        "partial_no_yoy": (False, True),
        "partial_no_cagr": (True, False),
        "no_prior_years": (False, False),
        "no_latest": (False, False),
        "not_in_fhfa": (False, False),
    }
    if not layer.status.isin(present.keys()).all():
        raise AssertionError(f"unknown status values: {set(layer.status) - present.keys()}")
    for status, (yoy, cagr) in present.items():
        rows = layer[layer.status == status]
        if not ((rows.hpi_yoy_pct.notna() == yoy).all() and (rows.hpi_cagr_5y_pct.notna() == cagr).all()):
            raise AssertionError(f"status {status!r} does not match the values present")


# --- web GeoJSON ------------------------------------------------------------------------------


def simplify_coverage(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    geoms = shapely.coverage_simplify(gdf.geometry.values, tolerance=SIMPLIFY_TOLERANCE, simplify_boundary=True)
    geoms = shapely.set_precision(geoms, grid_size=COORD_GRID)
    return gdf.set_geometry(gpd.GeoSeries(geoms, index=gdf.index, crs=gdf.crs))


def narrow_gaps(gdf: gpd.GeoDataFrame) -> set[str]:
    """geoids next to an opening narrower than GAP_WIDTH between neighbouring counties."""
    edges = shapely.coverage_invalid_edges(gdf.geometry.values, gap_width=GAP_WIDTH)
    return set(gdf.geoid[~shapely.is_empty(edges)])


def check_web_layer(web: gpd.GeoDataFrame, full: gpd.GeoDataFrame) -> None:
    """Valid, non-empty, no overlaps, and no gaps beyond those already in the Census file
    (narrow water channels between coastal counties, since the file is clipped to the shoreline)."""
    g = web.geometry.values
    if not shapely.is_valid(g).all() or shapely.is_empty(g).any():
        raise AssertionError("web layer has invalid or empty geometries")
    if not shapely.coverage_is_valid(g):
        raise AssertionError("web layer has overlaps or mismatched shared edges")
    new_gaps = narrow_gaps(web) - narrow_gaps(full)
    if new_gaps:
        raise AssertionError(f"simplification opened gaps at {sorted(new_gaps)}")


def write_outputs(layer: gpd.GeoDataFrame) -> None:
    """counties.parquet at full resolution; counties.geojson simplified for the web (RFC 7946)."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    layer.to_parquet(OUTPUT_DIR / "counties.parquet", index=False)

    web = simplify_coverage(layer)
    buf = io.BytesIO()
    web.to_file(buf, driver="GeoJSON", RFC7946="YES", COORDINATE_PRECISION=5)
    raw = buf.getvalue()
    if len(raw) > GEOJSON_MAX_BYTES:
        raise AssertionError(f"GeoJSON is {len(raw) / 1e6:.1f} MB, over the 8 MB limit")
    (OUTPUT_DIR / "counties.geojson").write_bytes(raw)

    # validate the file as written, not the in-memory frame
    check_web_layer(gpd.read_file(OUTPUT_DIR / "counties.geojson"), layer)
    print(f"wrote counties.parquet and counties.geojson ({len(raw) / 1e6:.2f} MB)")


def main(release_dir: Path) -> None:
    layer, _ = build_layer(release_dir)
    write_outputs(layer)
    print(layer.status.value_counts().to_string())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR / "fhfa")
