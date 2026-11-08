#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""课表 / 调度 / 提醒 的单元测试（不联网、不碰真实数据）。

    .venv\\Scripts\\python.exe tests\\test_jobs.py -v

重点是**时间感**：这些代码决定"路远在什么时候主动开口"，
时间算错一天，用户就会收到"你没有我的课表吗？"那种消息。
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from luyuan.core.courses import CoursesRepo, parse_weeks, week_in, week_of
from luyuan.jobs.reminders import ReminderBus, make_class_soon_job
from luyuan.jobs.scheduler import Scheduler

START = "2026-09-14"          # 第 1 周周一（实测与真实课表吻合）


def _mk(**kw):
    base = {"kind": "course", "id": "c1", "name": "高等数学A（一）",
            "place": "潇湘校区-B座212", "weekday": 1, "start": "08:00", "end": "09:40",
            "weeks": "1-3,7-19", "deleted": False,
            "created_at": "2026-09-15T21:34:09", "updated_at": "2026-09-28T17:57:08"}
    base.update(kw)
    return base


class TestWeeks(unittest.TestCase):
    def test_parse_ranges(self):
        self.assertEqual(parse_weeks("1-3,7-19")[0], {1, 2, 3, *range(7, 20)})
        self.assertEqual(parse_weeks("10,12,14,16")[0], {10, 12, 14, 16})

    def test_parity(self):
        self.assertEqual(parse_weeks("1-16(单)")[1], "单")
        self.assertFalse(week_in("1-16(单)", 8))
        self.assertTrue(week_in("1-16(单)", 7))

    def test_week_of(self):
        # 2026-10-30 是第 7 周周五
        self.assertEqual(week_of(START, datetime(2026, 10, 30, 15, 0)), 7)
        self.assertEqual(week_of(START, datetime(2026, 9, 14, 8, 0)), 1)
        self.assertIsNone(week_of("", datetime(2026, 10, 30)))

    def test_unset_week_means_all(self):
        self.assertTrue(week_in("14-19", None), "学期起点没配时旧行为是不过滤")


class TestCourses(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = CoursesRepo(self._tmp.name, semester_start=START)
        self.repo.save(_mk())
        self.repo.save(_mk(id="c2", name="国防教育", weekday=4, start="08:00",
                           weeks="14-19", place="A101"))
        self.repo.save(_mk(id="c3", name="体育（一）", weekday=5, start="10:00",
                           weeks="1-3,7-19", place="潇湘校区"))

    def tearDown(self):
        self._tmp.cleanup()

    def test_week_is_seven(self):
        self.assertEqual(self.repo.week(datetime(2026, 10, 30, 15, 0)), 7)

    def test_today_filters_by_week(self):
        # 周五：只有体育（高数是周一，国防是周四且 14 周才开）
        rows = self.repo.today(datetime(2026, 10, 30, 15, 0))
        self.assertEqual([c["name"] for c in rows], ["体育（一）"])

    def test_today_ignores_wrong_week(self):
        rows = self.repo.today(datetime(2026, 10, 29, 9, 0))  # 周四 第7周
        self.assertEqual(rows, [], "第 7 周不该出现在 14-19 周的课")

    def test_next_class(self):
        nx = self.repo.next_class(datetime(2026, 10, 30, 15, 0))
        self.assertEqual(nx["course"]["name"], "高等数学A（一）")
        self.assertTrue(nx["at"].startswith("2026-11-02T08:00"))

    def test_due_soon_window(self):
        # 周一 07:50，高数 08:00 → 10 分钟后上课
        items = self.repo.due_soon(15, datetime(2026, 11, 2, 7, 50))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["minutes_away"], 10)
        # 07:30 太早，不该报
        self.assertEqual(self.repo.due_soon(15, datetime(2026, 11, 2, 7, 30)), [])

    def test_brief_next_is_a_sentence(self):
        s = self.repo.brief_next(datetime(2026, 10, 30, 15, 0))
        self.assertIn("下一节", s)
        self.assertIn("潇湘校区-B座212", s)


class TestReminderBus(unittest.TestCase):
    def test_dedupe_and_empty(self):
        bus = ReminderBus(path=Path(tempfile.gettempdir()) / "never.jsonl", dry_run=True)
        self.assertIsNone(bus.push("x", "   "), "空内容不发")
        self.assertIsNotNone(bus.push("class", "8:00 有课", key="k1"))
        self.assertIsNone(bus.push("class", "8:00 有课", key="k1"), "同一个 key 只说一次")
        self.assertEqual(len(bus.pending()), 1)

    def test_ack(self):
        bus = ReminderBus(path=Path(tempfile.gettempdir()) / "never.jsonl", dry_run=True)
        r = bus.push("w", "带伞")
        self.assertTrue(bus.ack(r["id"]))
        self.assertEqual(bus.pending(), [])


class TestClassJob(unittest.TestCase):
    def test_job_says_one_thing(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # 直接构造一个"周一 07:50"的场景：用 today 的真实逻辑不好注入 now，
        # 所以这里只验证 job 在无事可说时返回空、不抛异常。
        bus = ReminderBus(path=Path(tmp.name) / "r.jsonl", dry_run=True)
        job = make_class_soon_job(bus, window=15)
        out = job()          # 当前时刻大概率没课要上
        self.assertIsInstance(out, str)


class TestScheduler(unittest.TestCase):
    def test_runs_due_jobs_and_survives_errors(self):
        sch = Scheduler(dry_run=True, tick=1)
        hits = []

        def bang():
            raise RuntimeError("boom")

        sch.add("ok", 0, lambda: hits.append(1))
        sch.add("bad", 0, bang)
        sch.tick(now=100.0)
        self.assertEqual(hits, [1])
        bad = sch.get("bad")
        self.assertEqual(bad.fails, 1)
        self.assertIn("boom", bad.last_error)
        # 再跑一轮不因上一轮异常而停摆
        sch.tick(now=200.0)
        self.assertEqual(len(hits), 2)
        self.assertEqual(bad.fails, 2)

    def test_disabled_job_not_run(self):
        sch = Scheduler(dry_run=True)
        hits = []
        sch.add("off", 0, lambda: hits.append(1), enabled=False)
        sch.tick(now=100.0)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
