#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""新骨架的单元测试（标准库 unittest，不依赖 pytest）。

    .venv\\Scripts\\python.exe tests\\test_core.py -v

只测"重构最容易改坏"的那几处契约：
  * 原子写（不留半个 JSON）
  * kind 过滤（笔记 / todo / expense 互不串台）
  * 软删与回收站
  * 待办字段白名单（done/deleted 永远碰不到）
  * 日记一天一篇 + 连续天数
  * 配置脱敏（key 只出掩码，写回不会被星号覆盖）
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from luyuan.core.diary import DiaryBook
from luyuan.core.expenses import ExpensesRepo
from luyuan.core.notes import NotesRepo
from luyuan.core.store import JsonRepo, repo_for
from luyuan.core.todos import AGENT_EDITABLE, TodosRepo


class TempRepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestStore(TempRepoCase):
    def test_add_and_read_back(self):
        r = NotesRepo(self.dir)
        n = r.add("明天带伞")
        self.assertIsNotNone(n)
        self.assertTrue((self.dir / r._filename(n)).exists())
        self.assertEqual(r.get(n["id"])["text"], "明天带伞")

    def test_atomic_no_tmp_left(self):
        r = NotesRepo(self.dir)
        n = r.add("x")
        r.update(n["id"], text="y")
        self.assertEqual([p.name for p in self.dir.glob("*.tmp")], [])

    def test_kind_isolation(self):
        notes, todos = NotesRepo(self.dir), TodosRepo(self.dir)
        notes.add("普通笔记")
        TodosRepo(self.dir).save({"kind": "todo", "id": "t1", "title": "交作业",
                                  "done": False, "deleted": False})
        self.assertEqual(len(notes.all()), 1, "笔记域不该看到 todo")
        self.assertEqual(len(todos.all()), 1)
        self.assertEqual(notes.all()[0]["text"], "普通笔记")

    def test_soft_delete_and_trash(self):
        r = NotesRepo(self.dir)
        n = r.add("要删的")
        r.soft_delete(n["id"])
        self.assertEqual(len(r.visible()), 0)
        self.assertEqual(len(r.trash()), 1)
        r.restore(n["id"])
        self.assertEqual(len(r.visible()), 1)

    def test_bad_file_does_not_break_list(self):
        r = NotesRepo(self.dir)
        r.add("好的")
        (self.dir / "broken.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual(len(r.all()), 1)

    def test_sync_conflict_excluded(self):
        r = NotesRepo(self.dir)
        r.add("正常")
        src = list(self.dir.glob("*.json"))[0]
        (self.dir / (src.stem + ".sync-conflict-20260101-000000-AAAAAA.json")).write_text(
            src.read_text(encoding="utf-8"), encoding="utf-8")
        self.assertEqual(len(r.all()), 1, "冲突副本不该被当成新记录")

    def test_repo_for_is_singleton(self):
        self.assertIs(repo_for("todo", self.dir), repo_for("todo", self.dir))


class TestTodos(TempRepoCase):
    def _seed(self):
        r = TodosRepo(self.dir)
        r.save({"kind": "todo", "id": "a", "title": "交作业", "done": False,
                "deleted": False, "created_at": "2026-10-30T08:00:00+08:00"})
        r.save({"kind": "todo", "id": "b", "title": "已完成的", "done": True,
                "done_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "deleted": False, "created_at": "2026-10-30T09:00:00+08:00"})
        r.save({"kind": "todo", "id": "c", "title": "不要的", "done": False,
                "deleted": True, "created_at": "2026-10-30T10:00:00+08:00"})
        return r

    def test_overview(self):
        r = self._seed()
        o = r.overview()
        self.assertEqual([t["id"] for t in o["todos"]], ["a"])
        self.assertEqual([t["id"] for t in o["done_today"]], ["b"])
        self.assertEqual(o["count"], 1)

    def test_whitelist_blocks_done(self):
        r = self._seed()
        self.assertIsNone(r.update_fields("a", {"done": True}), "done 不能走白名单")
        self.assertEqual(set(AGENT_EDITABLE), {"topic", "due_at", "when_text"})

    def test_whitelist_allows_topic(self):
        r = self._seed()
        t = r.update_fields("a", {"topic": "教务", "done": True})
        self.assertEqual(t["topic"], "教务")
        self.assertFalse(t["done"], "非法字段被忽略，done 保持原值")

    def test_discard_is_physical(self):
        r = self._seed()
        self.assertTrue(r.discard("a"))
        self.assertEqual(len(r.all()), 2)


class TestExpenses(TempRepoCase):
    def test_month_uses_spent_at(self):
        r = ExpensesRepo(self.dir)
        r.save({"kind": "expense", "id": "old01", "amount": 10, "item": "上月",
                "spent_at": "2026-09-30T12:00:00+08:00", "created_at": "2026-10-01T00:00:00+08:00"})
        r.save({"kind": "expense", "id": "new01", "amount": 20, "item": "本月",
                "spent_at": "2026-10-02T12:00:00+08:00", "created_at": "2026-10-02T12:00:00+08:00"})
        self.assertEqual([e["id"] for e in r.list_month("2026-10")], ["new01"])
        self.assertEqual([e["id"] for e in r.list_month("2026-09")], ["old01"])

    def test_stats(self):
        r = ExpensesRepo(self.dir)
        r.save({"kind": "expense", "id": "x1", "amount": 12.5, "item": "饭",
                "category": "餐饮", "spent_at": "2026-10-05T12:00:00+08:00"})
        r.save({"kind": "expense", "id": "x2", "amount": 7.5, "item": "水",
                "category": "餐饮", "spent_at": "2026-10-06T12:00:00+08:00"})
        st = r.month_stats("2026-10")
        self.assertEqual(st["total"], 20.0)
        self.assertEqual(st["categories"], [{"category": "餐饮", "amount": 20.0}])


class TestDiary(TempRepoCase):
    def test_one_per_day_and_streak(self):
        notes = NotesRepo(self.dir)
        book = DiaryBook(notes)
        today = datetime.now().astimezone().strftime("%Y-%m-%d")
        yesterday = (datetime.now().astimezone() - timedelta(days=1)).strftime("%Y-%m-%d")

        notes.add("昨天的日记", source="diary", tags=["日记"],
                  extra={"created_at": f"{yesterday}T21:00:00+08:00"})
        book.save("今天第一版")
        book.save("今天第二版")
        self.assertEqual(len(book.entries()), 2, "一天一篇：第二次是覆盖不是新增")
        self.assertEqual(book.today()["note"]["text"], "今天第二版")
        self.assertEqual(book.streak(), 2)

    def test_empty_text_rejected(self):
        self.assertIsNone(DiaryBook(NotesRepo(self.dir)).save("   "))


class TestConfigMasking(unittest.TestCase):
    def test_mask_and_restore(self):
        from luyuan.web.routes import config as C
        raw = {"askaway": {"api_key": "sk-REDACTED",
                           "model": "deepseek-v4-flash"}}
        masked = C._scrub(raw)
        self.assertNotIn("975cace9", json.dumps(masked))
        self.assertTrue(masked["askaway"]["api_key"].endswith("6e13"))

        # 前端把掩码原样提交回来 → 必须还原成真 key，不能写成星号
        back = C._restore_masked(raw, masked)
        self.assertEqual(back["askaway"]["api_key"], raw["askaway"]["api_key"])

    def test_plain_value_kept(self):
        from luyuan.web.routes import config as C
        back = C._restore_masked({"ai": {"model": "a"}}, {"ai": {"model": "b"}})
        self.assertEqual(back["ai"]["model"], "b")


class TestWeatherBrief(unittest.TestCase):
    """天气的"人话"规则（不联网，只测 brief 的措辞逻辑）。"""

    def _w(self, **kw):
        from luyuan.io.weather import Place, Weather
        base = dict(place=Place("长沙市", "湖南", 28.2, 112.97), temp=20.0, code=0,
                    precip=0.0, today_max=24.0, today_min=16.0, today_code=0, pop=10,
                    tomorrow_max=25.0, tomorrow_min=17.0, tomorrow_code=0, tomorrow_pop=0)
        base.update(kw)
        return Weather(**base)

    def test_rain_says_take_umbrella(self):
        w = self._w(today_code=61, pop=80)
        self.assertIn("带伞", w.brief())

    def test_dry_says_weather(self):
        w = self._w(today_code=0, pop=5)
        self.assertIn("晴", w.brief())
        self.assertNotIn("带伞", w.brief())

    def test_big_swing_adds_jacket(self):
        w = self._w(today_min=10.0, today_max=22.0)
        self.assertIn("外套", w.brief())

    def test_tomorrow_rain_mentioned_when_today_dry(self):
        w = self._w(today_code=0, pop=0, tomorrow_code=80, tomorrow_pop=90)
        self.assertIn("明天", w.brief())

    def test_snow_warns(self):
        w = self._w(today_code=73, pop=90)
        self.assertIn("雪", w.brief())


if __name__ == "__main__":
    unittest.main(verbosity=2)
