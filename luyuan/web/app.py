"""应用装配（唯一入口）。

    app = create_app(cfg, read_only=True)            # 影子实例：只读，绝不写用户数据
    app = create_app(cfg, read_only=False, jobs=True) # 大脑常态：带调度器

`read_only=True` 时所有非 GET 请求直接 403 —— 影子实例和线上实例共用同一个
data 目录，这是防"重构验证时把真数据写坏"的保险栓。

`jobs=True` 时挂上调度器与提醒队列（app.state 上），由 routes/reminders 暴露观测端点。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from luyuan import __version__, paths
from luyuan.config import Config
from luyuan.logs import get
from luyuan.web.routes import config as r_config
from luyuan.web.routes import courses as r_courses
from luyuan.web.routes import diary as r_diary
from luyuan.web.routes import expenses as r_expenses
from luyuan.web.routes import life as r_life
from luyuan.web.routes import notes as r_notes
from luyuan.web.routes import reminders as r_reminders
from luyuan.web.routes import system as r_system
from luyuan.web.routes import todos as r_todos

log = get("web")


def create_app(cfg: Config | None = None, read_only: bool = True,
               jobs: bool = False) -> FastAPI:
    cfg = cfg or Config.load()

    app = FastAPI(
        title="路远",
        version=__version__,
        docs_url="/api/docs" if not read_only else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],          # 本机/局域网自用；对外端口只有 Tailscale
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if read_only:
        @app.middleware("http")
        async def _read_only_guard(request: Request, call_next):
            if request.method not in ("GET", "HEAD", "OPTIONS"):
                return JSONResponse(
                    {"error": "read_only", "msg": "影子实例只读：见 REFACTOR.md §4 P2"},
                    status_code=403,
                )
            return await call_next(request)

    app.include_router(r_system.router)
    app.include_router(r_notes.router)
    app.include_router(r_todos.router)
    app.include_router(r_expenses.router)
    app.include_router(r_diary.router)
    app.include_router(r_config.router)
    app.include_router(r_life.router)
    app.include_router(r_courses.router)
    app.include_router(r_reminders.router)

    # 前端静态：与旧服务同路径 /ui/*，方便直接对比同一份页面
    if paths.UI.exists():
        app.mount("/ui", StaticFiles(directory=str(paths.UI)), name="ui")

    @app.get("/")
    def root():
        return {"app": "路远", "ver": __version__, "role": "brain",
                "read_only": read_only, "jobs": jobs, "ui": "/ui/panel.html"}

    # ── 调度器与提醒（可选）────────────────────────────────
    app.state.scheduler = None
    app.state.reminders = None
    if jobs:
        from luyuan.jobs.reminders import (ReminderBus, make_class_soon_job,
                                           make_weather_job, make_week_job)
        from luyuan.jobs.scheduler import Scheduler

        bus = ReminderBus(dry_run=read_only)
        sch = Scheduler(dry_run=read_only, tick=20)
        # dry_run 时提醒只进内存，不落盘 —— 影子实例绝不写用户数据目录
        sch.add("class_soon", 60, make_class_soon_job(bus), run_at_start=True)
        sch.add("weather", 1800, make_weather_job(bus, str(cfg.get("weather.city") or "长沙市")),
                run_at_start=True)
        sch.add("week_start", 3600, make_week_job(bus), run_at_start=True)
        app.state.scheduler = sch
        app.state.reminders = bus
        sch.start()

    log.info("app 装配完成 · read_only=%s · jobs=%s · data=%s", read_only, jobs, paths.DATA)
    return app
