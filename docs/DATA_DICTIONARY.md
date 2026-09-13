# 데이터 사전

|테이블|핵심 필드|의미|
|---|---|---|
|data_sources|id,organization,source_url,source_type,status,row counts|현재 출처 상태|
|collection_jobs|datasets,start_month,end_month,status,progress,errors|DB에 유지되는 비동기 수집 이력|
|raw_data_assets|provider,source_url,storage_location,row_count,request_parameters,collected_at|원본 증거와 비밀을 제외한 요청정보|
|regions|code,sigungu_code,bjdong_code,version|MOIS 현행 법정동. 문자열로 선행0 보존|
|grid_500m|id,geom,area_m2,geojson|EPSG5179 분석 셀. 기존 ID는 이력의 기준|
|energy_monthly|지번 식별자,use_ym,energy_type,usage_kwh,raw_record,grid_id,match_method|월별 실제 관측. null과0 구분|
|weather_monthly|use_ym,provider,mean/min/max_temperature,precipitation,hdd,cdd,days_observed|일별에서 계산한 월별 자료|
|emission_factors|energy_type,factor,factor_unit,reference_year,source_url,effective_from,notes|검증된 계수와 적용설명|
|buildings|id,grid_id,source_type,footprint_m2,floor_area_m2,geojson|OSM 또는 사용자 건물 폴리곤|
|apartment_complexes|Kapt code,법정동·지번,coordinates,summary/detail|공식 단지 목록·상세. 건물 폴리곤과 별도|
|municipal_apartments|원본 행 및 정규화 속성|전주시 준공 공동주택 현황|
|municipal_apartments_under_construction|원본 행 및 정규화 속성|시공 중 공동주택. 현재 기준과 분리|
|building_register|parcel_code,attributes,raw_record|별도 활용 승인된 공식 건축물대장|
|zoning_areas|source,properties,geojson|확보·입력된 용도지역. 현재 FAR로 법적 상한을 추측하지 않음|
|population_grid|source,grid_id,population,reference_period|원본 격자와 집계 근거는 imported_records에 보존|
|testbed_sectors|grid_id,reason,candidates,metadata_json|선정 이유·후보·관측과 매칭된 모델 기준면적|
|scenarios / scenario_results|inputs / result|계획 입력·결과. 실측과 분리|
|model_runs|year,result,created_at|실제 모델 검증 결과|
|upload_batches / imported_records|preview,mapping,source CRS,original/normalized geometry|수동 매핑 감사 기록|
|grid_id_mappings|old_grid_id,new_grid_id,batch_id|외부 격자와 기존 분석 ID의 명시적 대응|

에너지 단위는 kWh, 면적 m², 온도 °C, 강수 mm, HDD/CDD °C·day, 탄소 kgCO2eq이다. Kapt 가스 원단위 m³는 열량·표준조건 검증 없이 kWh로 바꾸지 않는다. 인구가 없으면 세대수×임의 인원으로 실측 인구를 만들지 않는다.
