"""Plain text of a 한글(HWP 5.0) file, enough to read a 조례 별표 table.

Many 도시·군계획 조례 keep the 용도지역 건폐율·용적률 in a 별표 that law.go.kr serves only as an .hwp
attachment. HWP 5.0 is an OLE compound file (MS-CFB) whose ``BodyText/Section<n>`` streams hold
(usually raw-deflated) records; paragraph text is record tag 67 (HWPTAG_PARA_TEXT) in UTF-16LE.
Table cells are ordinary paragraphs, so the text comes out cell by cell, row by row.

Only reading is supported; encrypted or distribution-protected documents return an empty string.
"""
from __future__ import annotations

import struct
import zlib

_FREE, _END = 0xFFFFFFFF, 0xFFFFFFFE
PARA_TEXT = 67
# Control characters that take 8 WCHARs (an inline/extended control), the rest take one.
_WIDE_CONTROLS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}


def ole_streams(data: bytes) -> dict[str, bytes]:
    """{"BodyText/Section0": bytes, …} of an OLE compound file."""
    if data[:8] != bytes.fromhex("d0cf11e0a1b11ae1"):
        raise ValueError("OLE 복합 문서가 아닙니다")
    sector_shift, mini_shift = struct.unpack_from("<HH", data, 30)
    size, mini_size = 1 << sector_shift, 1 << mini_shift
    n_fat, first_dir, _, mini_cutoff, first_minifat, n_minifat, first_difat, n_difat = struct.unpack_from("<IIIIIIII", data, 44)

    def sector(index: int) -> bytes:
        start = (index + 1) * size
        return data[start:start + size]

    difat = [x for x in struct.unpack_from("<109I", data, 76) if x not in (_FREE, _END)]
    nxt = first_difat
    for _ in range(n_difat):
        if nxt in (_FREE, _END):
            break
        values = struct.unpack(f"<{size // 4}I", sector(nxt))
        difat.extend(v for v in values[:-1] if v not in (_FREE, _END))
        nxt = values[-1]
    fat: list[int] = []
    for index in difat[:n_fat]:
        fat.extend(struct.unpack(f"<{size // 4}I", sector(index)))

    def chain(start: int, table: list[int]) -> list[int]:
        out, seen = [], set()
        while start not in (_FREE, _END) and start < len(table) and start not in seen:
            seen.add(start)
            out.append(start)
            start = table[start]
        return out

    def read(start: int) -> bytes:
        return b"".join(sector(i) for i in chain(start, fat))

    directory = read(first_dir)
    entries = []
    for offset in range(0, len(directory) - 127, 128):
        raw = directory[offset:offset + 128]
        name_len = struct.unpack_from("<H", raw, 64)[0]
        name = raw[:max(0, name_len - 2)].decode("utf-16-le", errors="replace")
        kind = raw[66]
        left, right, child = struct.unpack_from("<III", raw, 68)
        start, length = struct.unpack_from("<IQ", raw, 116)
        entries.append({"name": name, "kind": kind, "left": left, "right": right, "child": child, "start": start, "size": length & 0xFFFFFFFF})
    if not entries:
        return {}
    root = entries[0]
    ministream = read(root["start"]) if root["start"] not in (_FREE, _END) else b""
    minifat: list[int] = []
    for index in chain(first_minifat, fat)[:n_minifat or None]:
        minifat.extend(struct.unpack(f"<{size // 4}I", sector(index)))

    def read_mini(start: int) -> bytes:
        return b"".join(ministream[i * mini_size:(i + 1) * mini_size] for i in chain(start, minifat))

    streams: dict[str, bytes] = {}

    def walk(index: int, prefix: str, depth: int = 0) -> None:
        if index in (_FREE, _END) or index >= len(entries) or depth > 64:
            return
        entry = entries[index]
        walk(entry["left"], prefix, depth + 1)
        path = f"{prefix}{entry['name']}"
        if entry["kind"] == 2:
            body = read_mini(entry["start"]) if entry["size"] < mini_cutoff else read(entry["start"])
            streams[path] = body[:entry["size"]]
        elif entry["kind"] == 1:
            walk(entry["child"], path + "/", depth + 1)
        walk(entry["right"], prefix, depth + 1)

    walk(root["child"], "")
    return streams


def _records(body: bytes):
    pos = 0
    while pos + 4 <= len(body):
        header = struct.unpack_from("<I", body, pos)[0]
        pos += 4
        tag, size = header & 0x3FF, (header >> 20) & 0xFFF
        if size == 0xFFF:
            size = struct.unpack_from("<I", body, pos)[0]
            pos += 4
        yield tag, body[pos:pos + size]
        pos += size


def _para_text(payload: bytes) -> str:
    chars = []
    i = 0
    count = len(payload) // 2
    while i < count:
        code = struct.unpack_from("<H", payload, i * 2)[0]
        if code < 32:
            if code in (10, 13):
                chars.append("\n")
            elif code == 9:
                chars.append("\t")
            i += 8 if code in _WIDE_CONTROLS else 1
            continue
        chars.append(chr(code))
        i += 1
    return "".join(chars)


def hwp_text(data: bytes) -> str:
    """Paragraph texts of every body section, one per line ('' for encrypted/unsupported files)."""
    streams = ole_streams(data)
    header = streams.get("FileHeader", b"")
    if not header.startswith(b"HWP Document File"):
        return ""
    flags = struct.unpack_from("<I", header, 36)[0] if len(header) >= 40 else 0
    compressed, encrypted, distributed = flags & 1, flags & 2, flags & 4
    if encrypted or distributed:
        return ""
    sections = sorted((k for k in streams if k.startswith("BodyText/Section")), key=lambda k: int(k.rsplit("Section", 1)[1] or 0))
    lines = []
    for key in sections:
        body = streams[key]
        if compressed:
            try:
                body = zlib.decompressobj(-15).decompress(body)
            except zlib.error:
                continue
        for tag, payload in _records(body):
            if tag == PARA_TEXT:
                text = _para_text(payload).strip()
                if text:
                    lines.append(text)
    return "\n".join(lines)
