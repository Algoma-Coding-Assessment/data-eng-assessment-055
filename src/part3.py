"""Part 3: history.

    python -m src.part3 [release_dir]

Builds the Part 2 layer for one FHFA release and loads it, with FHFA's county values as
published, into PostGIS. Releases are keyed by FHFA's 'Last updated' date.

Tables and functions come from sql/schema.sql, the hpi_revisions and status_changes views from
sql/revisions.sql. Everything runs in one transaction, and each table is synced rather than
appended to: new rows are copied into a staging table, rows of this release that disappeared are
deleted, and only rows that differ are inserted or updated. Loading the same release twice
therefore touches zero rows.
"""

import io
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import psycopg2
import shapely

from src import part1, part2

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
SQL_DIR = REPO_ROOT / "sql"
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://takehome:takehome@localhost:5432/takehome")

LAYER_VALUE_COLUMNS = ["geoid", "hpi_yoy_pct", "hpi_cagr_5y_pct", "status", "yoy_source", "cagr_source", "coverage"]


def sync_table(cur, table: str, df: pd.DataFrame, keys: list[str],
               scope_sql: str = "TRUE", scope_params: tuple = ()) -> dict:
    """Make the rows of `table` within `scope_sql` equal to `df`, touching only rows that differ."""
    cols = list(df.columns)
    values = [c for c in cols if c not in keys]
    stage = f"stage_{table}"
    cur.execute(f"CREATE TEMP TABLE {stage} (LIKE {table}) ON COMMIT DROP")
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)  # floats are written in full, so they round-trip exactly
    buf.seek(0)
    cur.copy_expert(f"COPY {stage} ({', '.join(cols)}) FROM STDIN WITH (FORMAT csv)", buf)

    key_match = " AND ".join(f"s.{k} = t.{k}" for k in keys)
    cur.execute(f"""DELETE FROM {table} t WHERE {scope_sql}
                    AND NOT EXISTS (SELECT 1 FROM {stage} s WHERE {key_match})""", scope_params)
    deleted = cur.rowcount

    old = ", ".join(f"t.{c}" for c in values)
    new = ", ".join(f"EXCLUDED.{c}" for c in values)
    cur.execute(f"""
        INSERT INTO {table} AS t ({', '.join(cols)})
        SELECT {', '.join(cols)} FROM {stage}
        ON CONFLICT ({', '.join(keys)}) DO UPDATE
            SET {', '.join(f'{c} = EXCLUDED.{c}' for c in values)}
            WHERE ({old}) IS DISTINCT FROM ({new})
        RETURNING (xmax = 0) AS inserted""")
    inserted = [row[0] for row in cur.fetchall()]
    return {"table": table, "inserted": sum(inserted), "updated": len(inserted) - sum(inserted), "deleted": deleted}


def to_multipolygon_ewkb(geoms) -> list[str]:
    """Hex EWKB with SRID 4326, every geometry promoted to MultiPolygon (the column type)."""
    geoms = [shapely.MultiPolygon([g]) if g.geom_type == "Polygon" else g for g in geoms]
    return list(shapely.to_wkb(shapely.set_srid(geoms, 4326), hex=True, include_srid=True))


def release_rows(release_dir: Path) -> tuple[date, dict[str, pd.DataFrame]]:
    """The rows each table should hold for this release."""
    county_xlsx = release_dir / "hpi_at_county.xlsx"
    release_date = part1.read_release_date(county_xlsx)
    hpi = part1.read_fhfa_county(county_xlsx)
    layer, latest = part2.build_layer(release_dir)
    return release_date, {
        "releases": pd.DataFrame({"release_date": [release_date], "latest_year": [latest]}),
        "county_geom": pd.DataFrame({"geoid": layer.geoid, "name": layer.name, "state": layer.state,
                                     "geom": to_multipolygon_ewkb(layer.geometry.values)}),
        "fhfa_county_hpi": hpi.assign(release_date=release_date)[["release_date", "fips", "year", "hpi"]],
        "layer_values": layer[LAYER_VALUE_COLUMNS].assign(release_date=release_date)[
            ["release_date"] + LAYER_VALUE_COLUMNS],
    }


def load_release(conn, release_dir: Path) -> pd.DataFrame:
    """Create the schema if needed and sync this release, all in one transaction."""
    release_date, rows = release_rows(release_dir)
    scope = ("release_date = %s", (release_date,))
    with conn, conn.cursor() as cur:
        cur.execute((SQL_DIR / "schema.sql").read_text())
        report = [
            sync_table(cur, "releases", rows["releases"], ["release_date"], *scope),
            sync_table(cur, "county_geom", rows["county_geom"], ["geoid"]),
            sync_table(cur, "fhfa_county_hpi", rows["fhfa_county_hpi"], ["release_date", "fips", "year"], *scope),
            sync_table(cur, "layer_values", rows["layer_values"], ["release_date", "geoid"], *scope),
        ]
        cur.execute((SQL_DIR / "revisions.sql").read_text())
    return pd.DataFrame(report).set_index("table").assign(release=str(release_date))


def main(release_dir: Path) -> None:
    conn = psycopg2.connect(DATABASE_URL)
    try:
        report = load_release(conn, release_dir)
    finally:
        conn.close()
    print(report.to_string())


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else DATA_DIR / "fhfa")
