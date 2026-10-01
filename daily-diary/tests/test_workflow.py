"""Use synthetic material and local Git only; never read private diary data."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts/generate_diary_pdf.py"
PUBLISHER = ROOT / "scripts/publish-diary.sh"
SPEC = importlib.util.spec_from_file_location("diary_pdf", GENERATOR)
PDF_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PDF_MODULE)
SAMPLE = """# 2026-10-01 日常记录

这是明确虚构的工具测试资料，不代表任何真实用户的生活经历。

## 时间线

- 09:00 测试记录表明整理了演示文件，只有这一个可靠时间点。

## 数据说明

本样例只有测试材料，其他来源未读取，不能据此推断没有活动。

## 工作记录

我完成了一份用于验证中文字体和独立章节的演示文档。
结果只是本地测试，不代表线上系统验收。

## 日记

没有真实生活、心情或关系资料，不补写故事，也不把工作记录再摘要一次。
"""


def run(*args, cwd=None, env=None, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check,
                          text=True, capture_output=True)


class PdfTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "2026-10-01.md"
        self.source.write_text(SAMPLE, encoding="utf-8")

    def test_network_image_rejected(self):
        self.source.write_text(SAMPLE + "\n![image](https://example.invalid/private.png)",
                               encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "Network"):
            PDF_MODULE.markdown_to_html(self.source)

    def test_local_escape_rejected(self):
        self.source.write_text(SAMPLE + "\n![image](../outside.png)", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "outside"):
            PDF_MODULE.markdown_to_html(self.source)

    def test_invalid_generation_preserves_existing_pdf(self):
        output = self.source.with_suffix(".pdf")
        output.write_bytes(b"previous good artifact")
        self.source.write_text("# Invalid document\nmissing sections\n", encoding="utf-8")
        result = run("python3", str(GENERATOR), str(self.source), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(output.read_bytes(), b"previous good artifact")


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "diary"
        self.remote = self.root / "remote.git"
        run("git", "init", "--bare", str(self.remote))
        run("git", "init", "-b", "main", str(self.repo))
        run("git", "config", "user.name", "Synthetic Test", cwd=self.repo)
        run("git", "config", "user.email", "test@example.invalid", cwd=self.repo)
        (self.repo / "initial.txt").write_text("initial")
        run("git", "add", "initial.txt", cwd=self.repo)
        run("git", "commit", "-m", "Initial", cwd=self.repo)
        run("git", "remote", "add", "origin", str(self.remote), cwd=self.repo)
        run("git", "push", "-u", "origin", "main", cwd=self.repo)
        self.initial = run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip()
        path = self.repo / "2026/10/2026-10-01.md"
        path.parent.mkdir(parents=True)
        path.write_text(SAMPLE, encoding="utf-8")
        self.env = dict(os.environ, DIARY_REPO=str(self.repo), DIARY_PUBLISH="0")

    def publish(self, date="2026-10-01", check=True):
        return run("bash", str(PUBLISHER), date, env=self.env, check=check)

    def test_validation_publish_and_idempotency(self):
        result = json.loads(self.publish().stdout)
        self.assertEqual(result["status"], "validated")
        self.assertEqual(run("git", "rev-parse", "HEAD", cwd=self.repo).stdout.strip(),
                         self.initial)
        (self.repo / "unrelated.txt").write_text("preserve this staged change")
        run("git", "add", "unrelated.txt", cwd=self.repo)
        self.env["DIARY_PUBLISH"] = "1"
        first = json.loads(self.publish().stdout)
        self.assertEqual(first["status"], "published")
        self.assertTrue(first["changed"])
        files = run("git", "show", "--pretty=", "--name-only", "HEAD", cwd=self.repo).stdout
        self.assertEqual(set(files.split()), {
            "2026/10/2026-10-01.md", "2026/10/2026-10-01.pdf"})
        self.assertIn("unrelated.txt", run("git", "diff", "--cached", "--name-only",
                                        cwd=self.repo).stdout)
        pdf = self.repo / "2026/10/2026-10-01.pdf"
        before = pdf.read_bytes()
        second = json.loads(self.publish().stdout)
        self.assertFalse(second["changed"])
        self.assertEqual(first["commit"], second["commit"])
        self.assertEqual(before, pdf.read_bytes())
        remote_head = run("git", "--git-dir", str(self.remote), "rev-parse", "main").stdout
        self.assertEqual(remote_head.strip(), first["commit"])

    def test_invalid_date(self):
        self.assertNotEqual(self.publish("2026-02-30", check=False).returncode, 0)

    def test_unrelated_unpushed_commit_blocked(self):
        run("git", "commit", "--allow-empty", "-m", "Unrelated private work", cwd=self.repo)
        self.env["DIARY_PUBLISH"] = "1"
        result = self.publish(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs from remote", result.stderr)

    def test_missing_markdown(self):
        self.assertNotEqual(self.publish("2026-10-02", check=False).returncode, 0)


if __name__ == "__main__":
    unittest.main()
