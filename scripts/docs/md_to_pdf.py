"""Markdown 문서 → 표지·목차·쪽 번호가 있는 A4 PDF (사용 매뉴얼 배포용).

  python scripts/docs/md_to_pdf.py docs/USER_MANUAL.md docs/manual/Carbon-Urban-DSS-사용자-매뉴얼.pdf --title "사용자 매뉴얼" --doc-no CUD-UM-001

필요: pip install markdown playwright (+ playwright install chromium). 저장소 상대 링크(.md)는 GitHub 주소로 바꾼다.
"""
from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

import markdown

REPO = "https://github.com/shy0401/Carbon-Urban-DSS/blob/main/"
ROOT = Path(__file__).resolve().parents[2]

CSS = """
@page { size: A4; margin: 20mm 17mm 18mm 17mm; }
* { box-sizing: border-box; }
html { font-family: 'Pretendard Variable', Pretendard, 'Noto Sans CJK KR', 'Noto Sans KR', sans-serif; font-size: 10pt; color: #1C2622; line-height: 1.6; }
body { margin: 0; }
h1, h2, h3, h4 { color: #1F3A33; line-height: 1.3; break-after: avoid; }
h2 { font-size: 17pt; margin: 0 0 4mm; padding-bottom: 2mm; border-bottom: 1.5pt solid #2F5D50; break-before: page; }
h3 { font-size: 12.5pt; margin: 7mm 0 2.5mm; }
h4 { font-size: 11pt; margin: 5mm 0 2mm; }
p, li { orphans: 3; widows: 3; }
a { color: #2E5A87; text-decoration: none; word-break: break-all; }
code { font-family: 'D2Coding', 'Noto Sans Mono CJK KR', Consolas, monospace; font-size: 8.6pt; background: #ECEBE4; padding: 0.3mm 1mm; border-radius: 2px; word-break: break-all; }
pre { background: #1F3A33; color: #E6EEEA; padding: 3mm 4mm; border-radius: 3px; white-space: pre-wrap; word-break: break-all; break-inside: avoid; }
pre code { background: none; color: inherit; padding: 0; font-size: 8.4pt; }
table { width: 100%; border-collapse: collapse; margin: 3mm 0 4mm; font-size: 8.8pt; break-inside: auto; }
thead { display: table-header-group; }
tr { break-inside: avoid; }
th { background: #2F5D50; color: #fff; text-align: left; padding: 1.6mm 2mm; font-weight: 600; }
td { border-bottom: 0.5pt solid #D9D7CE; padding: 1.4mm 2mm; vertical-align: top; word-break: keep-all; overflow-wrap: anywhere; }
th { word-break: keep-all; }
tr:nth-child(even) td { background: #F6F6F1; }
blockquote { margin: 3mm 0; padding: 2.5mm 4mm; background: #FFF6E5; border-left: 3pt solid #C98A1B; color: #4A3B12; break-inside: avoid; }
blockquote p { margin: 0; }
figure { margin: 4mm 0 5mm; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; max-height: 205mm; border: 0.5pt solid #BDBAAE; border-radius: 2px; }
figcaption { font-size: 8.5pt; color: #505B55; margin-top: 1.5mm; }
hr { display: none; }
.cover { height: 257mm; display: flex; flex-direction: column; justify-content: space-between; break-after: page; }
.cover .band { background: #1F3A33; color: #E6EEEA; padding: 16mm 14mm 14mm; border-radius: 4px; }
.cover .kicker { letter-spacing: 0.3em; font-size: 9pt; color: #9FB5AB; }
.cover .name { font-size: 30pt; font-weight: 800; margin: 6mm 0 2mm; color: #fff; }
.cover .title { font-size: 20pt; font-weight: 600; color: #E6EEEA; }
.cover .lead { margin-top: 8mm; font-size: 10.5pt; color: #C9D8D1; max-width: 140mm; }
.cover table { font-size: 9pt; }
.cover th { width: 32mm; }
.toc { break-after: page; }
.toc h2 { break-before: avoid; }
.toc ul { list-style: none; padding-left: 0; columns: 1; }
.toc li { margin: 1.6mm 0; font-size: 11pt; border-bottom: 0.4pt dotted #BDBAAE; padding-bottom: 1mm; }
.doc > h1:first-child { display: none; }
"""


def convert(md_text: str, base: Path) -> tuple[str, str, list[tuple[int, str, str]]]:
    # repository-relative markdown links → GitHub
    def link(m: re.Match) -> str:
        target = m.group(2)
        if re.match(r"^(https?:|#|mailto:)", target) or target.startswith("images/"):
            return m.group(0)
        path = (base / target.split("#")[0]).resolve()
        try:
            rel = path.relative_to(ROOT).as_posix()
        except ValueError:
            return m.group(0)
        anchor = "#" + target.split("#", 1)[1] if "#" in target else ""
        return f"[{m.group(1)}]({REPO}{rel}{anchor})"
    md_text = re.sub(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", link, md_text)
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"], extension_configs={"toc": {"toc_depth": "2-2"}})
    body = md.convert(md_text)
    body = re.sub(r'<p>\s*<img alt="([^"]*)" src="([^"]+)"\s*/?>\s*</p>',
                  lambda m: f'<figure><img src="{(base / m.group(2)).resolve().as_uri()}" alt="{m.group(1)}"><figcaption>{m.group(1)}</figcaption></figure>', body)
    heads = [(int(t["level"]), t["id"], t["name"]) for t in md.toc_tokens] if md.toc_tokens else []
    flat: list[tuple[int, str, str]] = []
    def walk(tokens):
        for t in tokens:
            flat.append((t["level"], t["id"], t["name"]))
            walk(t.get("children", []))
    walk(md.toc_tokens)
    return body, md.toc, flat


def build(src: Path, out: Path, title: str, doc_no: str, lead: str) -> None:
    text = src.read_text(encoding="utf-8")
    # The first table after the H1 is the document information block: it goes to the cover.
    first_h2 = text.index("\n## ")
    head, rest = text[:first_h2], text[first_h2:]
    info = re.search(r"(\|.*\|\n)+", head)
    info_html = markdown.markdown(info.group(0), extensions=["tables"]) if info else ""
    # the manual's own hand-written table of contents is replaced by the generated one
    rest = re.sub(r"\n## 목차\n.*?(?=\n---|\n## )", "\n", rest, flags=re.S)
    body, _, heads = convert(rest, src.parent)
    toc = "".join(f'<li><a href="#{i}">{html.escape(n)}</a></li>' for lvl, i, n in heads if lvl == 2)
    font_css = (ROOT / "frontend/public/fonts/pretendard/pretendardvariable-dynamic-subset.css").as_uri()
    page = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>Carbon Urban DSS {html.escape(title)}</title>
<link rel="stylesheet" href="{font_css}"><style>{CSS}</style></head><body>
<section class="cover"><div class="band"><div class="kicker">CARBON URBAN DSS</div><div class="name">Carbon Urban DSS</div>
<div class="title">{html.escape(title)}</div><div class="lead">{html.escape(lead)}</div></div>{info_html}</section>
<section class="toc"><h2>목차</h2><ul>{toc}</ul></section>
<main class="doc">{body}</main></body></html>"""
    tmp = out.with_suffix(".html")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(page, encoding="utf-8")
    from playwright.sync_api import sync_playwright
    footer = (f'<div style="width:100%;font-size:7.5pt;color:#6B746E;padding:0 17mm;display:flex;justify-content:space-between;font-family:sans-serif">'
              f'<span>Carbon Urban DSS · {html.escape(title)} · {html.escape(doc_no)}</span><span><span class="pageNumber"></span> / <span class="totalPages"></span></span></div>')
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page()
        pg.goto(tmp.as_uri(), wait_until="networkidle")
        pg.pdf(path=str(out), format="A4", print_background=True, display_header_footer=True, header_template="<div></div>", footer_template=footer,
               margin={"top": "18mm", "bottom": "16mm", "left": "17mm", "right": "17mm"})
        browser.close()
    tmp.unlink()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--title", default="사용자 매뉴얼"); ap.add_argument("--doc-no", default="CUD-UM-001")
    ap.add_argument("--lead", default="관측 건물 에너지로 도시 운영 탄소를 계산하고, 개발 계획의 영향을 미리 보는 의사결정 지원 도구")
    a = ap.parse_args()
    build(Path(a.src).resolve(), Path(a.out).resolve(), a.title, a.doc_no, a.lead)
    print("PDF:", a.out)
