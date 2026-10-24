"""Pandoc structural decoration; prose and original table cells stay intact."""
from __future__ import annotations

import html
import re


def text(value):
    if isinstance(value, list):
        return "".join(text(item) for item in value)
    if not isinstance(value, dict):
        return ""
    if value.get("t") == "Str":
        return value["c"]
    if value.get("t") in ("Space", "SoftBreak", "LineBreak"):
        return " "
    return text(value.get("c"))


def div(classes, blocks):
    return {"t": "Div", "c": [["", classes.split(), []], blocks]}


def raw(value):
    return {"t": "RawBlock", "c": ["html", value]}


def photo(block):
    return (block.get("t") == "Para" and len(block["c"]) == 1
            and block["c"][0].get("t") == "Image")


def decorate(blocks):
    result = []
    i = 0
    while i < len(blocks):
        block = blocks[i]
        if photo(block):
            photos = []
            while i < len(blocks) and photo(blocks[i]) and len(photos) < 4:
                items = [blocks[i]]
                i += 1
                if (i < len(blocks) and blocks[i].get("t") == "Para"
                        and len(blocks[i]["c"]) == 1 and blocks[i]["c"][0].get("t") == "Emph"):
                    items.append(blocks[i])
                    i += 1
                photos.append(div("diary-photo", items))
            result.append(div("photo-board", photos) if len(photos) > 1 else photos[0])
            continue
        if block.get("t") == "Table":
            # Pandoc Table: attr, caption, columns, head, bodies, foot.
            head = block["c"][3][1]
            labels = [text(cell[4]).strip() for cell in head[0][1]] if head else []
            if labels[:2] == ["时间", "地点"]:
                result.append(div("timeline", [block]))
            elif len(labels) == 3 and labels[1] == "状态" and labels[0].startswith("来源"):
                result.append(div("source-table", [block]))
            elif labels[:2] == ["指标", "数值"]:
                result.append(div("health-metrics", [block]))
            elif labels == ["项目", "开始", "结束", "类别"]:
                rows = [row for body in block["c"][4] for row in body[3]]
                bars = []
                for row in rows:
                    cells = [text(cell[4]).strip() for cell in row[1]]
                    if len(cells) != 4:
                        continue
                    name, start, end, kind = cells
                    if not all(re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", t) for t in (start, end)):
                        continue
                    a, b = [int(t[:2]) * 60 + int(t[3:]) for t in (start, end)]
                    if a == b:
                        continue
                    ranges = [(a, b)] if b > a else [(a, 1440), (0, b)]
                    spans = "".join(f'<i style="left:{left / 14.4:.2f}%;width:{(right-left) / 14.4:.2f}%"></i>'
                                    for left, right in ranges)
                    bars.append(f'<p>{html.escape(name)} · {html.escape(kind)} · {start} - {end}</p>'
                                f'<div class="sleep-track">{spans}</div>')
                if bars:
                    result.append(raw('<div class="sleep-chart">' + "".join(bars)
                                      + '<div class="sleep-axis"><span>00:00</span><span>12:00</span>'
                                      '<span>24:00</span></div></div>'))
                result.append(block)
            elif len(labels) == 3 and labels[0] == "日期" and labels[2] == "单位":
                rows = [row for body in block["c"][4] for row in body[3]]
                values = []
                for row in rows:
                    cells = [text(cell[4]).strip() for cell in row[1]]
                    if len(cells) == 3:
                        values.append(cells)
                numeric = [float(v[1]) for v in values if re.fullmatch(r"\d+(?:\.\d+)?", v[1])]
                if numeric and len({v[2] for v in values if v[1]}) == 1:
                    maximum = max(numeric) or 1
                    bars = []
                    for date, value, unit in values:
                        if not re.fullmatch(r"\d+(?:\.\d+)?", value):
                            continue
                        width = float(value) / maximum * 100
                        bars.append(
                            f'<div class="trend-row"><span>{html.escape(date)}</span>'
                            f'<div class="trend-track"><i style="width:{width:.2f}%"></i></div>'
                            f'<b>{html.escape(value)} {html.escape(unit)}</b></div>')
                    result.append(raw('<div class="trend-chart">' + "".join(bars) + "</div>"))
                result.append(block)
            else:
                result.append(block)
        else:
            result.append(block)
        i += 1
    return result


STYLE = """
@page {
  margin: 18mm 19mm 20mm;
  @top-right { content: "DAILY JOURNAL"; font-family: "Diary Sans";
               font-size: 7pt; color: #25786f; letter-spacing: 0; }
  @bottom-center { content: counter(page); color: #25786f; font-size: 8pt; }
}
html { color: #263432; font-size: 10.5pt; line-height: 1.8; letter-spacing: 0; }
h1 { text-align: left; font-size: 23pt; color: #226f67;
     margin: 1mm 0 8mm; padding-bottom: 4mm; border-bottom: 3pt solid #e29270; }
h2 { font-size: 15pt; color: #226f67; border-left: 3pt solid #e29270;
     padding-left: 3mm; margin: 7mm 0 3mm; }
h3 { color: #a75340; font-size: 11.5pt; }
p { margin-bottom: 3.5mm; }
table { font-size: 8.5pt; line-height: 1.6; table-layout: fixed; }
th, td { border: 0; border-bottom: .4pt solid #dce5e1; overflow-wrap: anywhere;
         padding: 2.5mm 2mm; }
th { background: #e9f3ef; color: #226f67; }
tr:nth-child(even) td { background: #f6f8f7; }
th:first-child, td:first-child { width: auto; white-space: normal; }
.timeline table { font-size: 9pt; }
.timeline th:first-child, .timeline td:first-child { width: 21mm; color: #a75340; }
.timeline th:nth-child(2), .timeline td:nth-child(2) { width: 26mm; }
.timeline th:nth-child(3), .timeline td:nth-child(3) { width: 24mm; }
.timeline td:first-child { border-left: 2pt solid #73a99d; padding-left: 3mm; }
.source-table th:first-child, .source-table td:first-child { width: 25mm; }
.source-table th:nth-child(2), .source-table td:nth-child(2) { width: 26mm; }
.health-metrics { border-top: 2pt solid #d4a542; margin: 4mm 0; }
.health-metrics td:nth-child(2) { color: #226f67; font-size: 15pt; font-weight: bold; }
.health-metrics td:first-child { width: 30mm; }
.health-metrics td:nth-child(2) { width: 30mm; }
img { max-height: 100mm; margin: 3mm auto; }
.diary-photo { break-inside: avoid; margin: 4mm 0; }
.diary-photo p { text-indent: 0; text-align: center; margin: 0; }
.diary-photo p + p { font-family: "Diary Sans"; font-size: 8.5pt; color: #687872;
                    padding: 2mm 1mm; }
.photo-board { display: flex; flex-wrap: wrap; justify-content: space-between;
               padding: 5mm 2mm; margin: 4mm 0; break-inside: avoid; }
.photo-board .diary-photo { width: 45%; margin: 2mm 0 5mm; padding: 2mm;
                           background: white; border: .5pt solid #d6ded9;
                           box-shadow: 1mm 1mm 2mm #d7ddda; transform: rotate(-2deg); }
.photo-board .diary-photo:nth-child(even) { transform: rotate(2deg); }
.photo-board .diary-photo img { width: 100%; height: 52mm; object-fit: contain; margin: 0; }
blockquote { border-color: #d4a542; color: #52665e; }
.trend-chart { margin: 4mm 0; padding: 3mm 0; break-inside: avoid; }
.trend-row { display: flex; align-items: center; margin: 2mm 0;
             font-family: "Diary Sans"; font-size: 8pt; }
.trend-row span { width: 29mm; }
.trend-row b { width: 28mm; text-align: right; font-weight: normal; }
.trend-track { width: 100mm; background: #edf1ee; height: 3mm; }
.trend-track i { display: block; background: #3c978c; height: 3mm; }
.trend-row:nth-child(even) i { background: #d68b68; }
.sleep-chart { break-inside: avoid; margin: 4mm 0; font-family: "Diary Sans"; font-size: 8.5pt; }
.sleep-chart p { text-indent: 0; margin: 0 0 2mm; }
.sleep-track { position: relative; height: 5mm; background: #ecf0f3; }
.sleep-track i { position: absolute; top: 0; height: 5mm; background: #678baf; }
.sleep-axis { display: flex; justify-content: space-between; font-size: 7pt; color: #647873; }
"""
