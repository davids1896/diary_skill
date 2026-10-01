#!/usr/bin/env python3
"""Generate and verify a Chinese diary PDF from Markdown."""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


PANDOC = os.environ.get("DIARY_PANDOC", "pandoc")
WEASYPRINT = os.environ.get("DIARY_WEASYPRINT", "weasyprint")
NOTO_SERIF = Path(os.environ.get(
    "DIARY_NOTO_SERIF", "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc"
)).expanduser().resolve()
NOTO_SANS = Path(os.environ.get(
    "DIARY_NOTO_SANS", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
)).expanduser().resolve()


def run(command: list[str], *, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=text,
    )


def require_tools() -> None:
    required = [NOTO_SERIF, NOTO_SANS]
    missing = [str(path) for path in required if not path.exists()]
    for command in (PANDOC, WEASYPRINT, "pdfinfo", "pdffonts", "pdftotext", "pdftoppm"):
        if shutil.which(command) is None:
            missing.append(command)
    if missing:
        raise RuntimeError("Missing PDF dependencies: " + ", ".join(missing))


def markdown_to_html(source: Path) -> str:
    fragment = run(
        [
            str(PANDOC),
            "--from=gfm-raw_html",
            "--to=html5",
            "--wrap=none",
            str(source),
        ]
    ).stdout
    # Refuse external resources and filesystem escapes before the renderer runs.
    from html.parser import HTMLParser
    from urllib.parse import unquote, urlparse

    class ResourceCheck(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag != "img":
                return
            for name, value in attrs:
                if name != "src" or not value:
                    continue
                parsed = urlparse(value)
                if parsed.scheme not in ("", "file") or parsed.netloc:
                    raise RuntimeError("Network image resources are not allowed")
                path = Path(unquote(parsed.path))
                resolved = (source.parent / path).resolve()
                if not resolved.is_relative_to(source.parent):
                    raise RuntimeError("Image is outside the diary directory")
                if resolved.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
                    raise RuntimeError("Only local PNG/JPEG/WebP images are allowed")
                if not resolved.is_file():
                    raise RuntimeError("Diary image does not exist")

    ResourceCheck().feed(fragment)
    title_match = re.search(r"<h1[^>]*>(.*?)</h1>", fragment, flags=re.DOTALL)
    title = re.sub(r"<[^>]+>", "", title_match.group(1)) if title_match else source.stem
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
@font-face {{
  font-family: "Diary Serif";
  src: url("file://{NOTO_SERIF}");
  font-weight: 400;
}}
@font-face {{
  font-family: "Diary Sans";
  src: url("file://{NOTO_SANS}");
  font-weight: 400 900;
}}
@page {{
  size: A4;
  margin: 22mm 24mm 23mm;
  @bottom-center {{
    content: counter(page);
    font-family: "Diary Sans";
    font-size: 8.5pt;
    color: #777;
  }}
}}
html {{
  font-family: "Diary Serif", serif;
  color: #242424;
  font-size: 11.5pt;
  line-height: 1.9;
}}
body {{
  margin: 0;
}}
h1, h2, h3 {{
  font-family: "Diary Sans", sans-serif;
  page-break-after: avoid;
  color: #171717;
}}
h1 {{
  margin: 0 0 12mm;
  text-align: center;
  font-size: 20pt;
  line-height: 1.45;
}}
h2 {{
  margin: 8mm 0 3mm;
  font-size: 15pt;
}}
h3 {{
  margin: 6mm 0 2mm;
  font-size: 12.5pt;
}}
p {{
  margin: 0 0 4.5mm;
  text-align: justify;
  text-indent: 2em;
  orphans: 2;
  widows: 2;
}}
li p, blockquote p {{
  text-indent: 0;
}}
ul, ol {{
  margin: 0 0 4.5mm;
  padding-left: 2em;
}}
table {{
  width: 100%;
  margin: 3mm 0 5mm;
  border-collapse: collapse;
  font-family: "Diary Sans", sans-serif;
  font-size: 9.5pt;
  line-height: 1.55;
}}
thead {{
  display: table-header-group;
}}
tr {{
  page-break-inside: avoid;
}}
th, td {{
  padding: 2.2mm 2.5mm;
  border: 0.35pt solid #b8b8b8;
  text-align: left;
  vertical-align: top;
}}
th {{
  background: #f1f1f1;
  font-weight: 700;
}}
th:first-child, td:first-child {{
  width: 27mm;
  white-space: nowrap;
}}
blockquote {{
  margin: 4mm 0;
  padding-left: 1em;
  border-left: 2px solid #aaa;
  color: #4b4b4b;
}}
code {{
  font-family: "Diary Sans", sans-serif;
  font-size: 0.92em;
}}
img {{
  display: block;
  max-width: 100%;
  max-height: 180mm;
  margin: 4mm auto;
  object-fit: contain;
}}
</style>
</head>
<body>
{fragment}
</body>
</html>
"""


def verify_pdf(pdf: Path, source: Path) -> None:
    info = run(["pdfinfo", str(pdf)]).stdout
    pages_match = re.search(r"^Pages:\s+(\d+)$", info, flags=re.MULTILINE)
    if not pages_match or int(pages_match.group(1)) < 1:
        raise RuntimeError("pdfinfo did not report a valid page count")
    if not re.search(r"^Page size:\s+595\.27\d* x 841\.89\d* pts", info, re.MULTILINE):
        raise RuntimeError("PDF is not A4")

    fonts = run(["pdffonts", str(pdf)]).stdout
    font_rows = [
        line.split()
        for line in fonts.splitlines()[2:]
        if line.strip() and not set(line.strip()) <= {"-"}
    ]
    if not font_rows:
        raise RuntimeError("PDF contains no fonts")
    not_embedded = [
        row[0] for row in font_rows if len(row) < 6 or row[-5] != "yes"
    ]
    if not_embedded:
        raise RuntimeError("PDF contains unembedded fonts: " + ", ".join(not_embedded))

    extracted = run(["pdftotext", str(pdf), "-"]).stdout
    source_text = source.read_text(encoding="utf-8")
    for heading in ("工作记录", "日记"):
        if not re.search(rf"^##\s+{heading}\s*$", source_text, re.MULTILINE):
            raise RuntimeError(f"Markdown is missing section: {heading}")
        if heading not in extracted:
            raise RuntimeError(f"PDF is missing section: {heading}")
    source_plain = re.sub(r"(?m)^#{1,6}\s+", "", source_text)
    # PDF renderers show a Markdown link's label, not its potentially long URL.
    source_plain = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", source_plain)
    source_chars = re.sub(r"\s+", "", source_plain)
    extracted_chars = re.sub(r"\s+", "", extracted)
    if len(extracted_chars) < max(40, int(len(source_chars) * 0.85)):
        raise RuntimeError("Extracted PDF text is unexpectedly incomplete")
    for marker in re.findall(r"[\u4e00-\u9fff]{4,}", source_plain)[:3]:
        if marker not in extracted:
            raise RuntimeError(f"Extracted PDF text is missing marker: {marker}")

    with tempfile.TemporaryDirectory(prefix="diary-pdf-render-") as temp_dir:
        prefix = Path(temp_dir) / "page"
        run(["pdftoppm", "-f", "1", "-l", "1", "-r", "120", str(pdf), str(prefix)])
        ppm_files = list(Path(temp_dir).glob("page-*.ppm"))
        if not ppm_files:
            raise RuntimeError("PDF page rendering produced no image")
        data = ppm_files[0].read_bytes()
        header_end = 0
        newline_count = 0
        for index, byte in enumerate(data):
            if byte == 10:
                newline_count += 1
                if newline_count == 3:
                    header_end = index + 1
                    break
        pixels = data[header_end:]
        if not pixels:
            raise RuntimeError("Rendered PDF page contains no pixels")
        nonwhite = sum(value < 245 for value in pixels)
        if nonwhite / len(pixels) < 0.002:
            raise RuntimeError("Rendered PDF page appears blank")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Diary Markdown file")
    parser.add_argument("-o", "--output", type=Path, help="Output PDF path")
    parser.add_argument("--verify-only", action="store_true", help="Verify an existing PDF")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    output = (args.output or source.with_suffix(".pdf")).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)

    require_tools()
    if args.verify_only:
        verify_pdf(output, source)
        print(output)
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    html_text = markdown_to_html(source)
    with tempfile.TemporaryDirectory(prefix="diary-pdf-") as temp_dir:
        html_path = Path(temp_dir) / "diary.html"
        html_path.write_text(html_text, encoding="utf-8")
        candidate = Path(temp_dir) / "diary.pdf"
        run(
            [
                str(WEASYPRINT),
                "--base-url",
                str(source.parent),
                str(html_path),
                str(candidate),
            ]
        )

        verify_pdf(candidate, source)
        # Preserve the last good PDF if rendering or validation fails.
        fd, staged = tempfile.mkstemp(dir=output.parent, suffix=".pdf")
        os.close(fd)
        try:
            shutil.copyfile(candidate, staged)
            os.replace(staged, output)
        finally:
            Path(staged).unlink(missing_ok=True)
    print(output)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"PDF generation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
