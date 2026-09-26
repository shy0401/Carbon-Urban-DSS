from app.building_use import classify_use, floors, summarize_grid_buildings


def test_use_codes_map_by_major_group_and_unknown_codes_are_not_guessed():
    assert classify_use("02001") == ("공동주택", "RESIDENTIAL")
    assert classify_use("01000") == ("단독주택", "RESIDENTIAL")
    assert classify_use("14000") == ("업무시설", "COMMERCIAL")
    assert classify_use("17100") == ("공장", "INDUSTRIAL")
    assert classify_use("29000") == ("기타 용도(코드 29000)", "OTHER")
    assert classify_use(None) == (None, "UNKNOWN")
    assert classify_use("") == (None, "UNKNOWN")


def test_floor_counts_zero_and_invalid_are_missing():
    assert floors("12") == 12 and floors(3.0) == 3
    assert floors("0") is None and floors(None) is None and floors("-") is None


def test_grid_indicators_keep_numerators_and_only_use_known_floors():
    rows = [
        {"grid_id": "g1", "footprint_m2": 1000, "above_floors": 15, "use_category": "RESIDENTIAL"},
        {"grid_id": "g1", "footprint_m2": 500, "above_floors": None, "use_category": "COMMERCIAL"},
        {"grid_id": "g1", "footprint_m2": 500, "above_floors": "3", "use_category": "RESIDENTIAL"},
        {"grid_id": None, "footprint_m2": 999, "above_floors": 2, "use_category": "RESIDENTIAL"},
    ]
    summary = summarize_grid_buildings(rows, {"g1": "SUCCESS", "g2": "EMPTY_VALID"})
    g1 = summary["g1"]
    assert g1["building_count"] == 3 and g1["footprint_m2"] == 2000
    assert g1["coverage_pct"] == 0.8  # 2,000 / 250,000
    assert g1["floor_area_est_m2"] == 16500  # 1,000×15 + 500×3, the unknown-floor building excluded
    assert g1["far_est_pct"] == 6.6
    assert g1["floors_known_count"] == 2 and g1["floors_known_pct"] == 66.7
    assert g1["avg_floors"] == 9.0 and g1["max_floors"] == 15
    assert g1["category_share_pct"] == {"RESIDENTIAL": 75.0, "COMMERCIAL": 25.0}
    assert g1["dominant_use"] == "RESIDENTIAL"
    assert g1["residential_share_pct"] == 75.0 and g1["use_known_pct"] == 100.0
    # No use code at all (VWorld LT_C_SPBD): unknown, not "0% residential".
    unknown = summarize_grid_buildings([{"grid_id": "g", "footprint_m2": 300, "above_floors": 1, "use_category": None}])["g"]
    assert unknown["residential_share_pct"] is None and unknown["dominant_use"] is None and unknown["use_known_pct"] == 0.0
    # Requested without buildings: zeros; never requested: absent.
    assert summary["g2"]["building_count"] == 0 and summary["g2"]["far_est_pct"] is None
    assert "g3" not in summary
