import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
from generate_diary_pdf import visible_markdown_text

class VisibleTextTests(unittest.TestCase):
    def test_sparse_table_counts_content_instead_of_separators(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"diary.md"
            p.write_text("## 日记\n\n| 时间 | 地点 | 事情 |\n|"+"-"*120+"|"+"-"*120+"|"+"-"*120+"|\n| 12:10 | | 吃饭 |\n")
            text=visible_markdown_text(p)
            for marker in ["日记","时间","地点","事情","12:10","吃饭"]: self.assertIn(marker,text)
            self.assertNotIn("---",text)
            self.assertLess(len(text.replace(" ","")),80)
    def test_links_and_code_preserve_displayed_content(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"diary.md"
            p.write_text("[付款记录](https://example.invalid/"+"x"*500+")\n\n```text\n实际支付 123 元\n```\n")
            text=visible_markdown_text(p)
            self.assertIn("付款记录",text);self.assertIn("实际支付 123 元",text)
            self.assertNotIn("https://",text)
