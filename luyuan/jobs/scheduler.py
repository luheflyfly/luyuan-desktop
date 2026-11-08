"""一个调度器，替代 main.py 里 10 个 `while True`。

旧结构：提醒 / 联系人 / 生日 / 备份 / 收件箱 / 课表 / 日记 / 手机 / 转写 / 离开感，
十个线程各跑各的，任一个抛异常就静默死掉，且没人知道它死了。

新结构：
  * 所有定时任务注册成 Job（名字 + 间隔 + 函数）
  * 一个线程按"最早到期优先"轮转
  * 每次执行异常都记在 job 上（/api/jobs 能看见），不会连累别的任务
  * 每个 job 可以单独 enabled=False

`dry_run=True` 时不产生任何对外副作用（不发通知、不写同步目录），
只把"我本来要说什么"记下来 —— 这是影子实例验证提醒逻辑的方式。
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from luyuan.logs import get

log = get("scheduler")


@dataclass
class Job:
    name: str
    every: float                      # 秒
    fn: Callable[[], Any]
    enabled: bool = True
    run_at_start: bool = False
    last_run: float = 0.0
    last_error: str = ""
    runs: int = 0
    fails: int = 0
    last_result: str = field(default="")

    def due(self, now: float) -> bool:
        if not self.enabled:
            return False
        if self.last_run == 0 and self.run_at_start:
            return True
        return now - self.last_run >= self.every

    def as_dict(self) -> dict:
        return {
            "name": self.name, "every": int(self.every), "enabled": self.enabled,
            "runs": self.runs, "fails": self.fails, "last_error": self.last_error,
            "last_result": self.last_result,
            "since_last": int(time.time() - self.last_run) if self.last_run else None,
        }


class Scheduler:
    def __init__(self, dry_run: bool = True, tick: float = 20.0):
        self.jobs: list[Job] = []
        self.dry_run = dry_run
        self.tick_seconds = tick
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started_at = time.time()
        self.ticks = 0

    # ── 注册 ───────────────────────────────────────────────
    def add(self, name: str, every: float, fn: Callable[[], Any],
            run_at_start: bool = False, enabled: bool = True) -> Job:
        job = Job(name=name, every=every, fn=fn, run_at_start=run_at_start, enabled=enabled)
        self.jobs.append(job)
        return job

    def get(self, name: str) -> Job | None:
        return next((j for j in self.jobs if j.name == name), None)

    # ── 执行 ───────────────────────────────────────────────
    def tick(self, now: float | None = None) -> list[str]:
        now = now or time.time()
        ran: list[str] = []
        for job in self.jobs:
            if not job.due(now):
                continue
            job.last_run = now
            job.runs += 1
            try:
                result = job.fn()
                job.last_result = str(result)[:200] if result is not None else ""
                job.last_error = ""
            except Exception as e:  # noqa: BLE001 — 单个任务炸掉不能拖死调度器
                job.fails += 1
                job.last_error = f"{type(e).__name__}: {e}"
                log.error("job %s 失败: %s\n%s", job.name, job.last_error,
                          traceback.format_exc(limit=3))
            ran.append(job.name)
        self.ticks += 1
        return ran

    def _loop(self):
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.tick_seconds)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="luyuan-jobs", daemon=True)
        self._thread.start()
        log.info("调度器启动（dry_run=%s，%d 个任务）", self.dry_run, len(self.jobs))

    def stop(self, timeout: float = 3.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout)

    def status(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "ticks": self.ticks,
            "uptime": round(time.time() - self.started_at, 1),
            "jobs": [j.as_dict() for j in self.jobs],
        }
