# Carbon Urban DSS continuation ledger

Updated 2026-09-14 Asia/Seoul. Latest user request: implement missing planned features and refine UI. Sequential completion recorded in IMPLEMENTATION_UPDATE.md. Do not repeat broad development or spawn agents.

- Latest verification: backend 63, frontend 17, original Chromium 9 and refined Chromium 9 passed; page errors zero. Real local Qwen2.5 1.5B response passed evidence validation.
- Implemented shared year/grid scope; matched-area safeguards; partial-year handling; model eligibility/history; dashboard/map/mobile refinement; scenario invalidation/validation; persisted Korean reports, same-scope comparison, Markdown, print; constrained local AI evidence selection with fallback.
- Operating volumes and raw data preserved. Separate clean-volume validation was completed previously, not repeated for this update.
- Actual data includes 916 grids, 2,171 OSM buildings, 86 codes, 12 weather months, Kapt and municipal data. Energy zero. No real predictive performance or carbon-reduction result exists.
- Energy key remains invalid placeholder (HTTP403/code30). Never print credentials or retry unchanged key. User must replace locally and verify individual service approval.
- Still needed: official energy/buildings/zoning/population; enterprise 100m carbon adapter; gas basis/GWP; expanded trained features; physical PV/green models; production authentication/migrations/performance.
- Heartbeat remains paused to conserve usage. Do not reactivate without a new scheduling request.

2026-09-14 deployment: user selected free PC-hosted prototype. Authenticated Cloudflare Quick Tunnel deployed; credentials only .secrets/prototype-access.md, current URL only data/deployment/public-url.txt. Public auth checks 8, functional checks 10, 2MB upload passed, worker weather SUCCESS. compose.demo.yaml preserves volumes, scripts/prototype.ps1 manages Start/Stop/Status. All services run on this PC; no always-on cloud server provisioned. Do not upload credentials, URL logs, uploads or DB backups. Energy-key blocker unchanged.

2026-09-14 map/data fix: OSM 403 root cause was gateway Referrer-Policy same-origin stripping external Referer. Replaced with strict-origin-when-cross-origin, added visible attribution, optional basemap and failure fallback. Public real tiles 200, injected 403 fallback/selection/mobile and auth checks passed. User explicitly requested prototype username and password; current values only local .secrets. Kapt details expanded 8 to 364 (361 positive floor areas), cache-only refresh preserves all details. Weather 2025 12 months, other-year months preserved. DATA_SETUP_GUIDE.md contains source-by-source enrollment, download and required fields; energy key unchanged invalid, VWorld/SGIS credentials absent. Do not infer historical building state from current Kapt detail.
