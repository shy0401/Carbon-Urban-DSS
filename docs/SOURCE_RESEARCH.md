# Carbon Urban DSS — 2025 source research

This note records the public sources that can be reproduced without a private
account and the official API that becomes usable after a registered data.go.kr
key is supplied. It separates observed quantities, official factors, and
derived values so the 2025 baseline does not silently turn costs or modeled
values into observations.

## 1. Emission factors

### Purchased electricity

The Greenhouse Gas Inventory and Research Center (GIR) notice
[2024년 승인 국가 온실가스 배출계수_전력배출계수](https://www.gir.go.kr/home/board/read.do?boardId=82&boardMasterId=2&menuId=36)
was posted on **2025-03-31**. Its attachment is preserved as
`data/raw/research/gir_2024_approved_electricity_factors.pdf` and extracted text
as `gir_2024_approved_electricity_factors.txt`. The table is based on recent
**2020–2022** national statistics, the 2006 IPCC Guidelines, and revised energy
supply/demand statistics.

| Scope | CO2e | CO2 | CH4 | N2O |
| --- | ---: | ---: | ---: | ---: |
| Generation | 0.4172 t CO2e/MWh | 0.4150 t CO2/MWh | 0.0044 kg CH4/MWh | 0.0077 kg N2O/MWh |
| Consumption | **0.4541 t CO2e/MWh** | 0.4517 t CO2/MWh | 0.0048 kg CH4/MWh | 0.0084 kg N2O/MWh |

For purchased electricity, the DSS should use the consumption factor:
**0.4541 kg CO2e/kWh**. The number is unchanged by the unit conversion because
1 t/MWh equals 1 kg/kWh.

The notice does not state a separate legal effective-from date. For audit
purposes, record **2025-03-31 as the publication/availability date**, not
2025-01-01. Applying it to January and February 2025 is a retrospective project
choice and must be labelled that way.

### City-gas LNG

The Korea Energy Agency (KEA) [온실가스 배출계수](https://tips.energy.or.kr/carbon/Ggas_tatistics03.do)
page publishes the components and the calculation method. The local capture is
`data/raw/research/kea_energy_emission_factors.html`.

| Official component | Value | Publication/revision |
| --- | ---: | --- |
| City-gas LNG carbon factor | 15.236 t C/TJ | 2022-01 publication |
| City-gas LNG net calorific value | 38.5 MJ/Nm3 | Energy Act calorific-value standard revised 2022-11-21 |
| Gas-boiler CH4 factor | 0.19 kg CH4/TJ | 2017-09 publication |
| Gas-boiler N2O factor | 0.93 kg N2O/TJ | 2017-09 publication |

Using the KEA formula, the CO2-only volume factor derived from the two official
city-gas components is:

`38.5 MJ/Nm3 × 15.236 t C/TJ × 44/12 × 1000 kg/t ÷ 1,000,000 MJ/TJ`

= **2.1508153333 kg CO2/Nm3**.

This is an arithmetic derivation, not a directly published CO2e factor. The DSS
must choose and document a GWP assessment basis before adding the CH4 and N2O
components as CO2e. It must not substitute a heat-output kg/kWh factor for the
metered gas-input basis. The machine-readable official rows and the explicit
selection are in `official_emission_factor_components.csv` and
`emission_factor_selection.json`.

## 2. Apartment denominators and parcels

### K-apt, December 2025 snapshot

K-apt is operated by the Ministry of Land, Infrastructure and Transport and the
Korea Real Estate Board. The [official data.go.kr basic-information schema](https://www.data.go.kr/data/15096285/standard.do)
defines `kaptTarea` as **건축물대장상 연면적** (building-register gross floor
area) and includes household count and address fields.

The public K-apt website endpoints are:

- Main page for session and CSRF token: `https://www.k-apt.go.kr/web/main/index.do`
- Complex list: `POST https://www.k-apt.go.kr/kaptinfo/getKaptList.do`
- Detail: `GET https://www.k-apt.go.kr/kaptinfo/getKaptInfo_detail.do?kaptCode={kaptCode}`
- K-apt coordinate definition: `https://www.k-apt.go.kr/knew/js/knew_map.js?v=2`

The list request uses `bjdCode`, `searchDate=202512`, `kaptDuty=ALL`, and the
page CSRF token. The two Jeonju district results are:

| District request | Raw rows | Local file |
| --- | ---: | --- |
| Wansan-gu `52111` | 193 | `kapt_jeonju_52111_202512.json` |
| Deokjin-gu `52113` | 171 | `kapt_jeonju_52113_202512.json` |
| **Total** | **364** | `kapt_jeonju_summary.csv` |

Eight detail records around the current Ho-seong-dong prototype were
materialized rather than issuing 364 detail requests:

| K-apt code | Complex | Register gross area (m2) | Households | WGS84 lon, lat |
| --- | --- | ---: | ---: | --- |
| A56121109 | 호성동 엘지동아 | 94,993.33 | 796 | 127.1521907584, 35.8552530425 |
| A56121107 | 동아아파트 | 77,615 | 684 | 127.1522873858, 35.8604098100 |
| A56121102 | 호성 유원파크맨션 | 25,717 | 220 | 127.1531810955, 35.8586378586 |
| A56121103 | 호성동 동신3차 | 26,406.289 | 248 | 127.1553743081, 35.8572829761 |
| A56121105 | 호성동 동신아파트 | 52,719.26 | 530 | 127.1543857070, 35.8578829376 |
| A56121104 | 호성동 신동아1차 | 225,711 | 320 | 127.1536325232, 35.8559422397 |
| A56121101 | 호성동 신동아2차 | 12,457 | 165 | 127.1534260669, 35.8571498717 |
| A56121110 | 호성동 주공1.2차 | 151,750.049 | 1,911 | 127.1508291616, 35.8588270257 |

Each raw `kapt_detail_{code}.json` keeps the complete response. The normalized
`kapt_jeonju_detail_candidates.csv` keeps K-apt code, legal-dong code, parcel
and road addresses, `kaptTarea`, household and building counts, heating type,
approval date, source x/y, and transformed WGS84 coordinates.

K-apt publishes this exact source coordinate definition in `knew_map.js`:

```text
+proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1
+x_0=200000 +y_0=500000 +ellps=bessel +units=m +no_defs
+towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43
```

`backend/app/kapt.py` preserves that literal proj4 string and transforms with
`pyproj.Transformer(..., always_xy=True)`. This is preferable to assigning a
modern Korean CRS by guesswork.

### Jeonju City corroborating workbook

Jeonju City posted [전주시 공동주택 현황(2025.12월)](https://www.jeonju.go.kr/planweb/board/view.9is?dataUid=9be517a89b212afa019b734df7f35e34&contentUid=ff8080818990c349018b041ac4823bb5&categoryUid1=9be517a78a45ae01018b4adca74866e9&boardUid=ff8080818bad9295018bb25702581197&page=1&subPath=)
on **2025-12-31**. The original `.xls` attachment is preserved as
`jeonju_apartment_status_2025_12.xls`.

- `준공(아파트,연립)`: 595 records after the three header rows; fields include
  complex name, use, district, administrative dong, parcel location, site area,
  gross floor area, building/floor counts, and households by floor-area band.
- `시공중`: 14 records after two header rows.

The municipal file covers more completed housing developments than the managed
K-apt list, but it has administrative-dong labels and no coordinates. Use it for
coverage checks and parcel/name corroboration; use the K-apt legal-dong code and
published coordinates for the initial spatial join.

### Legal-dong codes

The official Ministry of the Interior and Safety code download is
`https://www.code.go.kr/etc/codeFullDown.do?codeseId=법정동코드`. The downloaded
file is `data/raw/legal-dong.zip`. Match the 10-digit `bjdCode`; retain leading
zeros in parcel main/sub numbers.

## 3. Monthly physical energy quantities

The formal source is the [MOLIT K-apt apartment energy-use API](https://www.data.go.kr/data/15012964/openapi.do):

```text
GET https://apis.data.go.kr/1613000/ApHusEnergyUseInfoOfferServiceV2/
    getHsmpApHusUsgQtyInfoSearchV2
```

Required query identifiers are `kaptCode` and `reqDate=YYYYMM`, plus the
registered `serviceKey`. Physical fields and declared units are:

| Field | Meaning | Unit |
| --- | --- | --- |
| `helect` | electricity use | kWh |
| `hgas` | gas use | m3 |
| `hheat` | district/central heat use | Mcal |
| `hwaterHot` | hot-water use | tonne |

The adapter method `fetch_monthly_energy()` returns only these physical fields
and their units. The response also contains cost fields in won; the adapter
deliberately excludes them. **Costs must never be converted to kWh.**

No 2025 monthly energy rows are committed in this research package: the formal
service rejected an unregistered placeholder key with result code 30, and the
old anonymous K-apt energy-page route is disabled in the current site. This is
recorded as unavailable, not replaced by management-fee cost data. Once a valid
key is present, a reproducible call is:

```python
from app.kapt import fetch_monthly_energy
rows = fetch_monthly_energy("A56121109", "202501")
```

## 4. Reproduction and provenance

`collect_kapt()` refreshes the two district lists, derives a bounded detail
sample near the selected LG Dong-A complex, writes the normalized CSVs and
`kapt_provenance.json`, and upserts all 364 summaries into
`apartment_complexes`. Eight rows currently contain the complete detail JSON;
the remaining 356 retain summary JSON and coordinates while their detail-only
floor area and household fields remain null. Accordingly, source `kapt` is
`PARTIAL`, has `normalized_row_count=364`, and `missing_count=356`.

`collect_municipal(db)` upserts the original workbook into separate
`municipal_apartments` (595 completed) and
`municipal_apartments_under_construction` (14 construction-stage) tables. It
registers the whole unmodified workbook as the raw asset. Cached-source and
asset collection timestamps come from the corresponding raw file modification
time rather than the adapter run time.

`candidate_energy_parcels(db, limit=3)` projects K-apt's canonical lower-case
`bjd_code`, `bun`, and `ji` fields into the official MOLIT request names
`sigunguCd`, `bjdongCd`, `bun`, and `ji`. Duplicate parcel keys and addresses
explicitly marked as additional parcels are excluded. The selected LG Dong-A
parcel remains first.

`merge_energy_coordinates(db, year=2025)` assigns `grid_id` and
`match_method=KAPT_COMPLEX_CENTROID` only when the complete legal-dong code,
main lot, and sub-lot identify one K-apt complex. Duplicate or additional-parcel
cases are flagged as ambiguous; mountain-lot rows never match an ordinary K-apt
parcel, and failed matches clear any stale grid assignment. Each exact match
stores `matched_gross_floor_area_m2` in the energy row's linkage metadata. The
selected sector's `baseline_floor_area_m2` is set only from the requested year
when every available energy-type/month group has the same matched parcel set
and every parcel has detail `kaptTarea`. It does not allocate complex energy
among OSM building footprints.

```powershell
$env:PYTHONPATH='backend'
python -c "from app.kapt import collect_kapt; print(collect_kapt(refresh=True))"
```

Current verification hashes:

| File | SHA-256 |
| --- | --- |
| GIR factor PDF | `56FEDB7DB3B46434FE13A09D9B1DD249C84795E983A0C04A3448CE702596757F` |
| KEA factor HTML | `094CBFD4D8EAEBE8CDFEB7A1F5571D90BF735D545FACDFB4C4931B35881EF144` |
| K-apt Wansan raw | `64F0A796C1FC607715C618B8BA26ADF6EF8B63192B861D44B09F831D8C29FC0E` |
| K-apt Deokjin raw | `AAA47EF2332789544C666C8C6F94B4E4BBABE6ACA01B420460ECAAFD1FD91000` |
| Jeonju City December 2025 workbook | `C28057E1F43BF36DF72C61DBB68EADA183BB480DE4D5DBC2185D7377018400E1` |
| Twelve official factor-component rows | `ACEDDEB2765094EFA770E52BB685855CD79246763BC2928857C9A6ED6D1BD382` |

Normalized CSV hashes change when the bounded candidate order or schema changes;
`kapt_provenance.json` records the source-file timestamp, selected codes, and
endpoint templates for each run.
