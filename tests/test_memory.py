import asyncio
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fishdeck.memory import Memory, RetentionError, diary_rows, read_json, row
from fishdeck.watch import sync

SHOW = "2026-11-23T00:05:00+08:00"
TIME = 1795363500000


class MemoryTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.mem = Memory(self.root, "#123")

    def test_feed_only_uses_official_life_events_and_keeps_old_cursor(self):
        state = {
            "fish": "鱼#123",
            "stage": "live",
            "where": {"place": {"name": "海边影院"}},
            "doing": {"name": "看电影", "since": SHOW, "with": ["阿紫#108", "none"]},
        }
        event = {"kind": "arrive", "t": TIME, "text": "到了北坡菜园"}
        notify = {"cursor": "first", "items": [event]}
        calls = []

        async def get(path, cursor=""):
            calls.append((path, cursor))
            return state if path == "state" else notify

        async def run():
            self.assertIn("首次", await sync(self.mem, "fwr_fake", get))
            self.assertEqual(self.mem.search("影院 #108", "2026-11-23")[0]["text"], "看电影")
            self.assertFalse(self.mem.search("菜园"))
            notify.update(
                cursor="next",
                items=[
                    event,
                    {"kind": "agreement", "t": TIME, "text": "不要自动提取约定"},
                    {"kind": "message", "t": TIME, "text": "私信正文泄露"},
                    {"kind": "done", "t": TIME, "text": "记下 fwr_should_not_save"},
                    {"kind": "done", "t": TIME, "text": "菜地浇完水"},
                ],
            )
            self.assertIn("新增 2 条", await sync(self.mem, "fwr_fake", get))
            self.assertEqual(calls[-1], ("notify", "first"))
            self.assertEqual(len(self.mem.search()), 3)
            self.assertIn("新增 0 条", await sync(self.mem, "fwr_fake", get))
            notify["cursor"] = ""
            with self.assertRaises(ValueError):
                await sync(self.mem, "fwr_fake", get)
            self.assertEqual(self.mem.load()[1]["cursor"], "next")
            state["fish"] = "别的鱼#999"
            with self.assertRaises(ValueError):
                await sync(self.mem, "fwr_fake", get)
            self.assertEqual(calls[-1], ("state", ""))
            self.assertFalse(Memory(self.root, "#999").search())
            state["fish"] = "鱼#123"
            notify.update(cursor="last", items=[])
            self.assertEqual(self.mem.clear(), 3)
            await sync(self.mem, "fwr_fake", get)
            self.assertEqual(self.mem.search(), [])
            self.assertEqual(calls[-1], ("notify", "next"))

        asyncio.run(run())

    def test_portable_export_and_diary_privacy(self):
        rows = diary_rows(
            "00:05\n开始：看电影\n00:08 私信：不公开\n00:20 结束：看电影\n"
            "00:30 开始：给小鱼发消息你好\n01:30 抵达：北坡菜园",
            "2026-11-23",
        )
        self.assertEqual(self.mem.merge(rows), 3)
        self.assertEqual(self.mem.merge(rows), 0)
        path = self.root / "export.json"
        self.mem.export(path)
        self.assertEqual(set(read_json(path)), {"format", "fish", "entries"})
        self.assertFalse(self.mem.search("不公开"))
        self.assertEqual(self.mem.search("电影", "2026-11-23", "done")[0]["source"], "journal-copy")
        with self.assertRaises(ValueError):
            Memory(self.root, "#456").import_file(path)
        other = Memory(self.root / "other", "#123")
        self.assertEqual(other.import_file(path), 3)
        fake = read_json(path)
        fake["entries"][-1]["text"] = "密钥 fwr_bad"
        path.write_text(json.dumps(fake), encoding="utf-8")
        with self.assertRaises(ValueError):
            other.import_file(path)
        self.assertEqual(len(other.search()), 3)

    def test_custom_retention_is_independent_and_preserves_cursor(self):
        for quota in (0, -2, True, "2000", 3.5):
            with self.subTest(quota=quota), self.assertRaises(RetentionError):
                Memory(self.root, "#123", quota)
        self.assertEqual(self.mem.max_entries, 2000)
        capped = Memory(self.root, "#123", 1)
        capped.merge([row(TIME, "done", "浇菜", "watch")], {"cursor": "known"})
        capped.merge([
            row(TIME + 60_000, "done", "吃饭", "watch"),
            row(TIME + 60_000, "agreement", "一起看电影", "fish-note", people=["#108"]),
        ])
        self.assertEqual(capped.load()[1]["cursor"], "known")
        self.assertEqual([r["text"] for r in capped.search()], ["吃饭", "一起看电影"])
        self.assertEqual(capped.merge([
            row(TIME + 60_000, "agreement", "一起种菜", "fish-note", people=["#108"])
        ]), 1)
        self.assertEqual(capped.search(kind="agreement")[0]["text"], "一起种菜")
        unlimited = Memory(self.root, "#123", -1)
        unlimited.merge([row(TIME + 120_000, "done", "散步", "watch")])
        self.assertEqual(len(capped.load()[0]), 3)
        capped.merge([])
        self.assertEqual({r["text"] for r in capped.search()}, {"散步", "一起种菜"})

    @unittest.skipUnless(shutil.which("node"), "需要 Node 验证大档案跨端迁移")
    def test_unlimited_archive_crosses_old_count_and_file_size_limits(self):
        total = 16_000
        mem = Memory(self.root, "#123", -1)
        entries = [
            row(TIME + i * 60_000, "done", f"回忆{i} " + "鱼" * 245, "watch")
            for i in range(total)
        ]
        self.assertEqual(mem.merge(entries), total)
        backup = self.root / "large.json"
        self.assertEqual(mem.export(backup), total)
        self.assertGreater(backup.stat().st_size, 12_000_000)
        script = """
          import assert from 'node:assert/strict'
          import { Memory } from './memory.js'
          const [root, imported, exported] = process.argv.slice(1)
          const memory = new Memory(root, '#123', -1)
          assert.equal(memory.importFile(imported), 16000)
          assert.equal(memory.exportFile(exported), 16000)
          assert.equal(memory.search('回忆0').length, 1)
        """
        node_export = self.root / "large-from-node.json"
        subprocess.run(
            [shutil.which("node"), "--input-type=module", "-e", script,
             str(self.root / "node"), str(backup), str(node_export)],
            cwd=Path(__file__).resolve().parents[1] / "harness",
            check=True,
        )
        capped = Memory(self.root / "capped", "#123", 2400)
        self.assertEqual(capped.import_file(node_export), 2400)
        self.assertEqual(capped.search()[0]["time"], TIME + (total - 1) * 60_000)
        self.assertEqual(capped.search("回忆0"), [])

    @unittest.skipUnless(shutil.which("node"), "需要 Node 验证两端互通")
    def test_python_and_node_exchange_portable_bundles(self):
        self.mem.merge(diary_rows("10:40 开始：打一份一荤两素（12 贝）", "2026-11-22"))
        self.assertEqual(self.mem.remember_agreement("#108", "11月25日一起看电影"), 1)
        original = self.root / "astrbot.json"
        exported = self.root / "harness.json"
        self.mem.export(original)
        script = """
          import assert from 'node:assert/strict'
          import { Memory, diaryRows } from './memory.js'
          const [root, imported, exported] = process.argv.slice(1)
          const memory = new Memory(root, '#123')
          assert.equal(memory.importFile(imported), 2)
          assert.equal(memory.search('一荤两素', '2026-11-22').length, 1)
          assert.deepEqual(memory.search('#108', '', 'agreement')[0].people, ['#108'])
          assert.equal(memory.search('#10', '', 'agreement').length, 0)
          assert.equal(memory.rememberAgreement('#108', '11月25日一起看电影'), 0)
          assert.equal(memory.rememberAgreement('#109', '11月26日一起种菜'), 1)
          memory.merge(diaryRows('11:25 抵达：北坡菜园', '2026-11-22'))
          assert.equal(memory.exportFile(exported), 4)
        """
        subprocess.run(
            [
                shutil.which("node"),
                "--input-type=module",
                "-e",
                script,
                str(self.root / "node"),
                str(original),
                str(exported),
            ],
            cwd=Path(__file__).resolve().parents[1] / "harness",
            check=True,
        )
        self.assertEqual(self.mem.import_file(exported), 2)
        self.assertEqual(self.mem.search("北坡")[0]["kind"], "arrive")
        self.assertEqual(self.mem.search("#109", kind="agreement")[0]["source"], "fish-note")


if __name__ == "__main__":
    unittest.main()
