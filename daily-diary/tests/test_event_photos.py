"""Invented candidate metadata; no user media fixtures."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from select_event_photos import select


class EventPhotoTests(unittest.TestCase):
    def test_events_before_more_of_same_event_and_no_unreviewed(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates = []
            for name, event, score in [("a", "morning", 100), ("b", "morning", 99),
                                       ("c", "evening", 50), ("d", "night", 10)]:
                path = Path(tmp) / f"{name}.jpg"
                path.touch()
                candidates.append(dict(id=name, event=event, path=str(path),
                                       reviewed=name != "d", score=score))
            self.assertEqual([row["id"] for row in select(candidates, 2)], ["a", "c"])
            self.assertEqual(len(select(candidates, 12)), 3)
            self.assertEqual(select(candidates, 0), [])
            candidates[1]["duplicate_group"] = "burst"
            candidates[0]["duplicate_group"] = "burst"
            self.assertEqual([row["id"] for row in select(candidates, 12)], ["a", "c"])

    def test_repeated_path_is_not_another_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.jpg"
            path.touch()
            rows = [dict(id=str(i), event=str(i), path=str(path), reviewed=True) for i in range(2)]
            self.assertEqual(len(select(rows)), 1)
