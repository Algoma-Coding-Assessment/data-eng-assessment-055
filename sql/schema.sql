-- Part 3: release history. Safe to run repeatedly (IF NOT EXISTS / OR REPLACE).
--
-- releases          one row per FHFA release            PK release_date
-- fhfa_county_hpi   FHFA county values as published      PK (release_date, fips, year)
-- county_geom       county shapes (2024 boundaries)      PK geoid
-- layer_values      the Part 2 layer per release         PK (release_date, geoid)
--
-- A release is identified by FHFA's 'Last updated' date, so "as of d" means
-- "what FHFA had published by d", independent of when it was loaded.
-- No load timestamps: they would change on every run.

CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS releases (
    release_date date PRIMARY KEY,          -- FHFA 'Last updated' date
    latest_year  integer NOT NULL           -- L used for the layer metrics
);

-- every row of hpi_at_county.xlsx, blanks included (hpi null) and codes as FHFA wrote them
CREATE TABLE IF NOT EXISTS fhfa_county_hpi (
    release_date date    NOT NULL REFERENCES releases ON DELETE CASCADE,
    fips         text    NOT NULL,
    year         integer NOT NULL,
    hpi          double precision,
    PRIMARY KEY (release_date, fips, year)
);

-- stored once: every release is drawn on the same 2024 boundaries
CREATE TABLE IF NOT EXISTS county_geom (
    geoid text PRIMARY KEY,
    name  text NOT NULL,
    state text NOT NULL,
    geom  geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS county_geom_gix ON county_geom USING gist (geom);

CREATE TABLE IF NOT EXISTS layer_values (
    release_date    date NOT NULL REFERENCES releases ON DELETE CASCADE,
    geoid           text NOT NULL REFERENCES county_geom,
    hpi_yoy_pct     double precision,
    hpi_cagr_5y_pct double precision,
    status          text NOT NULL,
    yoy_source      text,
    cagr_source     text,
    coverage        double precision,
    PRIMARY KEY (release_date, geoid)
);

-- the newest release published on or before d (null before the first release)
CREATE OR REPLACE FUNCTION release_as_of(d date) RETURNS date
LANGUAGE sql STABLE AS $$
    SELECT max(release_date) FROM releases WHERE release_date <= d
$$;

CREATE OR REPLACE FUNCTION hpi_as_of(d date)
RETURNS TABLE (fips text, year integer, hpi double precision)
LANGUAGE sql STABLE AS $$
    SELECT h.fips, h.year, h.hpi
    FROM fhfa_county_hpi h
    WHERE h.release_date = release_as_of(d)
$$;

CREATE OR REPLACE FUNCTION layer_as_of(d date)
RETURNS TABLE (geoid text, name text, state text, status text,
               hpi_yoy_pct double precision, hpi_cagr_5y_pct double precision,
               yoy_source text, cagr_source text, coverage double precision,
               release_date date, latest_year integer, geom geometry)
LANGUAGE sql STABLE AS $$
    SELECT v.geoid, g.name, g.state, v.status,
           v.hpi_yoy_pct, v.hpi_cagr_5y_pct, v.yoy_source, v.cagr_source, v.coverage,
           v.release_date, r.latest_year, g.geom
    FROM layer_values v
    JOIN county_geom g USING (geoid)
    JOIN releases r USING (release_date)
    WHERE v.release_date = release_as_of(d)
$$;
