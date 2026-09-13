# Carbon Urban DSS implementation plan

**Goal:** Run a five-service local real-data prototype for Jeonju in Docker Compose.
**Architecture:** FastAPI/SQLAlchemy/PostGIS stores normalized observations and provenance. Celery/Redis performs cached, rate-limited collection. React/Vite/MapLibre/ECharts renders database state and transparent preliminary scenarios.
**Authority:** User's supplied project specification; implementation is explicitly authorized without additional design gates.

## Tasks
- [ ] Discover official energy operations and response fields with a one-row request, regional codes, spatial fallback, weather, factors. Cache evidence in data/raw and document in DATA_SOURCE_DISCOVERY.md.
- [ ] Implement backend models, collectors, API, exact EPSG:5179 grid, automatic sector ranking, and honest missing-data/scenario calculations. Write and run focused parser, grid, cache, weather, factors, FAR/BCR tests.
- [ ] Implement Korean dashboard, map, simulation and collected-data views with null-aware charts, provenance previews and job progress. Build and run frontend smoke tests.
- [ ] Bring up Compose, perform real collection, verify PostGIS and live endpoints/browser, record exact counts and limitations.

## Interfaces
All frontend API calls use /api prefix. GET /health; GET /dashboard; GET /map returns GeoJSON collections `grids`, `buildings`, `boundary`, selected_sector; GET /grids/{id}; GET /sources returns list; GET /sources/{id} returns source, raw_preview, normalized_preview, jobs, errors, coverage; POST /collections {datasets:[energy,weather],start_month:2025-01,end_month:2025-12}; GET /collections returns list; POST /scenarios with site_area,building_count,footprint_per_building,floors,households,population,efficiency_factor,pv_ratio returns calculations and monthly/annual current/scenario/difference.
Dashboard fields: selected_sector {id,name,grid_id,area_m2,reason}, electricity_kwh,gas_kwh,carbon_kg,current_far,quality,monthly [{use_ym,electricity_kwh,gas_kwh,carbon_kg}],weather [], sources [], coverage. Source fields: id,category,name,organization,source_url,status,source_type,collected_at,reference_period,geographic_coverage,raw_row_count,normalized_row_count,missing_count,quality,limitation.

## Decisions
No repository currently exists; work directly in requested empty project directory. Secrets remain backend-only. Missing observations are null, never zero. Official energy is parcel-level and excludes small residential properties; match parcel energy to spatial sectors only when coordinates are supported, and label centroid assignment. Weather reanalysis and OSM are visibly FALLBACK. Unsupported current FAR/intensity/carbon remain unavailable.
