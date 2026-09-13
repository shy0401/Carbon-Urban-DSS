# Phase 1 data audit before enrichment

Verified against the live local PostGIS database on 2026-09-12. Counts are snapshots, not UI fixtures.

|Dataset|Current provider|Official candidate|Authentication|Rows|Coverage|Quality|Replacement needed|
|---|---|---|---|---:|---|---|---|
|Energy|MOLIT building HUB attempted|MOLIT building HUB|Approved key; actual code30 rejection|0|None|Missing|Fix key; explore legitimate public Kapt fallback|
|Buildings|OSM|Building HUB register / GIS building integration|Separate API approval / VWorld key / manual SHP|2171|Apartment footprints in Jeonju study extent|Fallback, some levels unknown|Retain until verified replacement|
|Boundary|OSM relation7619919|NGII administrative boundary|Manual file or official API|1|Jeonju city|Fallback administrative polygon|Yes, optional|
|Grid|Local EPSG5179 aligned generation|NGII StatisticsGrid500M|Manual download|916|Un-clipped 500m cells intersecting city|Exact dimensions; unofficial IDs|Map official IDs explicitly on import|
|Regions|MOIS code.go.kr|Current provider|None|86|Active Jeonju hierarchy/dong codes|Official; SHA256 version|No|
|Weather|Open-Meteo ERA5-Land|KMA ASOS Jeonju station146|Separate service approval|12 monthly /365 daily|2025 full year|Fallback reanalysis, ~0.1°|Retain until KMA verified|
|Population|None|NGII100m/500m population|Manual download/SGIS keys|0|None|Missing|Required to enable per-person observed metrics|
|Zoning|None|MOLIT VWorld zoning WFS/SHP|VWorld key/manual download|0|None|Missing|Legal limits remain unconfirmed|
|Factors|GIR PDF acquired, not ingested yet|GIR/KEA|None|0 DB|2024-approved electricity factors|Need applicability/units recorded|Ingest verified electricity; gas basis must be verified|
|Apartment metadata|Kapt district summaries acquired|Kapt / Jeonju apartment register|Public website endpoints|364 raw complexes,0 DB|Jeonju 2025-12|Official public listings|Fetch limited detail and exact parcel matching|
