import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from release_notes import release_note


class ReleaseNoteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "manual.json"
        self.auto = Path(self.tmp.name) / "automatic.json"
        self.url = "https://github.com/acme/app/releases/tag/v1"

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, body, **kwargs):
        return release_note("acme/app", "v1", body, self.url, self.cache, self.auto, **kwargs)

    def test_chinese_original_precedes_translation_and_keeps_chinese_warning(self):
        note = self.call("新增小组件\n注意：需要重新签名，部分设备不兼容\nSecurity warning: do not use")
        self.assertIn("新增小组件", note)
        self.assertIn("注意：需要重新签名", note)
        self.assertNotIn("Security warning", note)

    def test_manual_cache_wins_without_translation_or_raw_english_warning(self):
        self.cache.write_text(json.dumps({"acme/app@v1": {"repo": "acme/app", "tag": "v1", "summary": "人工核实摘要"}}), encoding="utf-8")
        with patch("release_notes._translate") as translator:
            note = self.call("Security warning: device data may be erased\n注意：此处有冗长的原文警示")
        translator.assert_not_called()
        self.assertIn("人工核实摘要", note)
        self.assertNotIn("Security warning", note)
        self.assertNotIn("此处有冗长的原文警示", note)

    def test_english_notes_translate_warning_and_cache_reuse_requires_body_hash(self):
        body = "Added widgets\nSecurity warning: older devices may lose data"
        with patch("release_notes._translate", side_effect=["安全警示：旧设备可能丢失数据", "新增小组件"]) as translator:
            first = self.call(body)
        self.assertIn("新增小组件", first)
        self.assertIn("安全警示", first)
        self.assertNotIn("Security warning", first)
        self.assertEqual(translator.call_count, 2)
        self.assertEqual(translator.call_args_list[0].args[0], "Security warning: older devices may lose data")
        with patch("release_notes._translate", side_effect=AssertionError("should reuse cache")):
            repeated = self.call(body)
        self.assertIn("新增小组件", repeated)
        changed = body + "\nFixed crash"
        with patch("release_notes._translate", return_value="已修复崩溃") as translator:
            self.call(changed)
        translator.assert_called()
        entry = json.loads(self.auto.read_text(encoding="utf-8"))["acme/app@v1"]
        self.assertIn("body_sha256", entry)

    def test_translation_failure_falls_back_and_keeps_source_url(self):
        with patch("release_notes._translate", side_effect=TimeoutError):
            note = self.call("Added widgets\nSecurity: certificate expired")
        self.assertIn("翻译暂不可用", note)
        self.assertIn(self.url, note)
        self.assertNotIn("certificate expired", note)

    def test_cache_rejects_mismatched_embedded_repo_or_tag(self):
        self.cache.write_text(json.dumps({"acme/app@v1": {"repo": "acme/app", "tag": "v2", "summary": "错误摘要"}}), encoding="utf-8")
        with patch("release_notes._translate", side_effect=TimeoutError):
            note = self.call("Added feature")
        self.assertNotIn("错误摘要", note)


if __name__ == "__main__":
    unittest.main()
