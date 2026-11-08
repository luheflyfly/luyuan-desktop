"""启动入口：`python -m luyuan [--port 8799] [--read-only]`

现在（P2 骨架阶段）它只起一个 Web 服务，用来和线上 8777 做行为对照。
后续阶段按 REFACTOR.md §4 依次接上 io / jobs / ai，最后这个文件就是"大脑"的全部编排：
    配置 → 数据 → io → ai → web → jobs
任何一步失败：写清楚哪一步失败、退码非 0（旧 main.py 是静默吞异常，最难查）。
"""
from __future__ import annotations

import argparse
import sys

import uvicorn

from luyuan import __version__, paths
from luyuan.config import Config
from luyuan.logs import setup


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="luyuan", description="路远大脑")
    p.add_argument("--host", default=None, help="监听地址（默认取 config.server.host）")
    p.add_argument("--port", type=int, default=None, help="监听端口（默认取 config.server.port）")
    p.add_argument("--read-only", action="store_true", default=False,
                   help="只读影子实例：拒绝所有写请求，用于重构对照")
    p.add_argument("--data", default=None, help="覆盖数据根（测试/影子用，等价 LUYUAN_DATA）")
    p.add_argument("--jobs", action="store_true", default=False,
                   help="启动调度器（课前/天气/周报提醒）；配合 --read-only 时只进内存不落盘")
    p.add_argument("--log-level", default="info")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.data:
        paths.use_data(args.data)

    setup(console=True)
    log = setup().getChild("main")
    log.info("路远大脑 v%s 启动", __version__)

    try:
        cfg = Config.load()
    except Exception as e:  # noqa: BLE001 — 启动阶段的错必须显式
        log.error("加载配置失败：%s", e)
        return 2

    paths.ensure_dirs()

    from luyuan.web.app import create_app

    app = create_app(cfg, read_only=args.read_only, jobs=args.jobs)
    host = args.host or ("127.0.0.1" if args.read_only else cfg.host)
    port = args.port or cfg.port
    log.info("监听 http://%s:%s （read_only=%s）", host, port, args.read_only)

    try:
        uvicorn.run(app, host=host, port=port, log_level=args.log_level, access_log=False)
    except KeyboardInterrupt:
        log.info("收到 Ctrl-C，正常退出")
    except Exception as e:  # noqa: BLE001
        log.exception("服务异常退出：%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
