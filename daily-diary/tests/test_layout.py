"""Structural layout tests using invented labels and values only."""
import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from generate_diary_pdf import markdown_to_html


class LayoutTests(unittest.TestCase):
    def render(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.md"
            path.write_text(text)
            (Path(tmp) / "a.jpg").touch()
            (Path(tmp) / "b.jpg").touch()
            return markdown_to_html(path)

    def test_board_keeps_captions(self):
        result = self.render("![A](a.jpg)\n\n*Caption A*\n\n![B](b.jpg)\n\n*Caption B*\n\nAfter.")
        self.assertIn('<div class="photo-board">', result)
        self.assertIn("Caption A", result)
        self.assertIn("Caption B", result)
        self.assertIn("After.", result)

    def test_timeline_and_people_column(self):
        result = self.render("| 时间 | 地点 | 人 | 事情 |\n|---|---|---|---|\n| 09:00 | | | 测试 |")
        self.assertIn('<div class="timeline">', result)
        self.assertIn("<th>人</th>", result)
        self.assertIn("测试", result)

    def test_trend_missing_is_not_zero(self):
        result = self.render("| 日期 | 步数 | 单位 |\n|---|---|---|\n"
                             "| 01 | 100 | 步 |\n| 02 | | 步 |\n| 03 | 200 | 步 |")
        self.assertEqual(result.count('<div class="trend-row">'), 2)
        self.assertIn("width:50.00%", result)
        self.assertIn("width:100.00%", result)

    def test_sleep_keeps_record_type_and_midnight_gap(self):
        result = self.render("| 项目 | 开始 | 结束 | 类别 |\n|---|---|---|---|\n"
                             "| 卧床 | 23:00 | 07:00 | In Bed |")
        self.assertIn('<div class="sleep-chart">', result)
        self.assertIn("In Bed", result)
        self.assertIn("left:95.83%;width:4.17%", result)
