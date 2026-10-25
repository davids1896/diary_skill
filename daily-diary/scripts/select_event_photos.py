#!/usr/bin/env python3
"""Select reviewed photo candidates by event coverage, then visual quality.

Input is a JSON list: id, event, path, reviewed, score, optional duplicate_group.
Scores and event assignments come from visual review, not filename inference.
"""
import argparse
import json
from pathlib import Path


def select(candidates, limit=12):
    if not isinstance(limit, int) or limit < 0:
        raise ValueError("limit must be a nonnegative integer")
    eligible = []
    ids = set()
    for item in candidates:
        if item.get("reviewed") is not True:
            continue
        identity = item["id"]
        if identity in ids:
            raise ValueError("Duplicate candidate id")
        ids.add(identity)
        if not item.get("event") or not Path(item["path"]).is_file():
            raise ValueError("Reviewed candidates require an event and a local image")
        eligible.append(item)
    eligible.sort(key=lambda row: (-float(row.get("score", 0)), row["id"]))
    chosen, events, duplicates, paths = [], set(), set(), set()
    # First pass covers distinct events; second pass can fill remaining slots.
    for coverage_only in (True, False):
        for item in eligible:
            if len(chosen) >= limit:
                return chosen
            group = item.get("duplicate_group") or item["id"]
            path = str(Path(item["path"]).resolve())
            if group in duplicates or path in paths or (coverage_only and item["event"] in events):
                continue
            chosen.append(item)
            duplicates.add(group)
            paths.add(path)
            events.add(item["event"])
    return chosen


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(select(json.loads(args.candidates.read_text()), args.limit),
                     ensure_ascii=False, indent=2))
