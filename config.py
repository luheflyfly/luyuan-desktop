"""路远配置加载：读 config.json 并把相对路径解析为绝对路径。"""
import json
import os

_BASE = os.path.dirname(os.path.abspath(__file__))
_cache = None
_mtime = 0.0


def load():
    """读 config.json（带 mtime 热更新：外部手改文件后无需重启，下次 load 自动生效）。"""
    global _cache, _mtime
    path = os.path.join(_BASE, "config.json")
    try:
        m = os.path.getmtime(path)
    except OSError:
        m = _mtime
    if _cache is None or m != _mtime:
        with open(path, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        _mtime = m
    return _cache


def reload():
    global _cache
    _cache = None
    return load()


def save(cfg):
    """把配置写回 config.json。"""
    global _cache
    with open(os.path.join(_BASE, "config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    _cache = cfg


def abs_path(p):
    """把配置里的相对路径（相对项目根）转成绝对路径。"""
    if not p:
        return p
    return p if os.path.isabs(p) else os.path.join(_BASE, p)
