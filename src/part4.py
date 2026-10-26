"""Part 4: answers.

    python -m src.part4

Reads the newest layer loaded by Part 3 (layer_as_of(current_date)) and answers:

Which counties appreciated the most?  -> output/rankings.csv
    Counties with FHFA's own 5-year CAGR, highest first (ties by geoid). One-year changes are too
    noisy in small counties to rank on, and ZIP estimates are excluded because their error moves a
    county many places. housing_units is shown so small counties can be judged, not dropped.

Where are the clusters of high and low appreciation?  -> output/clusters.csv
    Local Moran's I on the same values with queen contiguity (counties whose boundaries touch, from
    PostGIS) and conditional permutations. Each county gets a label:
        high_high / low_low     hot spot / cold spot (p < ALPHA)
        high_low / low_high     outlier: unlike its neighbours (p < ALPHA)
        not_significant
        no_data                 no FHFA 5-year CAGR
        no_neighbors            no touching county with a value (islands, counties across water)
    Touching counties with the same hot/cold label are joined into regions (HH-1 is the largest hot
    spot, LL-1 the largest cold spot).
"""

import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import psycopg2

from src import part2

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = REPO_ROOT / "output"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://takehome:takehome@localhost:5432/takehome")

METRIC = "hpi_cagr_5y_pct"
PERMUTATIONS = 999
ALPHA = 0.05
SEED = 20261031  # fixed, so the permutation p-values and clusters.csv are reproducible

RANK_COLUMNS = ["rank", "geoid", "name", "state", METRIC, "hpi_yoy_pct", "status", "housing_units"]
CLUSTER_COLUMNS = ["geoid", "name", "state", "cluster", "region", METRIC, "local_i", "p_value"]
REGION_PREFIX = {"high_high": "HH", "low_low": "LL"}


# --- inputs -----------------------------------------------------------------------------------


def read_layer(conn) -> pd.DataFrame:
    """The newest loaded release's layer, without geometry, plus ACS housing units."""
    with warnings.catch_warnings():  # pandas prefers SQLAlchemy; a psycopg2 connection works fine
        warnings.simplefilter("ignore", UserWarning)
        layer = pd.read_sql("""SELECT geoid, name, state, status, hpi_yoy_pct, hpi_cagr_5y_pct,
                                      yoy_source, cagr_source, release_date, latest_year
                               FROM layer_as_of(current_date)""", conn)
    if layer.empty:
        raise RuntimeError("no release loaded; run python -m src.part3 first")
    layer["housing_units"] = layer.geoid.map(part2.read_housing_units()["050"]).astype("Int64")
    return layer


def read_neighbour_edges(conn) -> pd.DataFrame:
    """Queen contiguity: every pair of counties whose boundaries touch, in both directions."""
    with conn.cursor() as cur:
        cur.execute("""SELECT a.geoid, b.geoid FROM county_geom a
                       JOIN county_geom b ON a.geoid < b.geoid AND ST_Intersects(a.geom, b.geom)""")
        pairs = pd.DataFrame(cur.fetchall(), columns=["a", "b"])
    return pd.concat([pairs, pairs.rename(columns={"a": "b", "b": "a"})], ignore_index=True)


# --- rankings ---------------------------------------------------------------------------------


def rank_counties(layer: pd.DataFrame) -> pd.DataFrame:
    ranked = (layer[layer.cagr_source == "fhfa"]
              .sort_values([METRIC, "geoid"], ascending=[False, True])
              .reset_index(drop=True))
    ranked.insert(0, "rank", np.arange(1, len(ranked) + 1))
    return ranked[RANK_COLUMNS]


# --- clusters ---------------------------------------------------------------------------------


def local_moran(values: pd.Series, edges: pd.DataFrame, permutations: int = PERMUTATIONS,
                seed: int = SEED) -> pd.DataFrame:
    """Local Moran's I per county. values: indexed by geoid, no NaN. edges: columns a, b.

    z = (x - mean) / sd over the counties analysed; lag = mean z of neighbours with a value;
    local_i = z * lag. The pseudo p-value keeps z_i and draws its k neighbours at random from the
    other counties `permutations` times (with replacement: negligible for k ~ 6 of ~2,700).
    """
    ids = values.index.to_numpy()
    pos = pd.Series(np.arange(len(ids)), index=ids)
    e = edges[edges.a.isin(pos.index) & edges.b.isin(pos.index)]
    neighbours = e.groupby("a").b.apply(lambda s: pos[s].to_numpy()).reindex(ids)

    x = values.to_numpy(float)
    z = (x - x.mean()) / x.std()
    rng = np.random.default_rng(seed)
    n = len(z)
    lag = np.full(n, np.nan)
    local_i = np.full(n, np.nan)
    p = np.full(n, np.nan)
    for i, nb in enumerate(neighbours.to_numpy()):
        if not isinstance(nb, np.ndarray) or len(nb) == 0:
            continue
        lag[i] = z[nb].mean()
        local_i[i] = z[i] * lag[i]
        draws = rng.integers(0, n - 1, size=(permutations, len(nb)))
        draws[draws >= i] += 1  # never draw county i itself
        sim = z[i] * z[draws].mean(axis=1)
        extreme = (sim >= local_i[i]).sum() if local_i[i] >= np.median(sim) else (sim <= local_i[i]).sum()
        p[i] = (extreme + 1) / (permutations + 1)
    return pd.DataFrame({"z": z, "lag": lag, "local_i": local_i, "p_value": p}, index=ids)


def cluster_label(z: float, lag: float, p_value: float, alpha: float = ALPHA) -> str:
    if np.isnan(lag):
        return "no_neighbors"
    if p_value >= alpha:
        return "not_significant"
    return ("high" if z > 0 else "low") + "_" + ("high" if lag > 0 else "low")


def assign_regions(clusters: pd.DataFrame, edges: pd.DataFrame) -> pd.Series:
    """Join touching counties with the same hot/cold label into regions, numbered by size."""
    region = pd.Series(pd.NA, index=clusters.geoid, dtype="string")
    for label, prefix in REGION_PREFIX.items():
        members = set(clusters.geoid[clusters.cluster == label])
        e = edges[edges.a.isin(members) & edges.b.isin(members)]
        adjacent = e.groupby("a").b.apply(list).to_dict()
        groups, seen = [], set()
        for start in sorted(members):
            if start in seen:
                continue
            seen.add(start)
            stack, group = [start], []
            while stack:
                g = stack.pop()
                group.append(g)
                for nb in adjacent.get(g, []):
                    if nb not in seen:
                        seen.add(nb)
                        stack.append(nb)
            groups.append(sorted(group))
        groups.sort(key=lambda g: (-len(g), g[0]))  # largest first; ties by smallest geoid
        for k, group in enumerate(groups, start=1):
            region[group] = f"{prefix}-{k}"
    return region


def find_clusters(layer: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    values = layer.loc[layer.cagr_source == "fhfa"].set_index("geoid")[METRIC]
    lisa = local_moran(values, edges)
    lisa["cluster"] = [cluster_label(z, lag, p) for z, lag, p in zip(lisa.z, lisa.lag, lisa.p_value)]

    clusters = layer[["geoid", "name", "state", METRIC]].join(lisa[["local_i", "p_value", "cluster"]], on="geoid")
    clusters["cluster"] = clusters.cluster.fillna("no_data")
    clusters["region"] = clusters.geoid.map(assign_regions(clusters, edges))
    return clusters.sort_values("geoid")[CLUSTER_COLUMNS]


def summarise_regions(clusters: pd.DataFrame, top: int = 5) -> pd.DataFrame:
    """The largest hot and cold regions, for the console and NOTES.md."""
    g = clusters.dropna(subset=["region"]).groupby("region")
    summary = pd.DataFrame({
        "counties": g.size(),
        "states": g.state.agg(lambda s: ", ".join(s.value_counts().index[:4])),
        f"mean_{METRIC}": g[METRIC].mean().round(2),
    })
    summary["n"] = summary.index.str.split("-").str[1].astype(int)
    summary = summary[summary.n <= top].sort_values(["n"]).drop(columns="n")
    return summary.loc[sorted(summary.index, key=lambda r: (r[:2] != "HH", int(r.split("-")[1])))]


def main() -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        layer = read_layer(conn)
        edges = read_neighbour_edges(conn)
    finally:
        conn.close()
    release, latest = layer.release_date.iloc[0], int(layer.latest_year.iloc[0])

    rankings = rank_counties(layer)
    clusters = find_clusters(layer, edges)

    OUTPUT_DIR.mkdir(exist_ok=True)
    rankings.round({METRIC: 4, "hpi_yoy_pct": 4}).to_csv(OUTPUT_DIR / "rankings.csv", index=False)
    clusters.round({METRIC: 4, "local_i": 4, "p_value": 4}).to_csv(OUTPUT_DIR / "clusters.csv", index=False)

    print(f"release {release} (latest year {latest}): {len(rankings)} counties ranked by {METRIC}")
    print(rankings.head(10).round(2).to_string(index=False))
    print("\n" + clusters.cluster.value_counts().to_string())
    print("\n" + summarise_regions(clusters).to_string())


if __name__ == "__main__":
    main()
