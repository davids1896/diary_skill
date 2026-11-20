"""Read-only diary library and version-matched PDF companion worker.

The hosting handler must implement authorized(); this module never supplies an
anonymous server. Original source files are evidence, not executable input.
"""
from __future__ import annotations

from collections import defaultdict
import hashlib
import html
from html.parser import HTMLParser
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import unquote, urlsplit

DATE = r"20\d{2}-\d{2}-\d{2}"
NAME = re.compile(DATE + r"(?:-jimi-supplement)?$")


def write_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode())
    tmp.replace(path)


class SafeHTML(HTMLParser):
    tags = set("p br h1 h2 h3 h4 h5 h6 ul ol li blockquote pre code strong em del hr table thead tbody tr th td a img sup sub span div section figure figcaption details summary".split())

    def __init__(self, asset_prefix):
        super().__init__(convert_charrefs=False)
        self.parts, self.asset_prefix = [], asset_prefix

    def handle_starttag(self, tag, attrs):
        if tag not in self.tags:
            return
        clean = []
        for key, value in attrs:
            if value is None:
                continue
            if key in {"id", "title", "alt", "colspan", "rowspan"}:
                clean.append((key, value))
            elif tag == "a" and key == "href":
                if urlsplit(value).scheme in {"http", "https", "mailto"} or value.startswith("#"):
                    clean.extend([(key, value), ("rel", "noreferrer noopener")])
            elif tag == "img" and key == "src" and re.fullmatch(r"assets/[a-f0-9]{64}\.(?:png|jpg|jpeg|webp)", value):
                clean.extend([("src", self.asset_prefix + value[7:]), ("loading", "lazy")])
        self.parts.append("<" + tag + "".join(" " + k + '=\"' + html.escape(v, quote=True) + '\"' for k, v in clean) + ">")

    def handle_endtag(self, tag):
        if tag in self.tags and tag not in {"br", "img", "hr"}:
            self.parts.append("</" + tag + ">")

    def handle_data(self, data):
        self.parts.append(html.escape(data))

    def handle_entityref(self, name):
        self.parts.append("&" + name + ";")

    def handle_charref(self, name):
        self.parts.append("&#" + name + ";")


class Library:
    def __init__(self, config):
        self.config = config
        self.cache = Path(config["cache"]).resolve()
        self.cache.mkdir(parents=True, exist_ok=True)
        self.assets = Path(config["assets"]).resolve()
        self.roots = {k: Path(v).resolve() for k, v in config["roots"].items()}
        self.allowed = [Path(p).resolve() for p in config["image_roots"]]
        self.state_path = self.cache / "state.json"
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.rows, self.progress = [], {"running": True, "done": 0, "total": 0}
        self.lock, self.scan_lock = threading.RLock(), threading.Lock()
        self.gen = None
        self.error = None
        self.temp = self.cache / "temp"
        self.temp.mkdir(exist_ok=True)

    def load_generator(self):
        if self.gen is None:
            spec = importlib.util.spec_from_file_location("diary_library_pdf", self.config["generator"])
            self.gen = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.gen)
        return self.gen

    def discover(self):
        rows = []
        for kind, root in self.roots.items():
            files = root.glob("*/*/*.md") if kind == "archive" else root.glob("*.md")
            for p in files:
                if not NAME.fullmatch(p.stem) or not p.resolve().is_relative_to(root):
                    continue
                text = p.read_text(encoding="utf-8")
                if kind != "archive" and ("## 工作记录" not in text or "## 日记" not in text):
                    continue
                ident = hashlib.sha256((kind + ":" + str(p.relative_to(root))).encode()).hexdigest()[:20]
                supplement = p.stem.endswith("-jimi-supplement")
                label = "录音补充草稿" if supplement else "日记稿" if kind == "archive" else "工作区草稿"
                preview = re.split(r"(?m)^## 日记\s*$", text, maxsplit=1)
                if len(preview) == 1:
                    preview = re.split(r"(?m)^## 工作记录\s*$", text, maxsplit=1)
                paragraphs = [re.sub(r"[*_`]", "", s.strip()) for s in preview[-1].splitlines()
                              if s.strip() and not s.lstrip().startswith(("#", "|", "!", ">", "<!--", "草稿", "Asia/Shanghai"))]
                rows.append({"id": ident, "date": p.name[:10], "kind": kind,
                             "label": label, "supplement": supplement,
                             "path": str(p), "source_sha": hashlib.sha256(text.encode()).hexdigest(),
                             "updated": p.stat().st_mtime, "title": p.name[:10] + " · " + label,
                             "excerpt": " ".join(paragraphs[:2])[:170],
                             "draft": bool(re.search(r"草稿|初稿|未确认|待本人核对", text[:500])), "ready": False})
        return sorted(rows, key=lambda r: (r["date"], r["supplement"], r["kind"] == "archive"), reverse=True)

    def _image(self, source, location):
        parsed = urlsplit(location)
        if parsed.scheme not in {"", "file"} or parsed.netloc:
            raise ValueError("Only approved local diary pictures can be included")
        path = (source.parent / unquote(parsed.path)).resolve()
        if not any(path.is_relative_to(root) for root in self.allowed):
            raise ValueError("Picture is outside the configured evidence roots")
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.is_file():
            raise ValueError("Referenced diary picture is unavailable")
        return path

    def _current(self, row, previous):
        if not previous or previous.get("source_sha") != row["source_sha"]:
            return False
        for a in previous.get("images", []):
            path = self._image(Path(row["path"]), a["source"])
            stat = path.stat()
            if stat.st_size != a["bytes"] or stat.st_mtime_ns != a["mtime_ns"]:
                return False
        directory = self.cache / row["id"] / previous["revision"]
        return all((directory / p).is_file() for p in ["diary.md", "diary.pdf", "body.html"])

    def published_baseline_matches(self, source, pictures):
        reference = self.config.get("validated_archive_commit", "")
        root = self.roots.get("archive")
        if root is None or not re.fullmatch(r"[a-f0-9]{40}", reference):
            return False
        try:
            paths = [str(p.relative_to(root)) for p in [source, source.with_suffix(".pdf"), *[Path(a["source"]) for a in pictures]]]
        except ValueError:
            return False
        tracked = subprocess.run(["git", "-C", str(root), "ls-files", "--error-unmatch", "--", *paths], capture_output=True)
        same = subprocess.run(["git", "-C", str(root), "diff", "--quiet", reference, "--", *paths], capture_output=True)
        return tracked.returncode == 0 and same.returncode == 0

    def prepare(self, row):
        gen = self.load_generator()
        source = Path(row["path"])
        document = json.loads(gen.run([str(gen.PANDOC), "--from=gfm-raw_html", "--to=json"], input_text=gen.authored_markdown(source)).stdout)
        pictures = []
        def visit(node):
            if isinstance(node, list):
                for child in node:
                    visit(child)
            elif isinstance(node, dict):
                if node.get("t") == "Image":
                    url = node["c"][-1][0]
                    path = self._image(source, url)
                    stat = path.stat()
                    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                    name = checksum + path.suffix.lower()
                    pictures.append({"source": str(path), "name": name, "sha": checksum,
                                     "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns})
                    node["c"][-1][0] = "assets/" + name
                for child in node.values():
                    visit(child)
        visit(document)
        revision = hashlib.sha256((row["source_sha"] + "".join(a["sha"] for a in pictures)).encode()).hexdigest()
        directory = self.cache / row["id"] / revision
        (directory / "assets").mkdir(parents=True, exist_ok=True)
        for a in pictures:
            dest = directory / "assets" / a["name"]
            if not dest.exists():
                shutil.copyfile(a["source"], dest)
        md = directory / "diary.md"
        text = gen.run([str(gen.PANDOC), "--from=json", "--to=gfm", "--wrap=none"], input_text=json.dumps(document)).stdout
        write_atomic(md, text)
        gen.verify_content_reference(md, source)
        pdf = directory / "diary.pdf"
        existing = source.with_suffix(".pdf")
        if not pdf.exists():
            # Baseline archived PDFs already exist; verify them against this revision.
            if existing.is_file() and existing.stat().st_mtime >= source.stat().st_mtime:
                if row["kind"] != "archive" or not self.published_baseline_matches(source, pictures):
                    try:
                        gen.verify_pdf(existing, md)
                    except (RuntimeError, subprocess.SubprocessError):
                        existing = None
            else:
                existing = None
            if existing is not None:
                shutil.copyfile(existing, pdf)
            else:
                proc = subprocess.run(["python3", self.config["generator"], str(md)],
                                      env={**os.environ, "TMPDIR": str(self.temp)},
                                      capture_output=True, text=True, timeout=180)
                if proc.returncode:
                    raise RuntimeError(proc.stderr[-600:])
        fragment = gen.run([str(gen.PANDOC), "--from=gfm-raw_html", "--to=html5", "--wrap=none"], input_text=text).stdout
        safe = SafeHTML("/diary/api/entries/" + row["id"] + "/assets/")
        safe.feed(fragment)
        write_atomic(directory / "body.html", "".join(safe.parts))
        # Authored archive files retain their conventional adjacent PDF as well.
        if row["kind"] == "archive" and (not source.with_suffix(".pdf").exists() or
                source.with_suffix(".pdf").read_bytes() != pdf.read_bytes()):
            tmp = source.with_suffix(".pdf.library-tmp")
            shutil.copyfile(pdf, tmp)
            tmp.replace(source.with_suffix(".pdf"))
        return {"source_sha": row["source_sha"], "images": pictures, "revision": revision,
                "pdf_bytes": pdf.stat().st_size, "checked_at": time.time()}

    def refresh(self):
        if not self.scan_lock.acquire(blocking=False):
            return
        try:
            rows = self.discover()
            with self.lock:
                self.rows = rows
                self.progress = {"running": True, "done": 0, "total": len(rows)}
            for row in rows:
                try:
                    previous = self.state.get(row["id"])
                    if not self._current(row, previous):
                        previous = self.prepare(row)
                        self.state[row["id"]] = previous
                        write_atomic(self.state_path, json.dumps(self.state, ensure_ascii=False))
                    row.update(ready=True, revision=previous["revision"])
                except Exception as e:
                    row.update(ready=False, error="PDF暂未生成，请稍后重试")
                    # A bounded private diagnostic is not returned through the API.
                    self.error = {"entry": row["id"], "error": str(e)[-700:]}
                    write_atomic(self.cache / "last-error.json", json.dumps(self.error, ensure_ascii=False))
                with self.lock:
                    self.progress["done"] += 1
            with self.lock:
                self.progress["running"] = False
        finally:
            self.scan_lock.release()

    def start(self):
        def run():
            while True:
                try:
                    self.refresh()
                except Exception as e:
                    self.error = {"error": str(e)[-500:]}
                time.sleep(self.config.get("interval", 60))
        threading.Thread(target=run, daemon=True, name="diary-pdf-companions").start()

    def index(self, search=""):
        with self.lock:
            rows, progress = list(self.rows), dict(self.progress)
        result = []
        for r in rows:
            if search and search.lower() not in (r["date"] + r["title"] + r["excerpt"]).lower():
                if search.lower() not in Path(r["path"]).read_text().lower():
                    continue
            result.append({**{k: r[k] for k in ["id", "date", "label", "title", "excerpt", "draft", "ready", "supplement"]}, "revision": r.get("revision")})
        return {"entries": result, "progress": progress, "days": len({r["date"] for r in rows})}

    def handle(self, h, path, query):
        if not callable(getattr(h, "authorized", None)) or not h.authorized():
            return self.reply(h, 403, {"error": "请使用本人Tailscale账号访问"})
        if h.command not in {"GET", "HEAD"}:
            return self.reply(h, 405, {"error": "日记页面只提供阅读与下载"})
        if path in {"/diary", "/diary/"}:
            return self.file(h, self.assets / "index.html", "text/html; charset=utf-8")
        if path in {"/diary/app.js", "/diary/app.css"}:
            return self.file(h, self.assets / path.rsplit("/", 1)[1], "text/javascript; charset=utf-8" if path.endswith("js") else "text/css; charset=utf-8")
        if path == "/diary/api/index":
            return self.reply(h, 200, self.index(query.get("q", [""])[0][:200]))
        match = re.fullmatch(r"/diary/api/entries/([a-f0-9]{20})/(content|pdf|markdown|assets/([a-f0-9]{64}\.(?:jpg|jpeg|png|webp)))", path)
        if not match:
            return self.reply(h, 404, {"error": "没有找到日记"})
        ident, kind, image = match.groups()
        with self.lock:
            row = next((dict(r) for r in self.rows if r["id"] == ident), None)
        if row is None or not row.get("ready"):
            return self.reply(h, 404, {"error": "这份日记的PDF正在准备中"})
        directory = self.cache / ident / row["revision"]
        if kind == "content":
            return self.reply(h, 200, {"html": (directory / "body.html").read_text(), "date": row["date"], "label": row["label"]})
        if kind == "pdf":
            return self.file(h, directory / "diary.pdf", "application/pdf", row["date"] + ("-supplement" if row["supplement"] else "") + ".pdf", inline=True)
        if kind == "markdown":
            return self.file(h, directory / "diary.md", "text/markdown; charset=utf-8", row["date"] + ".md")
        return self.file(h, directory / "assets" / image, mimetypes.guess_type(image)[0])

    def reply(self, h, code, value):
        data = json.dumps(value, ensure_ascii=False).encode()
        self.headers(h, code, "application/json; charset=utf-8", len(data))
        if h.command != "HEAD":
            h.wfile.write(data)

    def headers(self, h, status, kind, size, filename=None, inline=False, extra=None):
        h.send_response(status)
        for key, value in {"Content-Type": kind, "Content-Length": str(size), "Cache-Control": "no-store",
                           "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                           "X-Frame-Options": "SAMEORIGIN", "Content-Security-Policy":
                           "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; object-src 'none'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"}.items():
            h.send_header(key, value)
        if filename:
            h.send_header("Content-Disposition", ("inline" if inline else "attachment") + '; filename="' + filename + '"')
        for key, value in (extra or {}).items():
            h.send_header(key, value)
        h.end_headers()

    def file(self, h, path, kind, filename=None, inline=False):
        if not path.is_file() or not path.resolve().is_relative_to(self.cache if path.is_relative_to(self.cache) else self.assets):
            return self.reply(h, 404, {"error": "文件暂不可用"})
        size = path.stat().st_size
        start, end, status = 0, size - 1, 200
        if h.headers.get("Range") and kind == "application/pdf":
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", h.headers["Range"])
            if not match:
                return self.reply(h, 416, {"error": "无效文件范围"})
            start, end = int(match[1]), min(int(match[2]) if match[2] else end, end)
            if start > end:
                return self.reply(h, 416, {"error": "无效文件范围"})
            status = 206
        extra = {"Accept-Ranges": "bytes"}
        if status == 206:
            extra["Content-Range"] = f"bytes {start}-{end}/{size}"
        self.headers(h, status, kind, end - start + 1, filename, inline, extra)
        if h.command != "HEAD":
            with path.open("rb") as f:
                f.seek(start)
                remaining = end - start + 1
                while remaining:
                    data = f.read(min(131072, remaining))
                    if not data:
                        break
                    h.wfile.write(data)
                    remaining -= len(data)
