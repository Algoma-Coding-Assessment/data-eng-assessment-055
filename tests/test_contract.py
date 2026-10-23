"""Public format checks for the layer. Run `python -m src.part1` (and `src.part2`) first.

Passing these is necessary but not sufficient. Reviewers run additional checks.
"""

import json
from pathlib import Path

import geopandas as gpd
import pytest

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "output"
BOUNDARIES = ROOT / "data" / "census" / "cb_2024_us_county_500k.zip"
TERRITORIES = {"60", "66", "69", "72", "78"}
PROPERTIES = {"geoid", "name", "state", "hpi_yoy_pct", "hpi_cagr_5y_pct", "status"}


@pytest.fixture(scope="module")
def expected_geoids() -> set[str]:
    b = gpd.read_file(BOUNDARIES, columns=["GEOID", "STATEFP"], ignore_geometry=True)
    return set(b.loc[~b["STATEFP"].isin(TERRITORIES), "GEOID"])


@pytest.fixture(scope="module")
def parquet() -> gpd.GeoDataFrame:
    return gpd.read_parquet(OUTPUT / "counties.parquet")


@pytest.fixture(scope="module")
def geojson() -> gpd.GeoDataFrame:
    return gpd.read_file(OUTPUT / "counties.geojson")


def test_properties(parquet, geojson):
    for layer in (parquet, geojson):
        assert PROPERTIES <= set(layer.columns)


def test_one_feature_per_county(parquet, geojson, expected_geoids):
    for layer in (parquet, geojson):
        assert layer["geoid"].is_unique
        assert set(layer["geoid"]) == expected_geoids


def test_status_values(parquet):
    assert parquet["status"].notna().all()
    assert "published" in set(parquet["status"])


def test_geojson_is_web_ready(geojson):
    path = OUTPUT / "counties.geojson"
    assert path.stat().st_size <= 8 * 1024 * 1024
    raw = json.loads(path.read_text())
    assert raw.get("crs") is None, "RFC 7946 GeoJSON has no crs member; coordinates are WGS84 lon/lat"
    assert geojson.geometry.is_valid.all()
