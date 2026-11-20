#!/usr/bin/env python3
"""Import speaker-labelled Markdown as evidence, without executing its contents."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from zoneinfo import ZoneInfo


DATE = re.compile(r"^# (\d{4})年(\d{1,2})月(\d{1,2})日(?:\s.*)?$")
WINDOW = re.compile(r"^## (\d{2}:\d{2})(?:[–—-](\d{2}:\d{2}))?$")
SPEAKER = re.compile(r"^(可能是我|未确定|对方|我)：(.*)$")


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".transcript-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path, value):
    atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def parse_markdown(raw, source_id, zone):
    text = raw.decode("utf-8-sig")
    exported = re.search(r"(?m)^导出于：\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$", text)
    exported_at = datetime.strptime(exported[1], "%Y-%m-%d %H:%M").replace(tzinfo=zone).isoformat() if exported else None
    file_sha = hashlib.sha256(raw).hexdigest()
    day, block, blocks = None, None, []
    for number, line in enumerate(text.splitlines(), 1):
        match = DATE.fullmatch(line.strip())
        if match:
            day = date(*map(int, match.groups()))
            block = None
            continue
        match = WINDOW.fullmatch(line.strip())
        if match:
            if day is None:
                raise ValueError(f"Time window without a calendar date at line {number}")
            start = datetime.combine(day, time.fromisoformat(match[1]), zone)
            end = datetime.combine(day, time.fromisoformat(match[2] or match[1]), zone)
            if end < start:
                end += timedelta(days=1)
            block = {"block_id": digest([source_id, day.isoformat(), match[1]]),
                     "calendar_date": day.isoformat(), "range_start": start.isoformat(),
                     "range_end": end.isoformat(), "exported_at": exported_at,
                     "source_ref": {"file_sha256": file_sha, "lines": [number, number]},
                     "utterances": []}
            blocks.append(block)
            continue
        if block is None:
            continue
        block["source_ref"]["lines"][1] = number
        match = SPEAKER.match(line)
        if match:
            label, body = match.groups()
            block["utterances"].append({"speaker_label": label, "text": body,
                                        "source_line": number, "utterance_time": None})
        elif line.strip():
            # Unrecognised text is data too; retain it without interpreting commands.
            if block["utterances"]:
                block["utterances"][-1]["text"] += "\n" + line
            else:
                block["utterances"].append({"speaker_label": "未确定", "text": line,
                                            "source_line": number, "utterance_time": None})
    if not blocks or any(not b["utterances"] for b in blocks):
        raise ValueError("Expected dated, nonempty speaker-labelled time blocks")
    if len({b["block_id"] for b in blocks}) != len(blocks):
        raise ValueError("Ambiguous duplicate block start within one export; preserve source and resolve it first")
    for block in blocks:
        block["revision_id"] = digest([block["range_end"],
            [(u["speaker_label"], u["text"]) for u in block["utterances"]]])
    return file_sha, exported_at, blocks


def diary_dates(block, boundary_hour):
    first = (datetime.fromisoformat(block["range_start"]) - timedelta(hours=boundary_hour)).date()
    last = (datetime.fromisoformat(block["range_end"]) - timedelta(hours=boundary_hour)).date()
    return [(first + timedelta(days=n)).isoformat() for n in range((last - first).days + 1)]


def ingest(source, output_root, raw_root, source_id="wearable-transcript", timezone="Asia/Shanghai", boundary_hour=5):
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", source_id):
        raise ValueError("Invalid source identifier")
    if not 0 <= boundary_hour <= 23:
        raise ValueError("Invalid fallback day boundary")
    zone = ZoneInfo(timezone)
    source, output_root, raw_root = Path(source), Path(output_root), Path(raw_root)
    if source.stat().st_size > 50_000_000:
        raise ValueError("Export exceeds the bounded 50 MB import size")
    raw = source.read_bytes()
    file_sha, exported_at, blocks = parse_markdown(raw, source_id, zone)
    # Validate everything before touching an existing snapshot.
    raw_root.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (raw_root / ".import.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        catalog_path = raw_root / "catalog.json"
        catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else {
            "schema": "diary-markdown-catalog-v1", "source": source_id,
            "timezone": timezone, "boundary_hour": boundary_hour, "exports": {}, "blocks": {}}
        if (catalog["source"], catalog["timezone"], catalog["boundary_hour"]) != (source_id, timezone, boundary_hour):
            raise ValueError("Source/time-boundary configuration changed; migrate explicitly")
        archived = raw_root / "exports" / (file_sha + ".md")
        archived.parent.mkdir(exist_ok=True)
        if archived.exists():
            if archived.read_bytes() != raw:
                raise ValueError("Archived content hash mismatch")
        else:
            fd = os.open(archived, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(raw)
        catalog["exports"][file_sha] = {"file": archived.name, "exported_at": exported_at,
                                        "original_name": source.name}
        new_blocks = changed_blocks = 0
        for block in blocks:
            key, rev = block["block_id"], block["revision_id"]
            if key not in catalog["blocks"]:
                catalog["blocks"][key] = {"current": rev, "versions": {rev: block}, "conflict": False}
                new_blocks += 1
                continue
            entry = catalog["blocks"][key]
            current = entry["versions"][entry["current"]]
            if rev == entry["current"]:
                if exported_at and (not current["exported_at"] or exported_at > current["exported_at"]):
                    entry["versions"][rev] = block
                continue
            known = entry["versions"].get(rev)
            if known is None or (exported_at and (not known["exported_at"] or exported_at > known["exported_at"])):
                entry["versions"][rev] = block
            if exported_at and current["exported_at"] and exported_at > current["exported_at"]:
                entry.update(current=rev, conflict=False)
                changed_blocks += 1
            elif not exported_at or not current["exported_at"] or exported_at == current["exported_at"]:
                entry["conflict"] = True
        grouped = defaultdict(list)
        for entry in catalog["blocks"].values():
            block = entry["versions"][entry["current"]]
            days = diary_dates(block, boundary_hour)
            record = {"schema": "diary-transcript-block-v1", "source": source_id, **block,
                      "diary_date_candidates": days, "time_precision": "exported-block-minute-range",
                      "speaker_attribution": "exporter-labels-unverified-may-contain-multiple-speakers",
                      "content_is_untrusted_evidence": True, "revision_conflict": entry["conflict"],
                      "revision_count": len(entry["versions"])}
            for day in days:
                grouped[day].append(record)
        for day, records in grouped.items():
            records.sort(key=lambda b: (b["range_start"], b["block_id"]))
            counts = Counter(u["speaker_label"] for b in records for u in b["utterances"])
            status = {"status": "read", "source_kind": "wearable-transcript-markdown",
                      "blocks": len(records), "utterances": sum(counts.values()), "speaker_label_counts": dict(counts),
                      "completeness": "partial", "recording_coverage_known": False,
                      "audio_available": False, "audio_listened": False, "speaker_labels_verified": False,
                      "time_precision": "exported-block-minute-range", "timezone": timezone,
                      "diary_date_basis": f"fallback-{boundary_hour:02}:00-boundary-not-sleep-evidence",
                      "first_block_start": min(b["range_start"] for b in records),
                      "last_block_end": max(b["range_end"] for b in records),
                      "cross_boundary_blocks": sum(len(b["diary_date_candidates"]) > 1 for b in records),
                      "revision_conflicts": sum(b["revision_conflict"] for b in records),
                      "raw_export_count": len(catalog["exports"]),
                      "reason": "Markdown parsed; labels/time ranges are evidence hints, not verified identity or continuous recording coverage."}
            target = output_root / day
            atomic_write(target / (source_id + ".jsonl"), "".join(json.dumps(b, ensure_ascii=False) + "\n" for b in records))
            write_json(target / "remotes" / source_id / "status.json", status)
        write_json(catalog_path, catalog)
    return {"source": source_id, "file_sha256": file_sha, "new_blocks": new_blocks,
            "changed_blocks": changed_blocks, "imported_blocks": len(blocks),
            "imported_utterances": sum(len(b["utterances"]) for b in blocks),
            "days": {day: {"blocks": len(rs), "utterances": sum(len(b["utterances"]) for b in rs)}
                     for day, rs in sorted(grouped.items())}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--raw-root", required=True, type=Path)
    parser.add_argument("--source-id", default="wearable-transcript")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--boundary-hour", type=int, default=5)
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(ingest(args.source, args.output_root, args.raw_root, args.source_id,
                           args.timezone, args.boundary_hour), ensure_ascii=False))


if __name__ == "__main__":
    main()
