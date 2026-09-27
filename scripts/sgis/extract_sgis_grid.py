"""Cut the nationwide SGIS grid statistics package to an analysis area (default Jeonju) or keep all of it (--national).

Input: the folder from 공공데이터포털 '국가데이터처_SGIS 격자 통계 및 경계' (data.go.kr 15141768), which holds
  1. 통계/…/<year>년_<group>_<100km block>_1K.csv   (기준연도, 격자코드, 통계항목, 통계값; CP949 or UTF-8)
  2. 경계/grid_<block>/grid_<block>_1K.shp/.dbf       (GRID_CD, EPSG:5179 1km squares)
  3. 코드집/2. 제공용 코드(statistics_code).xlsx       (item code → name; optional, needs openpyxl)

Output (default data/raw/sgis_grid_1k/<year>/): cells.csv, stats.csv, items.json, manifest.json.
Only standard-library Python is required (openpyxl only for the code names).

    python scripts/sgis/extract_sgis_grid.py --source "국가데이터처_SGIS 격자 통계 및 경계_20250630/국가데이터처_SGIS 격자 통계 및 경계"
    python scripts/sgis/extract_sgis_grid.py --national --source "…"   # 전국 (약 550만 행)

The grid code is <x block><y block><xx><yy>: x = 700000 + 100000·index(x block) + 1000·xx, y likewise from 1300000,
with blocks 가나다라마바사아. The script checks every kept boundary against that rule.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

BLOCKS = "가나다라마바사아"
X0, Y0 = 700000, 1300000
# Project 500m grid (EPSG:5179) spans x 954500–976500, y 1748000–1767500 → the 1km cells that contain it.
JEONJU_BBOX = (954000, 1748000, 977000, 1768000)
# Every 100km block (가~아 × 가~아): the whole country.
NATIONAL_BBOX = (700000, 1300000, 1500000, 2100000)
GROUPS = {"인구": "population", "가구": "household", "주택": "housing", "사업체": "business", "사업체중분류": "business_detail",
          "종사자": "worker", "종사자중분류": "worker_detail"}
CODE_RE = re.compile(r"^([가-힣])([가-힣])(\d{2})(\d{2})$")


def code_origin(code: str) -> tuple[int, int] | None:
    """Lower-left corner (EPSG:5179) of a 1km grid code such as 다마6862."""
    m = CODE_RE.match(code.strip())
    if not m or m.group(1) not in BLOCKS or m.group(2) not in BLOCKS:
        return None
    x = X0 + 100000 * BLOCKS.index(m.group(1)) + 1000 * int(m.group(3))
    y = Y0 + 100000 * BLOCKS.index(m.group(2)) + 1000 * int(m.group(4))
    return x, y


def blocks_for(bbox: tuple[int, int, int, int]) -> list[str]:
    xs = range((bbox[0] - X0) // 100000, (bbox[2] - 1 - X0) // 100000 + 1)
    ys = range((bbox[1] - Y0) // 100000, (bbox[3] - 1 - Y0) // 100000 + 1)
    return [BLOCKS[i] + BLOCKS[j] for i in xs for j in ys]


def inside(code: str, bbox: tuple[int, int, int, int]) -> bool:
    origin = code_origin(code)
    return bool(origin) and bbox[0] <= origin[0] < bbox[2] and bbox[1] <= origin[1] < bbox[3]


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"인코딩을 읽을 수 없습니다: {path.name}")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_dbf(path: Path) -> list[dict[str, str]]:
    data = path.read_bytes()
    count, header_len, record_len = struct.unpack("<I", data[4:8])[0], *struct.unpack("<HH", data[8:12])
    fields, pos = [], 32
    while data[pos] != 0x0D:
        fields.append((data[pos:pos + 11].split(b"\0")[0].decode("ascii"), data[pos + 16]))
        pos += 32
    rows = []
    for i in range(count):
        rec = data[header_len + i * record_len: header_len + (i + 1) * record_len]
        at, row = 1, {}
        for name, length in fields:
            row[name] = rec[at:at + length].decode("utf-8", "replace").strip()
            at += length
        rows.append(row)
    return rows


def read_shp_boxes(path: Path) -> list[tuple[float, float, float, float, int]]:
    """(xmin, ymin, xmax, ymax, point count) per polygon record."""
    data = path.read_bytes()
    out, pos = [], 100
    while pos + 8 <= len(data):
        length = struct.unpack(">i", data[pos + 4:pos + 8])[0] * 2
        content = data[pos + 8: pos + 8 + length]
        xmin, ymin, xmax, ymax = struct.unpack("<4d", content[4:36])
        points = struct.unpack("<i", content[40:44])[0]
        out.append((xmin, ymin, xmax, ymax, points))
        pos += 8 + length
    return out


def read_items(xlsx: Path) -> dict[str, dict[str, str]]:
    try:
        import openpyxl
    except ImportError:
        return {}
    wb = openpyxl.load_workbook(xlsx, read_only=True)
    ws = wb["격자"]
    items: dict[str, dict[str, str]] = {}
    category = group = None
    for row in list(ws.iter_rows(values_only=True))[2:]:
        cells = list(row)
        code = next((c.strip() for c in cells if isinstance(c, str) and re.fullmatch(r"[a-z0-9_]+", c.strip())), None)
        if cells and cells[0]:
            category = str(cells[0]).replace("\n", " ").strip()
        if not code:
            continue
        idx = [c.strip() if isinstance(c, str) else c for c in cells].index(code)
        if len(cells) > 1 and cells[1] and idx - 1 != 1:
            group = str(cells[1]).replace("\n", " ").strip()
        name = str(cells[idx - 1]).replace("\n", " ").strip() if idx > 0 and cells[idx - 1] else code
        items[code] = {"name": name, "group": group or "", "category": category or ""}
    return items


def extract(source: Path, out: Path, bbox: tuple[int, int, int, int]) -> dict:
    stats_dir, bound_dir, code_dir = source / "1. 통계", source / "2. 경계", source / "3. 코드집"
    if not stats_dir.is_dir() or not bound_dir.is_dir():
        raise SystemExit(f"'1. 통계'와 '2. 경계' 폴더가 있는 원본 폴더를 지정하세요: {source}")
    blocks = blocks_for(bbox)
    out.mkdir(parents=True, exist_ok=True)
    used: list[dict] = []

    cells = []
    for block in blocks:
        folder = bound_dir / f"grid_{block}"
        shp, dbf = folder / f"grid_{block}_1K.shp", folder / f"grid_{block}_1K.dbf"
        if not shp.exists():
            continue
        records, boxes = read_dbf(dbf), read_shp_boxes(shp)
        if len(records) != len(boxes):
            raise SystemExit(f"경계 레코드 수 불일치: {shp.name}")
        for rec, box in zip(records, boxes):
            code = rec.get("GRID_CD", "")
            if not inside(code, bbox):
                continue
            x, y = code_origin(code)
            if (round(box[0]), round(box[1]), round(box[2]), round(box[3])) != (x, y, x + 1000, y + 1000) or box[4] != 5:
                raise SystemExit(f"격자코드와 경계가 맞지 않습니다: {code} {box}")
            cells.append({"grid_cd": code, "x_min": x, "y_min": y, "x_max": x + 1000, "y_max": y + 1000, "size_m": 1000})
        used.append({"file": str(shp.relative_to(source)), "sha256": sha256(shp), "kept": len(cells)})
    with (out / "cells.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["grid_cd", "x_min", "y_min", "x_max", "y_max", "size_m"])
        writer.writeheader()
        writer.writerows(sorted(cells, key=lambda c: c["grid_cd"]))

    years: set[int] = set()
    kept_rows = 0
    with (out / "stats.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["base_year", "grid_cd", "item", "value", "group"])
        for path in sorted(stats_dir.rglob("*_1K.csv")):
            m = re.match(r"(\d{4})년_(.+)_([가-힣]{2})_1K\.csv$", path.name)
            if not m or m.group(3) not in blocks:
                continue
            group = GROUPS.get(m.group(2), m.group(2))
            n = 0
            reader = csv.reader(read_text(path).splitlines())
            next(reader, None)
            for row in reader:
                if len(row) < 4 or not inside(row[1], bbox):
                    continue
                writer.writerow([row[0], row[1].strip(), row[2].strip(), row[3].strip(), group])
                years.add(int(row[0]))
                n += 1
            kept_rows += n
            used.append({"file": str(path.relative_to(source)), "sha256": sha256(path), "kept": n})

    xlsx = code_dir / "2. 제공용 코드(statistics_code).xlsx"
    items = read_items(xlsx) if xlsx.exists() else {}
    (out / "items.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    manifest = {
        "dataset": "국가데이터처_SGIS 격자 통계 및 경계 (공공데이터포털 15141768)",
        "source_folder": source.name, "grid_size_m": 1000, "crs": "EPSG:5179",
        "base_years": sorted(years), "bbox_5179": list(bbox), "blocks": blocks,
        "cells": len(cells), "stat_rows": kept_rows, "items_named": len(items),
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "files": used,
        "rules": [
            "인구 부문 5 미만(사업체 부문 3 미만) 값은 0 또는 5(3)로 확률 대체되고, 그 이상은 최대 ±7(±4)의 잡음이 들어 있다 (iLBA).",
            "격자에 행이 없으면 그 항목의 통계가 생성되지 않은 것이다(인구·사업체가 없는 격자 등). 0으로 채우지 않는다.",
            "세부 항목의 합이나 작은 격자의 합은 총괄 항목과 같지 않다. 총계는 to_* 항목을 쓴다.",
            "공공데이터포털 제공 범위는 1km 격자다. 500m·100m는 SGIS 자료신청이 필요하다.",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="'1. 통계', '2. 경계', '3. 코드집'이 있는 폴더")
    parser.add_argument("--out", default=None, help="출력 폴더 (기본 data/raw/sgis_grid_1k/<기준연도>)")
    parser.add_argument("--bbox", default=",".join(map(str, JEONJU_BBOX)), help="EPSG:5179 xmin,ymin,xmax,ymax")
    parser.add_argument("--national", action="store_true", help="전국 (모든 100km 블록): --bbox를 무시합니다")
    args = parser.parse_args()
    bbox = NATIONAL_BBOX if args.national else tuple(int(v) for v in args.bbox.split(","))
    source = Path(args.source)
    tmp = Path(args.out) if args.out else Path("data/raw/sgis_grid_1k/_new")
    manifest = extract(source, tmp, bbox)  # type: ignore[arg-type]
    if not args.out:
        final = Path("data/raw/sgis_grid_1k") / str(max(manifest["base_years"]))
        final.mkdir(parents=True, exist_ok=True)
        for name in ("cells.csv", "stats.csv", "items.json", "manifest.json"):
            (tmp / name).replace(final / name)
        tmp.rmdir()
        print(f"→ {final}")
    json.dump({k: manifest[k] for k in ("base_years", "cells", "stat_rows", "items_named")}, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
