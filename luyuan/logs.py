"""日志：一个地方配置，全大脑共用。

旧代码每个模块 `logging.basicConfig(level=INFO)` 各来一次，日志一半打到
黑框（关掉就没了）、一半写成 data/ 根目录下十几个 txt。
新规则：`from luyuan.logs import log`，全部落到 data/logs/luyuan.log（2MB×3 轮转），
控制台只在有终端时同步输出。
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from luyuan import paths

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_configured = False


def setup(level: int = logging.INFO, console: bool | None = None) -> logging.Logger:
    global _configured
    root = logging.getLogger("luyuan")
    if _configured:
        return root

    root.setLevel(level)
    root.propagate = False

    fh = RotatingFileHandler(paths.log_file(), maxBytes=2 * 1024 * 1024,
                             backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter(_FMT))
    root.addHandler(fh)

    if console is None:
        console = bool(sys.stderr) and sys.stderr.isatty()
    if console:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(logging.Formatter(_FMT))
        root.addHandler(sh)

    _configured = True
    return root


def get(name: str = "luyuan") -> logging.Logger:
    if not _configured:
        setup()
    return logging.getLogger("luyuan" if name == "luyuan" else f"luyuan.{name}")


log = get()
