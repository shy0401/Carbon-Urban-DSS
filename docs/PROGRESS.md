# Carbon Urban DSS continuation ledger

Updated 2026-09-14 Asia/Seoul. Latest user request: implement missing planned features and refine UI. Sequential completion recorded in IMPLEMENTATION_UPDATE.md. Do not repeat broad development or spawn agents.

- Latest verification: backend 63, frontend 17, original Chromium 9 and refined Chromium 9 passed; page errors zero. Real local Qwen2.5 1.5B response passed evidence validation.
- Implemented shared year/grid scope; matched-area safeguards; partial-year handling; model eligibility/history; dashboard/map/mobile refinement; scenario invalidation/validation; persisted Korean reports, same-scope comparison, Markdown, print; constrained local AI evidence selection with fallback.
- Operating volumes and raw data preserved. Separate clean-volume validation was completed previously, not repeated for this update.
- Actual data includes 916 grids, 2,171 OSM buildings, 86 codes, 12 weather months, Kapt and municipal data. Energy zero. No real predictive performance or carbon-reduction result exists.
- Energy key remains invalid placeholder (HTTP403/code30). Never print credentials or retry unchanged key. User must replace locally and verify individual service approval.
- Still needed: official energy/buildings/zoning/population; enterprise 100m carbon adapter; gas basis/GWP; expanded trained features; physical PV/green models; production authentication/migrations/performance.
- Heartbeat remains paused to conserve usage. Do not reactivate without a new scheduling request.
