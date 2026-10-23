# Data sources

Every file is byte-for-byte what the publisher served. Nothing was filtered or reformatted.

| File | Source | Retrieved |
| --- | --- | --- |
| `fhfa/hpi_at_county.xlsx` | FHFA annual HPI for counties (developmental). https://www.fhfa.gov/hpi/download/annual/hpi_at_county.xlsx, via the Internet Archive capture of 2025-07-27 | 2026-10-20 |
| `fhfa/hpi_at_zip5.xlsx` | FHFA annual HPI for five-digit ZIP codes (developmental). https://www.fhfa.gov/hpi/download/annual/hpi_at_zip5.xlsx, via the Internet Archive capture of 2025-07-27 | 2026-10-20 |
| `fhfa/next_release/hpi_at_county.xlsx` | Same URL, served live | 2026-10-20 |
| `fhfa/next_release/hpi_at_zip5.xlsx` | Same URL, served live | 2026-10-20 |
| `census/cb_2024_us_county_500k.zip` | Census 2024 cartographic boundary file, counties, 1:500,000. https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip | 2026-10-20 |
| `census/tab20_zcta520_county20_natl.txt` | Census 2020 relationship file, ZCTA520 to County20. https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/tab20_zcta520_county20_natl.txt | 2026-10-20 |
| `census/acsdt5y2024-b25001.dat` | ACS 2020–2024 5-year table-based summary file, table B25001. https://www2.census.gov/programs-surveys/acs/summary_file/2024/table-based-SF/data/5YRData/acsdt5y2024-b25001.dat | 2026-10-20 |
| `census/ct_cou_to_cousub_crosswalk.xlsx` | Census Connecticut county and county subdivision crosswalk. https://www2.census.gov/geo/docs/reference/ct_change/ct_cou_to_cousub_crosswalk.xlsx | 2026-10-20 |

Documentation:

- FHFA HPI datasets and technical notes: https://www.fhfa.gov/data/hpi/datasets
- Cartographic boundary files: https://www.census.gov/geographies/mapping-files/time-series/geo/cartographic-boundary.html
- 2020 relationship files: https://www.census.gov/geographies/reference-files/time-series/geo/relationship-files.2020.html
- ACS summary file: https://www.census.gov/programs-surveys/acs/data/summary-file.html
