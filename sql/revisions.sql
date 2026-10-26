-- Part 3: what changed between the two most recent releases. Safe to run repeatedly.
-- Both views are empty until two releases are loaded.

CREATE OR REPLACE VIEW latest_two_releases AS
SELECT max(release_date) FILTER (WHERE rn = 1) AS new_release,
       max(release_date) FILTER (WHERE rn = 2) AS old_release
FROM (SELECT release_date, row_number() OVER (ORDER BY release_date DESC) AS rn FROM releases) r;

-- Every (fips, year) whose published value differs between the two releases.
--   revision  revised: a value in both, changed
--             added:   blank or absent before, a value now (new year, new county code)
--             removed: a value before, blank or absent now (e.g. CT's pre-2022 county codes)
--   rebased   the series' first recorded year moved, so its whole level shifted and
--             pct_change reflects the new base rather than new information
CREATE OR REPLACE VIEW hpi_revisions AS
WITH r AS (SELECT * FROM latest_two_releases),
o AS (SELECT h.fips, h.year, h.hpi FROM fhfa_county_hpi h, r WHERE h.release_date = r.old_release),
n AS (SELECT h.fips, h.year, h.hpi FROM fhfa_county_hpi h, r WHERE h.release_date = r.new_release),
first_year AS (
    SELECT fips,
           min(year) FILTER (WHERE release_date = r.old_release AND hpi IS NOT NULL) AS old_first,
           min(year) FILTER (WHERE release_date = r.new_release AND hpi IS NOT NULL) AS new_first
    FROM fhfa_county_hpi, r GROUP BY fips
)
SELECT coalesce(o.fips, n.fips) AS fips,
       coalesce(o.year, n.year) AS year,
       o.hpi AS old_hpi,
       n.hpi AS new_hpi,
       CASE WHEN o.hpi IS NOT NULL AND n.hpi IS NOT NULL THEN 'revised'
            WHEN o.hpi IS NULL THEN 'added'
            ELSE 'removed' END AS revision,
       round(((n.hpi / nullif(o.hpi, 0) - 1) * 100)::numeric, 4) AS pct_change,
       coalesce(f.old_first IS DISTINCT FROM f.new_first AND f.old_first IS NOT NULL AND f.new_first IS NOT NULL,
                false) AS rebased,
       r.old_release, r.new_release
FROM o FULL JOIN n ON o.fips = n.fips AND o.year = n.year
CROSS JOIN r
LEFT JOIN first_year f ON f.fips = coalesce(o.fips, n.fips)
WHERE r.old_release IS NOT NULL
  AND o.hpi IS DISTINCT FROM n.hpi;

-- Every county whose layer status differs between the two releases.
CREATE OR REPLACE VIEW status_changes AS
WITH r AS (SELECT * FROM latest_two_releases),
o AS (SELECT v.* FROM layer_values v, r WHERE v.release_date = r.old_release),
n AS (SELECT v.* FROM layer_values v, r WHERE v.release_date = r.new_release)
SELECT coalesce(o.geoid, n.geoid) AS geoid,
       g.name, g.state,
       o.status AS old_status,
       n.status AS new_status,
       o.hpi_yoy_pct AS old_hpi_yoy_pct, n.hpi_yoy_pct AS new_hpi_yoy_pct,
       r.old_release, r.new_release
FROM o FULL JOIN n ON o.geoid = n.geoid
CROSS JOIN r
LEFT JOIN county_geom g ON g.geoid = coalesce(o.geoid, n.geoid)
WHERE r.old_release IS NOT NULL
  AND o.status IS DISTINCT FROM n.status;
