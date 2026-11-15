"""팀원이 보낸 자료를 붙일 때 보낸 사람의 이름이 DB·기록·화면·문서에 남지 않게 한다.

이름 목록은 저장소에 두지 않는다(목록이 곧 기록이 되므로). 각 PC가 둘 중 하나에 적는다.

* ``.env``의 ``PRIVATE_NAMES`` (쉼표로 구분)
* ``DATA_DIR/ops/private_names.txt`` (한 줄에 하나, ``#`` 뒤는 주석. ``data/``는 Git에 올리지 않음)

목록이 없어도 잡는 관례(폴더·파일 이름에 보낸 사람을 붙이는 버릇):

* 날짜 뒤에 붙인 한글 2~4자: ``urban-carbon_공유_전체_2026-10-01_이몽룡`` → ``urban-carbon_공유_전체_2026-10-01``
* ``수집``·``전달``·``공유`` 등 뒤에 붙인 한글 2~4자: ``데이터수집_이몽룡`` → ``데이터수집``
* 규칙은 시·군·구·동·읍·면·리·도로 끝나는 말을 지명으로 보아 건너뛴다(``…_2026-10-03_효자동``). 그렇게 끝나는 이름이나
  다른 자리에 쓴 이름은 목록에 적어야 잡힌다.

가져오기 코드는 기록하는 경로·파일 이름을 ``scrub_path``로, 사람이 적은 글자(제공 기관 등)를 ``scrub_text``로 거친다.
점검: ``python backend/app/privacy.py check`` (저장소에 올라가는 파일), ``python -m app.privacy check --db`` (DB).
이 파일은 표준 라이브러리만 쓴다(GitHub 점검에서 그대로 돌림). 한 줄에 ``privacy: ok``를 적으면 그 줄은 건너뛴다.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

PLACEHOLDER = "팀원"
NAMES_FILE = Path("ops") / "private_names.txt"
IGNORE_MARK = "privacy: ok"

# 이름이 아닌 말(날짜·수집 뒤에 자주 붙는 것). 행정구역 이름(…시·군·구·동·읍·면·리·도)도 이름으로 보지 않는다.
STOPWORDS = frozenset("""전체 자료 원본 정리 결과 최종 수정 사본 백업 일부 설명 공유 전달 인계 묶음 파일 폴더 데이터 팀원 보정 검토 초안
완료 확인 추가 새로 예시 시험 테스트 요약 목록 보고서 발표 대본 영상 지도 격자 건물 전기 가스 난방 배출 인구 통계 기록 사례 모델 학습
코드 저장소 받음 보냄 수집 제공 응답 원문 표본 기준 계산 추정 공개 비공개 제외 포함 처리 갱신 변경 반영 오전 오후 야간 주간 월별 연도별
지역 지역별 도시 전국 공동주택 아파트 단지 버전 판 차수 최신 이전 다음 임시 개인 공용 메모 노트 정본 회의 요청 답변 점검 분석
백테스트 시연 보고 수정판 개정 초판 공지 계획 계획안 공고 고시 시행 개편 버튼 화면 전력 열 기타 합계 평균 중앙값 없음 있음 미정""".split())
ADMIN_SUFFIX = re.compile(r"(시|군|구|동|읍|면|리|도)$")
HANGUL_NAME = r"[가-힣]{2,4}"
DATE = r"(?:19|20)\d{2}[-.]?\d{2}[-.]?\d{2}"
AFTER_WORDS = r"(?:수집|전달|공유|보냄|받음|제공|자료)"
# 폴더·파일 이름(확장자 뺀 것)의 끝에 붙은 이름
SEG_AFTER = re.compile(rf"(?:{DATE}|{AFTER_WORDS})([_\- ]({HANGUL_NAME}))$")
EXTENSION = re.compile(r"^(.*?)((?:\.[A-Za-z0-9]{1,8})*)$")
# 글 안에서 사람을 출처로 적은 꼴
END = r"(?=\s*[,)\]·/]|\s*$)"  # 이름이 마디 끝에 옴(뒤에 다른 낱말이 이어지면 글월)
TEXT_PATTERNS = (
    re.compile(rf"(?:팀 수집|수집자|수집|보낸 사람|보낸이|작성자|작성|담당자|담당|제공자)\s*[:：]\s*({HANGUL_NAME}){END}"),
    re.compile(rf"\(({HANGUL_NAME}),\s*{DATE}\)"),
    re.compile(rf"{DATE}_({HANGUL_NAME})(?![가-힣])"),
    re.compile(rf"(?:데이터수집|수집|전달|공유)_({HANGUL_NAME})(?![가-힣])"),
)


def _is_word(token: str) -> bool:
    """이름이 아닌 낱말: 목록에 있거나, 행정구역 이름이거나, 목록 낱말 둘을 붙인 것(발표자료)."""
    if token in STOPWORDS or ADMIN_SUFFIX.search(token):
        return True
    return any(token[:i] in STOPWORDS and token[i:] in STOPWORDS for i in range(1, len(token)))


@lru_cache(maxsize=8)
def _names_cached(env_value: str, file_path: str, file_mtime: float) -> tuple[str, ...]:
    names = {n.strip() for n in env_value.split(",")}
    if file_path:
        for line in Path(file_path).read_text(encoding="utf-8-sig").splitlines():
            names.add(line.split("#", 1)[0].strip())
    return tuple(sorted((n for n in names if len(n) >= 2), key=len, reverse=True))


def private_names() -> tuple[str, ...]:
    """이 PC에 적어 둔 이름들(긴 것부터). 없으면 빈 묶음."""
    path = Path(os.getenv("DATA_DIR", "data")) / NAMES_FILE
    try:
        mtime = path.stat().st_mtime if path.is_file() else 0.0
    except OSError:
        mtime = 0.0
    return _names_cached(os.getenv("PRIVATE_NAMES", ""), str(path) if mtime else "", mtime)


def scrub_segment(segment: str, names: Iterable[str] | None = None) -> str:
    """폴더·파일 이름 하나에서 사람 이름을 뺀다(확장자는 그대로). 다 빠지면 ``팀원``."""
    names = private_names() if names is None else tuple(names)
    m = EXTENSION.match(segment)
    stem, ext = (m.group(1), m.group(2)) if m and m.group(1) else (segment, "")
    out = stem
    for name in names:
        out = re.sub(rf"[_\- ]?{re.escape(name)}", "", out)
    m = SEG_AFTER.search(out)
    if m and not _is_word(m.group(2)):
        out = out[:m.start(1)]
    if out == stem:
        return segment
    return (out.strip("_- ") or PLACEHOLDER) + ext


def scrub_path(path: str | None, names: Iterable[str] | None = None) -> str | None:
    """기록할 경로(``a/b/c.csv``, ``a\\b``)의 각 부분에서 사람 이름을 뺀다."""
    if not path:
        return path
    names = private_names() if names is None else tuple(names)
    parts = re.split(r"([\\/])", path)
    return "".join(p if p in ("/", "\\") or not p else scrub_segment(p, names) for p in parts)


def scrub_text(value: Any, names: Iterable[str] | None = None) -> Any:
    """사람이 적은 글자에서 적어 둔 이름을 ``팀원``으로 바꾼다(글자가 아니면 그대로)."""
    if not isinstance(value, str) or not value:
        return value
    names = private_names() if names is None else tuple(names)
    for name in names:
        value = value.replace(name, PLACEHOLDER)
    return value


def word_pattern(names: Iterable[str]) -> str:
    """이름이 한 낱말로 쓰인 자리만(앞뒤가 한글이 아님). '○○교회' 같은 건물·지명 안의 같은 글자는 건드리지 않는다.
    Python ``re``와 PostgreSQL 정규식 모두에서 쓰는 꼴."""
    return "(?<![가-힣])(?:" + "|".join(re.escape(n) for n in names) + ")(?![가-힣])"


def scrub_word(value: Any, names: Iterable[str] | None = None) -> Any:
    """자료 값(표의 칸)에서 이름이 한 낱말로 쓰인 자리만 ``팀원``으로."""
    if not isinstance(value, str) or not value:
        return value
    names = private_names() if names is None else tuple(names)
    return re.sub(word_pattern(names), PLACEHOLDER, value) if names else value


def scrub_values(values: dict[str, Any], names: Iterable[str] | None = None) -> dict[str, Any]:
    """팀이 보낸 표의 한 줄(개발 사례·점수 줄): 이름이 한 낱말로 든 칸만 바꾼다."""
    names = private_names() if names is None else tuple(names)
    if not names:
        return values
    return {k: scrub_word(v, names) for k, v in values.items()}


def find_private(text: str, names: Iterable[str] | None = None) -> list[tuple[int, str]]:
    """[(줄 번호, 무엇)]: 적어 둔 이름, 또는 사람을 출처로 적은 꼴. 이름 자체는 돌려주지 않는다."""
    names = private_names() if names is None else tuple(names)
    out: list[tuple[int, str]] = []
    for no, line in enumerate(text.splitlines(), 1):
        if IGNORE_MARK in line:
            continue
        if any(n in line for n in names):
            out.append((no, "적어 둔 이름"))
            continue
        for pattern in TEXT_PATTERNS:
            if any(not _is_word(m.group(1)) for m in pattern.finditer(line)):
                out.append((no, "사람을 출처로 적은 꼴"))
                break
    return out


# --------------------------------------------------------------------------- 저장소 점검
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".ps1",
                 ".cmd", ".sh", ".html", ".css", ".csv", ".sql", ".example", ".conf", ".xml", ".svg", ""}
OFFICE_SUFFIXES = {".pptx", ".docx", ".xlsx"}  # 압축 안의 XML 글자(슬라이드·발표자 노트·본문·셀)를 본다. PDF는 보지 않음
SKIP = re.compile(r"(^|/)(node_modules|dist|\.git|__pycache__)/|package-lock\.json$|\.min\.js$")
WALK_SKIP = re.compile(r"^(data|tmp|output|\.venv[^/]*|\.idea|\.worktrees|Claude outputs|팀원전달_[^/]*|urban-carbon_[^/]*|데이터수집_[^/]*|국가데이터처_[^/]*)/")


def repo_files(root: Path, listed: Path | None = None) -> list[Path]:
    """Git에 올라가는 파일(``git ls-files``, 또는 그 출력을 담은 ``listed``). git이 없으면 data·node_modules 등을 뺀 전체."""
    if listed is not None:
        names = listed.read_text(encoding="utf-8-sig").splitlines()
        files = [root / n.strip().strip('"') for n in names if n.strip()]
        return [p for p in files if p.suffix.lower() in TEXT_SUFFIXES | OFFICE_SUFFIXES and not SKIP.search(p.as_posix()) and p.is_file()]
    try:
        listed = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True).stdout.decode("utf-8")
        files = [root / p for p in listed.split("\0") if p]
    except (OSError, subprocess.CalledProcessError):
        files = [p for p in root.rglob("*") if p.is_file() and not WALK_SKIP.search(p.relative_to(root).as_posix())]
    return [p for p in files if p.suffix.lower() in TEXT_SUFFIXES | OFFICE_SUFFIXES and not SKIP.search(p.as_posix()) and p.is_file()]


def office_texts(path: Path) -> list[tuple[str, str]]:
    """[(압축 안 파일, 글자)]: 태그를 뺀 XML 글자. 읽지 못하면 빈 목록."""
    import zipfile
    out: list[tuple[str, str]] = []
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if name.endswith(".xml"):
                    raw = z.read(name).decode("utf-8", "ignore")
                    out.append((name, re.sub(r"<[^>]+>", " ", raw)))
    except (zipfile.BadZipFile, OSError):
        return []
    return out


def check_repo(root: Path, names: Iterable[str] | None = None, listed: Path | None = None) -> list[str]:
    names = private_names() if names is None else tuple(names)
    problems: list[str] = []
    for path in repo_files(root, listed):
        rel = path.relative_to(root).as_posix()
        if rel.endswith("backend/app/privacy.py") or rel.endswith("backend/tests/test_privacy.py"):
            continue  # 규칙을 적은 파일 자신(예시 이름은 지어낸 것)
        if scrub_path(rel, names) != rel:
            problems.append(f"{scrub_path(rel, names)}: 경로 이름에 사람 이름")
        if path.suffix.lower() in OFFICE_SUFFIXES:
            for part, text in office_texts(path):
                if any(n in text for n in names) or any(what for _, what in find_private(text, ())):
                    problems.append(f"{scrub_path(rel, names)}#{part}: 문서 안 글자에 사람 이름")
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for no, what in find_private(text, names):
            problems.append(f"{scrub_path(rel, names)}:{no}: {what}")
    return problems


def check_lines(lines: Iterable[str], names: Iterable[str] | None = None) -> list[str]:
    """PR이 더한 줄만 본다: ``+++ <파일>`` 머리 줄 뒤에 그 파일에 더한 줄(``+`` 뺀 것). GitHub 자동 병합이 쓴다(PR 코드는 실행하지 않음)."""
    names = private_names() if names is None else tuple(names)
    problems: list[str] = []
    current, count = "", 0
    for raw in lines:
        line = raw.rstrip("\n")
        if line.startswith("+++ "):
            current, count = line[4:].strip(), 0
            if current and scrub_path(current, names) != current:
                problems.append(f"{scrub_path(current, names)}: 경로 이름에 사람 이름")
            continue
        count += 1
        if current.endswith(("backend/app/privacy.py", "backend/tests/test_privacy.py")):
            continue
        for _, what in find_private(line, names):
            problems.append(f"{scrub_path(current, names)}: 더한 줄 {count}번째: {what}")
    return problems


# --------------------------------------------------------------------------- DB 점검·정리
# 가져오기가 경로·파일 이름을 적는 열: 경로 규칙까지 적용. (표, 열, 기본 키 열)
PATH_COLUMNS = (("team_imports", "path", "path"), ("team_grid500", "source_file", "id"), ("kcsm_imports", "path", "path"),
                ("kcsm_grid100", "source_file", "id"), ("upload_batches", "filename", "id"))


def _db_text_columns(conn: Any) -> list[tuple[str, str, str]]:
    from sqlalchemy import text
    return [tuple(r) for r in conn.execute(text("""select c.table_name, c.column_name, c.data_type from information_schema.columns c
        join information_schema.tables t on t.table_schema = c.table_schema and t.table_name = c.table_name and t.table_type = 'BASE TABLE'
        where c.table_schema = 'public' and c.data_type in ('text', 'character varying', 'json', 'jsonb')
        order by c.table_name, c.ordinal_position""")).all()]


def check_db(conn: Any, names: Iterable[str] | None = None) -> dict[str, int]:
    """{"표.열": 이름이 든 행 수}. 값은 돌려주지 않는다. 이름 목록이 없으면 빈 dict."""
    from sqlalchemy import text
    names = private_names() if names is None else tuple(names)
    if not names:
        return {}
    pattern = "|".join(re.escape(n) for n in names)
    by_table: dict[str, list[str]] = {}
    for table, column, _ in _db_text_columns(conn):
        by_table.setdefault(table, []).append(column)
    out: dict[str, int] = {}
    for table, columns in by_table.items():
        exprs = ", ".join(f'count(*) filter (where "{c}"::text ~ :p)' for c in columns)
        row = conn.execute(text(f'select {exprs} from public."{table}"'), {"p": pattern}).one()
        out.update({f"{table}.{c}": int(n) for c, n in zip(columns, row) if n})
    return out


def scrub_db(conn: Any, names: Iterable[str] | None = None, apply: bool = False) -> dict[str, int]:
    """DB에 남은 이름을 지운다: 경로 열은 ``scrub_path``(이름 자리를 뺌), 다른 글자·JSON 열은 이름이 한 낱말로 쓰인
    자리만 ``팀원``으로(건물 이름 '○○교회'처럼 다른 낱말 안의 같은 글자는 그대로).

    이름이 든 열만 다룬다(``check_db``). ``storage_location``(원본 파일 자리)은 바꾸면 파일을 못 찾으므로 세기만 한다.
    경로가 기본 키인 기록에서 이름을 뺀 값이 이미 있으면 이름 붙은 행을 지운다(같은 파일의 기록). 한 열이 실패하면
    그 열만 되돌리고 센다. ``apply=False``면 바꿀 행 수만 센다."""
    from sqlalchemy import text
    names = private_names() if names is None else tuple(names)
    found = check_db(conn, names)
    if not found:
        return {}
    pattern = "|".join(re.escape(n) for n in names)
    word = word_pattern(names)
    path_cols = {(t, c): pk for t, c, pk in PATH_COLUMNS}
    types = {f"{t}.{c}": d for t, c, d in _db_text_columns(conn)}
    stats: dict[str, int] = {}
    for key in found:
        table, column = key.split(".", 1)
        dtype = types[key]
        if column == "storage_location":
            stats[f"{key} (left: file path)"] = found[key]
            continue
        if not apply:
            if (table, column) in path_cols:
                stats[key] = found[key]
            else:  # 바꿀 것만(한 낱말로 든 이름). 다른 낱말 안의 같은 글자는 따로 셈
                n = int(conn.execute(text(f'select count(*) from public."{table}" where "{column}"::text ~ :w'), {"w": word}).scalar() or 0)
                stats[key] = n
                if found[key] - n:
                    stats[f"{key} (inside other words: left)"] = found[key] - n
            continue
        save = conn.begin_nested()
        try:
            if (table, column) in path_cols:
                pk = path_cols[(table, column)]
                rows = conn.execute(text(f'select "{pk}", "{column}" from public."{table}" where "{column}" ~ :p'), {"p": pattern}).all()
                changed = dropped = 0
                for ident, value in rows:
                    new = ";".join(scrub_path(v, names) or "" for v in value.split(";"))
                    if pk == column and conn.execute(text(f'select 1 from public."{table}" where "{pk}" = :n'), {"n": new}).first():
                        conn.execute(text(f'delete from public."{table}" where "{pk}" = :o'), {"o": ident})
                        dropped += 1
                        continue
                    conn.execute(text(f'update public."{table}" set "{column}" = :n where "{pk}" = :i'), {"n": new, "i": ident})
                    changed += 1
                stats[key] = changed
                if dropped:
                    stats[f"{key} (duplicate removed)"] = dropped
            else:
                cast = {"jsonb": "::jsonb", "json": "::json"}.get(dtype, "")
                stats[key] = int(conn.execute(text(
                    f'update public."{table}" set "{column}" = (regexp_replace("{column}"::text, :w, :ph, \'g\')){cast} '
                    f'where "{column}"::text ~ :w'), {"w": word, "ph": PLACEHOLDER}).rowcount or 0)
            save.commit()
        except Exception as exc:  # noqa: BLE001 — 한 열의 실패(키 겹침 등)는 그 열만 되돌림
            save.rollback()
            stats[f"{key} (failed: {type(exc).__name__})"] = found[key]
    return stats


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="팀원 이름이 저장소·DB에 남았는지 점검하고 지운다")
    p.add_argument("command", choices=["check", "check-lines", "scrub-db"])
    p.add_argument("--root", default=None, help="저장소 위치(기본: 이 파일의 두 단계 위)")
    p.add_argument("--db", action="store_true", help="check: DB도 점검")
    p.add_argument("--list", default=None, help="check: 볼 파일 목록(git ls-files 출력, git이 없는 곳에서)")
    p.add_argument("--apply", action="store_true", help="scrub-db: 실제로 바꿈(없으면 세기만)")
    args = p.parse_args(argv)
    names = private_names()
    if args.command == "check-lines":  # 표준 입력의 더한 줄(자동 병합). 걸린 것만 찍는다
        problems = check_lines(sys.stdin, names)
        if problems:
            print("\n".join(problems))
        return 1 if problems else 0
    print(f"이름 목록: {len(names)}개 ({'PRIVATE_NAMES·' + str(NAMES_FILE) if names else '없음: 관례 규칙만 점검'})")
    code = 0
    if args.command == "check":
        root = Path(args.root) if args.root else Path(__file__).resolve().parents[2]
        if (root / ".git").exists() or args.root or args.list:
            problems = check_repo(root, names, Path(args.list) if args.list else None)
            for line in problems:
                print(line)
            print(f"저장소: {len(problems)}건")
            code = 1 if problems else 0
        if args.db:
            from .db import engine  # type: ignore[import-not-found]
            with engine.connect() as conn:
                found = check_db(conn, names)
            for key, n in found.items():
                print(f"DB {key}: {n}행")
            print(f"DB: {sum(found.values())}행")
            code = code or (1 if found else 0)
        return code
    from .db import engine  # type: ignore[import-not-found]
    with engine.begin() as conn:
        stats = scrub_db(conn, names, apply=args.apply)
    for key, n in stats.items():
        print(f"{'바꿈' if args.apply else '바꿀 것'} {key}: {n}행")
    print(f"합계 {sum(v for k, v in stats.items() if '(' not in k)}행{'' if args.apply else ' (세기만, --apply로 바꿈)'}")
    return 1 if any("(failed" in k for k in stats) else 0


if __name__ == "__main__":
    if __package__ in (None, ""):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        __package__ = "app"  # noqa: A001 — `python backend/app/privacy.py check`도 되게
        import importlib
        sys.exit(importlib.import_module("app.privacy").main())
    sys.exit(main())
