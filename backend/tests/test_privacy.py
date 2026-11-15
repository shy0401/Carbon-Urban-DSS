"""팀원이 보낸 자료를 붙여도 보낸 사람 이름이 기록에 남지 않는다 (app.privacy). 이름은 모두 지어낸 것."""
from pathlib import Path

import pytest

from app.privacy import check_lines, check_repo, find_private, private_names, scrub_path, scrub_segment, scrub_text, scrub_values, scrub_word

NAMES = ("홍길동", "길순")


@pytest.mark.parametrize("segment, expected", [
    ("urban-carbon_공유_전체_2026-10-01_홍길동", "urban-carbon_공유_전체_2026-10-01"),  # 날짜 뒤 이름: 목록 없이도
    ("자료_20261106_김철수.zip", "자료_20261106.zip"),
    ("데이터수집_박영희", "데이터수집"),                                                   # 수집 뒤 이름: 목록 없이도
    ("x_길순_y.csv", "x_y.csv"),                                                           # 목록에 적은 이름
    ("홍길동", "팀원"),
    # 이름이 아닌 것은 그대로
    ("52110_전주시", "52110_전주시"), ("11740_서울특별시_강동구", "11740_서울특별시_강동구"), ("2026-10-01", "2026-10-01"),
    ("팀원전달_20261002", "팀원전달_20261002"), ("urban-carbon_전체_2026-11-06", "urban-carbon_전체_2026-11-06"),
    ("보고서_2026-11-11_발표자료.pptx", "보고서_2026-11-11_발표자료.pptx"), ("2026-10-01_전주시", "2026-10-01_전주시"),
    ("grid_500m.csv", "grid_500m.csv"), ("수집_전체", "수집_전체"),
])
def test_scrub_segment(segment, expected):
    assert scrub_segment(segment, NAMES) == expected


def test_scrub_path_keeps_separators_and_other_parts():
    assert scrub_path("2026-10-01_이몽룡/52110_전주시/2024/grid_500m.csv", ()) == "2026-10-01/52110_전주시/2024/grid_500m.csv"
    # 시·군·구·동…으로 끝나는 이름은 지명과 구별할 수 없어 규칙으로는 못 잡음: 이 PC의 이름 목록에 적는다
    assert scrub_path("2026-10-01_홍길동/a.csv", ()) == "2026-10-01_홍길동/a.csv"
    assert scrub_path("2026-10-01_홍길동/a.csv", NAMES) == "2026-10-01/a.csv"
    assert scrub_path(r"F:\자료\데이터수집_박영희\share\a.csv", ()) == r"F:\자료\데이터수집\share\a.csv"
    assert scrub_path("", NAMES) == "" and scrub_path(None, NAMES) is None


def test_scrub_text_and_values_replace_only_listed_names():
    assert scrub_text("팀 수집: 홍길동, 7차", NAMES) == "팀 수집: 팀원, 7차"
    assert scrub_text("길순 자료", NAMES) == "팀원 자료" and scrub_text(3.5, NAMES) == 3.5 and scrub_text(None, NAMES) is None
    assert scrub_values({"a": "홍길동 확인", "b": 1.0, "c": None}, NAMES) == {"a": "팀원 확인", "b": 1.0, "c": None}
    # 자료 칸은 이름이 한 낱말일 때만: 건물·지명 안의 같은 글자는 그대로
    assert scrub_word("길순교회", NAMES) == "길순교회" and scrub_word("확인: 길순", NAMES) == "확인: 팀원" and scrub_word("길순,홍길동", NAMES) == "팀원,팀원"
    assert scrub_values({"a": "홍길동"}, ()) == {"a": "홍길동"}  # 목록이 없으면 글자는 그대로(경로 규칙은 경로에만)


def test_private_names_come_from_env_and_the_local_file(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PRIVATE_NAMES", " 홍길동 ,길순,")
    assert private_names() == ("홍길동", "길순")
    (tmp_path / "ops").mkdir()
    (tmp_path / "ops" / "private_names.txt").write_text("\ufeff# 이 PC에만 둠\n이몽룡  # 팀원\n성춘향\n", encoding="utf-8")
    monkeypatch.delenv("PRIVATE_NAMES")
    assert set(private_names()) == {"이몽룡", "성춘향"}


@pytest.mark.parametrize("line, hit", [
    ("국토교통부 탄소공간지도 (팀 수집: 홍길동, 7차 인계)", True),
    ("# 팀 사례 자료 (김철수, 2026-10-03)", True),
    ("| B | `urban-carbon_공유_전체_2026-10-01_박영희\\` |", True),
    ("PC 폴더 `데이터수집_박영희\\share`", True),
    ("길순 자료를 붙임", True),                                   # 목록에 적은 이름
    ("길순 자료를 붙임 <!-- privacy: ok -->", False),
    ("![보고서 작성: 계획안 고르기](x.jpg)", False), ("빠진 자료 전부 수집: 버튼 한 번", False),
    ("(팀원 자료, 2026-10-03)", False), ("백테스트(백테스트, 2026-10-27)", False), ("2026-10-01_전주시", False),
    ("PC 폴더 `데이터수집_*\\share`", False), ("팀 데이터셋 urban-carbon, 7차 인계 2026-10-20", False),
])
def test_find_private_lines(line, hit):
    assert bool(find_private(line, NAMES)) is hit


def test_check_repo_reports_paths_and_lines_without_printing_names(tmp_path: Path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("첫 줄\n출처(팀 수집: 홍길동)\n", encoding="utf-8")
    (tmp_path / "자료_2026-10-01_박영희").mkdir()
    (tmp_path / "자료_2026-10-01_박영희" / "b.txt").write_text("ok\n", encoding="utf-8")
    problems = check_repo(tmp_path, NAMES)
    assert "docs/a.md:2: 적어 둔 이름" in problems
    assert "자료_2026-10-01/b.txt: 경로 이름에 사람 이름" in problems
    assert not any("홍길동" in p or "박영희" in p for p in problems)


def test_check_repo_reads_text_inside_office_files(tmp_path: Path):
    import zipfile
    with zipfile.ZipFile(tmp_path / "deck.pptx", "w") as z:
        z.writestr("ppt/slides/slide1.xml", "<p:sld><a:t>제목</a:t></p:sld>")
        z.writestr("ppt/notesSlides/notesSlide1.xml", "<p:notes><a:t>이미 한 일: 길순 님의 사례</a:t></p:notes>")
    assert check_repo(tmp_path, NAMES) == ["deck.pptx#ppt/notesSlides/notesSlide1.xml: 문서 안 글자에 사람 이름"]
    assert check_repo(tmp_path, ()) == []


def test_check_lines_reads_only_added_lines_and_names_no_one():
    lines = ["+++ docs/a.md", "출처(팀 수집: 이몽룡)", "괜찮은 줄", "+++ 데이터수집_이몽룡/b.txt", "ok", "+++ backend/app/privacy.py", "(이몽룡, 2026-10-01)"]
    assert check_lines(lines, ()) == ["docs/a.md: 더한 줄 1번째: 사람을 출처로 적은 꼴", "데이터수집/b.txt: 경로 이름에 사람 이름"]
    assert check_lines(["+++ docs/a.md", "괜찮은 줄"], ()) == []


def test_repository_has_no_sender_names():
    """이 저장소 자체(관례 규칙 + 이 PC의 이름 목록). 실패하면 출처를 '팀 데이터셋 <이름>·받은 날짜'로 고친다."""
    root = Path(__file__).resolve().parents[2]
    if not (root / ".git").exists():
        pytest.skip("not a git checkout")
    assert check_repo(root) == []


def test_team_import_records_paths_without_the_sender_name(tmp_path: Path, monkeypatch):
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from app.team_grid import TeamDevelopment, TeamGrid500, TeamImport, import_team_grid
    monkeypatch.setenv("PRIVATE_NAMES", "길순")
    db = sessionmaker(create_engine("sqlite+pysqlite:///:memory:"))()
    city = tmp_path / "2026-11-20_이몽룡" / "52110_전주시"
    (city / "2024").mkdir(parents=True)
    (city / "2024" / "grid_500m.csv").write_text(
        "grid_id_500m,x_min_m,y_min_m,buildings_tco2e_total\n다마71b61b,971500,1761500,10\n", encoding="utf-8")
    (city / "developments.csv").write_text(
        "grid_id_500m,x_min_m,y_min_m,before_year,after_year,note\n다마71b61b,971500,1761500,2016,2024,길순 확인\n", encoding="utf-8")
    logged: list[str] = []
    import_team_grid(db, tmp_path, log=logged.append)
    recorded = [r.path for r in db.scalars(select(TeamImport))] + [r.source_file for r in db.scalars(select(TeamGrid500))]
    assert recorded and all(p.startswith("2026-11-20/52110_전주시/") for p in recorded)
    assert db.scalars(select(TeamDevelopment)).one().data["note"] == "팀원 확인"
    assert not any("이몽룡" in m or "길순" in m for m in logged)
    again = import_team_grid(db, tmp_path, log=lambda m: None)  # the scrubbed path is still the key of the done file
    assert again["skipped_files"] == 2
