"""仓储基类：一条记录 = 一个 JSON 文件。

为什么还是"一条一文件"：Syncthing 双向同步时整库单文件必冲突，一条一文件是这套
项目四个月里唯一没塌过的设计，保留。

相比旧 store.py（397 行、只服务笔记）升级三点：
  1. **通用**：按 kind 分域（note / todo / expense / diary / course / contact / report），
     一个基类 + 每个域一行子类，替代旧的 6 套各写各的读写。
  2. **原子写**：先写 .tmp 再 os.replace —— 断电/被杀不会留下半个 JSON
     （旧实现直接 open(w) 覆写，曾有 0 字节文件）。
  3. **索引缓存**：按 (path, mtime, size) 复用解析结果，避免每次请求把全目录重读一遍
     （旧 get_note() 每次都 glob + 全量 json.load，是"点一下卡一下"的来源之一）。

契约（SYNC_FORMAT.md，手机端依赖，**不可改**）：
  * 必带：id / created_at / updated_at
  * 可选：kind（空=笔记）/ deleted / device / schema / tags / text
  * 文件名：笔记 `<YYYY-mm-dd_HH-MM-SS>_<id8>.json`；实体 `<kind>_<id8>.json`
  * Syncthing 冲突副本 `*.sync-conflict-*` 不参与扫描
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from luyuan import paths
from luyuan.logs import get

log = get("store")

_lock = threading.RLock()


def iso_now() -> str:
    """本地时区 ISO8601，秒精度 —— 全项目时间字符串唯一格式（与旧数据一致）。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


class JsonRepo:
    """单目录 JSON 仓储。

    子类只需要声明 `kind`：
        class NotesRepo(JsonRepo):    kind = None      # 无 kind 字段 = 笔记
        class TodosRepo(JsonRepo):    kind = "todo"
    """

    kind: str | None = None
    strict_kind: bool = True
    # kind=None 且 strict_kind=True  → 只取「没有 kind 字段」的记录（笔记）
    # kind="todo" 且 strict_kind=True → 只取 kind=="todo"
    # strict_kind=False              → 不按 kind 过滤，整个目录就是边界（人脉域）

    def __init__(self, directory: Path | None = None):
        self.dir = Path(directory or paths.NOTES)
        self._parsed: dict[str, tuple[int, int, dict]] = {}  # path -> (mtime_ns, size, rec)

    # ── 扫描 ───────────────────────────────────────────────
    def _files(self) -> list[Path]:
        if not self.dir.exists():
            return []
        return [p for p in self.dir.glob("*.json")
                if ".sync-conflict" not in p.name and p.is_file()]

    def _read(self, path: Path) -> dict | None:
        try:
            st = path.stat()
        except OSError:
            return None
        key = str(path)
        hit = self._parsed.get(key)
        if hit and hit[0] == st.st_mtime_ns and hit[1] == st.st_size:
            return hit[2]
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 — 坏文件不能拖死整个列表
            log.warning("跳过坏文件 %s: %s", path.name, e)
            self._parsed.pop(key, None)
            return None
        if not isinstance(rec, dict):
            return None
        self._parsed[key] = (st.st_mtime_ns, st.st_size, rec)
        return rec

    def _matches_kind(self, rec: dict) -> bool:
        """kind=None 表示「没有 kind 字段」（笔记）；否则按字段严格相等。"""
        if not self.strict_kind:
            return True
        if self.kind is None:
            return not rec.get("kind")
        return rec.get("kind") == self.kind

    # ── 读 ─────────────────────────────────────────────────
    def all(self) -> list[dict]:
        """全部记录（含软删），按 created_at 倒序。每次调用都反映磁盘最新状态。"""
        out: list[dict] = []
        for p in self._files():
            rec = self._read(p)
            if rec and self._matches_kind(rec):
                out.append(rec)
        out.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        return out

    def __iter__(self) -> Iterator[dict]:
        return iter(self.all())

    def get(self, rid: str) -> dict | None:
        for p in self._files():
            rec = self._read(p)
            if rec and rec.get("id") == rid:
                return rec
        return None

    def _path_of(self, rid: str) -> Path | None:
        for p in self._files():
            rec = self._read(p)
            if rec and rec.get("id") == rid:
                return p
        return None

    def count(self) -> int:
        return len(self.all())

    # ── 写 ─────────────────────────────────────────────────
    def _filename(self, rec: dict) -> str:
        if rec.get("kind"):
            return f"{rec['kind']}_{str(rec['id'])[:8]}.json"
        created = str(rec.get("created_at") or iso_now())
        stamp = created[:19].replace("T", "_").replace(":", "-")
        return f"{stamp}_{str(rec['id'])[:8]}.json"

    def _atomic_write(self, path: Path, rec: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)  # 原子替换：读者要么见旧版，要么见新版

    def save(self, rec: dict) -> dict:
        """新增或整条覆盖。新增时补齐 id / created_at / updated_at。"""
        with _lock:
            rec = dict(rec)
            now = iso_now()
            # ⚠️ 必须用 if not 而不是 setdefault：调用方常把 id 显式写成 None，
            # setdefault 只在"键不存在"时生效，会留下 id=None → 文件名变成 *_None.json
            # （2026-10-30 被 tests/test_core.py 抓到的真 bug）。
            if not rec.get("id"):
                rec["id"] = str(uuid.uuid4())
            rec.setdefault("created_at", now)
            rec["updated_at"] = now
            if self.kind is not None:
                rec["kind"] = self.kind
            path = self._path_of(rec["id"]) or (self.dir / self._filename(rec))
            self._atomic_write(path, rec)
            return rec

    def update(self, rid: str, **fields: Any) -> dict | None:
        """只改给定字段（value=None 表示删掉该字段），其余原样保留。"""
        with _lock:
            path = self._path_of(rid)
            if not path:
                return None
            rec = self._read(path)
            if not rec:
                return None
            for k, v in fields.items():
                if v is None:
                    rec.pop(k, None)
                else:
                    rec[k] = v
            rec["updated_at"] = iso_now()
            self._atomic_write(path, rec)
            return rec

    def soft_delete(self, rid: str) -> dict | None:
        return self.update(rid, deleted=True)

    def restore(self, rid: str) -> dict | None:
        return self.update(rid, deleted=None)

    def purge(self, rid: str) -> bool:
        """物理删除。**只在回收站里调用**（旧代码的教训：直接删等于没后悔药）。"""
        with _lock:
            path = self._path_of(rid)
            if not path:
                return False
            try:
                path.unlink()
                self._parsed.pop(str(path), None)
                return True
            except OSError as e:
                log.warning("删除失败 %s: %s", path.name, e)
                return False

    # ── 便捷 ───────────────────────────────────────────────
    def visible(self) -> list[dict]:
        """未软删的记录。"""
        return [r for r in self.all() if not r.get("deleted")]

    def trash(self) -> list[dict]:
        return [r for r in self.all() if r.get("deleted")]

    def search(self, q: str, fields: tuple[str, ...] = ("text", "title", "summary")) -> list[dict]:
        q = (q or "").strip().lower()
        if not q:
            return self.visible()
        out = []
        for rec in self.visible():
            hay = " ".join(str(rec.get(f) or "") for f in fields)
            hay += " " + " ".join(str(t) for t in (rec.get("tags") or []))
            if q in hay.lower():
                out.append(rec)
        return out

    def by_date(self, day: str) -> list[dict]:
        """day='YYYY-MM-DD'"""
        return [r for r in self.all() if str(r.get("created_at") or "").startswith(day)]

    def dates(self) -> list[dict]:
        """有记录的日期 + 条数，新日期在前（面板日期跳转用）。

        ⚠️ 与旧 store.note_dates() 一致：**含软删**（旧实现没过滤 deleted，
        改成 visible() 会让历史日期的条数变少 —— 影子对照会立刻报出来）。
        """
        counts: dict[str, int] = {}
        for rec in self.all():
            d = str(rec.get("created_at") or "")[:10]
            if d:
                counts[d] = counts.get(d, 0) + 1
        return [{"date": d, "count": c} for d, c in sorted(counts.items(), reverse=True)]



# ── kind 注册表 ────────────────────────────────────────────
# 旧结构：todo / expense / course / contact / report / diary 各写一套读写函数，
# 六个文件里六份几乎一样的 glob + json.load + 排序。
# 新结构：kind 只是基类的一个字段，需要时按名取单例，缓存也跟着单例走。
_repos: dict[str, JsonRepo] = {}


def repo_for(kind: str, directory: Path | None = None) -> JsonRepo:
    """按 kind 取仓储单例（同进程复用索引缓存）。"""
    key = f"{kind}@{directory or ''}"
    repo = _repos.get(key)
    if repo is None:
        cls = type(f"{kind.title()}Repo", (JsonRepo,), {"kind": kind})
        repo = cls(directory)
        _repos[key] = repo
    return repo
