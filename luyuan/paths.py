"""路径唯一来源。

为什么单独一个文件：旧代码里 40+ 个模块各自 `os.path.join(_BASE, "data", ...)`，
换个数据目录要改 40 处，改漏一处就出现"两份数据"。新规则只有一句话：
**想知道某个路径，问 paths；不要在别处出现字符串 "data"。**

数据根可以用 `LUYUAN_DATA` 环境变量或 `paths.use_data()` 整体搬走
（影子实例、测试用，避免和线上数据抢读写）。
"""
from __future__ import annotations

import os
from pathlib import Path

# D:\Luyuan\luyuan\paths.py -> D:\Luyuan
ROOT: Path = Path(__file__).resolve().parent.parent

UI = ROOT / "ui"                 # 前端源码
CONFIG_FILE = ROOT / "config.json"
CONFIG_EXAMPLE = ROOT / "config.example.json"

# 以下在 _derive() 里统一赋值（模块加载时算一次，use_data() 可重算）
DATA: Path
NOTES: Path
MEDIA: Path
STATE: Path
LOGS: Path
BACKUPS: Path
MEMORY: Path


def _derive(data_root: Path) -> None:
    global DATA, NOTES, MEDIA, STATE, LOGS, BACKUPS, MEMORY
    DATA = Path(data_root)
    NOTES = DATA / "notes"           # 唯一同步目录（手机只认这里）
    MEDIA = DATA / "media"           # 录音 / 图片（新址；旧的还在 notes 下，迁移脚本会搬）
    STATE = DATA / "state"           # 运行态：窗口位置、索引、缓存
    LOGS = DATA / "logs"             # 所有日志集中
    BACKUPS = DATA / "backups"       # 每日 zip
    MEMORY = DATA / "memory"         # 人格记忆


def use_data(data_root: str | os.PathLike) -> None:
    """切换数据根（必须在任何仓储实例化之前调用）。"""
    _derive(Path(data_root))


_derive(Path(os.environ.get("LUYUAN_DATA") or (ROOT / "data")))


def ensure_dirs() -> None:
    """启动时确保目录存在（只建目录，不建文件）。"""
    for d in (DATA, NOTES, MEDIA, STATE, LOGS, BACKUPS, MEMORY):
        Path(d).mkdir(parents=True, exist_ok=True)


def state_file(name: str) -> Path:
    """运行态文件（overlay_pos / sem_index / hitokoto …）。"""
    STATE.mkdir(parents=True, exist_ok=True)
    return STATE / name


def log_file(name: str = "luyuan.log") -> Path:
    LOGS.mkdir(parents=True, exist_ok=True)
    return LOGS / name
