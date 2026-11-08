"""路远 Web 面板 + REST API（FastAPI）。"""
import io
import os
import time
import datetime

import re
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

import config
import store
import bridge

_BASE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(_BASE, "ui")

app = FastAPI(title="路远")


APP_VER = 51   # 前端资源版本（与 panel.html 的 app.js?v= 保持一致，改前端时 +1）


def _privacy_granted(source=None):
    """私密内容是否获准外发（2026-09-13 红线变更）。

    旧规则「私密永不外发」→ 新规则「默认不外发，经用户允许可外发」。
    授权判定统一收口在 askaway.privacy_granted（全局开关 / 来源白名单）。
    单次授权由各路由的 allow_private 入参表达。
    """
    try:
        import askaway
        return askaway.privacy_granted(source)
    except Exception:
        return False


@app.get("/api/health")
def health():
    return {"ok": True, "time": time.time(), "ver": APP_VER}


# ---- 课务系统（独立应用 :8790）接入：面板「课务」页用 iframe 装它的界面 ----
@app.get("/api/keiwu/status")
def keiwu_status():
    import keiwu
    return keiwu.status()


@app.post("/api/keiwu/ensure")
def keiwu_ensure():
    import keiwu
    return keiwu.ensure()


# ---- 消息采集与总结（msgdigest）已于 2026-09-18 按路河拍板彻底下线 ----
# 备份与回退：.zcode_backup/2026-09-18_msgdigest下线/


@app.get("/api/notes")
def notes(limit: int = 200, tag: str = "", trash: int = 0, ondate: str = "",
          diary: int = 0):
    ns = store.list_notes(limit=limit + 50, tag=tag or None,
                          trash=bool(trash), ondate=ondate or None)
    if diary:
        ns = [n for n in ns if "日记" in (n.get("tags") or [])]
    else:
        ns = [n for n in ns if "日记" not in (n.get("tags") or [])]
    return {"notes": ns[:limit]}


@app.get("/api/note_dates")
def note_dates():
    """有笔记的日期+条数（供面板日期跳转）。"""
    return {"dates": store.note_dates()}


@app.get("/api/search")
def search(q: str = "", tag: str = "", diary: int = 0):
    out = store.search_notes(q)
    if tag:
        out = [n for n in out if tag in (n.get("tags") or [])]
    else:
        out = [n for n in out if ("日记" in (n.get("tags") or [])) == bool(diary)]
    # 关键字搜不到几条时，追加"意思相近"的语义结果（模型懒加载，首次约 20 秒）
    if q and len(out) < 3 and not tag:
        try:
            import semsearch
            out = out + semsearch.search(q, exclude={n["id"] for n in out})
        except Exception:
            pass
    return {"notes": out}


@app.post("/api/notes")
async def create(req: Request):
    data = await req.json()
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    note = store.add_note(text, source=data.get("source", "manual"),
                          tags=data.get("tags"))
    bridge.set_status("saved", text)
    # 自动归类（后台线程，失败静默，绝不影响记事）
    if note:
        try:
            import classify
            classify.classify_async(note["id"], text)
        except Exception:
            pass
    return {"note": note}


@app.delete("/api/notes/{nid}")
def delete(nid: str):
    """软删（进回收站，可恢复）。彻底清除走 /purge。"""
    return {"deleted": store.soft_delete(nid) is not None}


@app.post("/api/notes/{nid}/restore")
def restore(nid: str):
    note = store.restore_note(nid)
    if not note:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"note": note}


@app.post("/api/notes/{nid}/purge")
def purge(nid: str):
    """彻底清除（物理删除，不可恢复）。"""
    return {"purged": store.purge_note(nid)}


@app.post("/api/notes/trash/empty")
def trash_empty():
    """清空回收站。"""
    n = sum(1 for note in store.list_notes(trash=True) if store.purge_note(note["id"]))
    return {"purged": n}


@app.post("/api/notes/delete_many")
async def delete_many(req: Request):
    data = await req.json()
    ids = data.get("ids") or []
    deleted = store.soft_delete_many(ids)
    return {"deleted": deleted}


@app.post("/api/notes/restore_many")
async def restore_many(req: Request):
    """批量恢复（回收站工具条，v1.37）。"""
    data = await req.json()
    return {"restored": store.restore_many(data.get("ids") or [])}


@app.post("/api/notes/purge_many")
async def purge_many(req: Request):
    """批量彻底删除（仅回收站内的条目会被接受，防误删）。"""
    data = await req.json()
    return {"purged": store.purge_many(data.get("ids") or [])}


@app.get("/api/counts")
def counts():
    """模块计数（左栏徽章用）：笔记不含日记；记账=当月条数。"""
    import contacts as _ct
    import courses as _co
    import expenses as _ex
    ns = store.list_notes(limit=None)
    diary = sum(1 for n in ns if "日记" in (n.get("tags") or []))
    try:
        import readlater as _rl
        rl = _rl.pending_items()
        rl_pending, rl_failed = len(rl["pending"]), len(rl["failed"])
    except Exception:
        rl_pending = rl_failed = 0
    try:
        import todos as _td
        msg_todo = _td.overview()["count"]
    except Exception:
        msg_todo = 0
    return {"note": len(ns) - diary, "diary": diary,
            "trash": len(store.list_notes(trash=True, limit=None)),
            "expense": len(_ex.list_month()),
            "course": len(_co.list_courses()),
            "contact": len(_ct.list_contacts()),
            "msg_todo": msg_todo,
            "readlater_pending": rl_pending,
            "readlater_failed": rl_failed}


@app.put("/api/notes/{nid}")
async def update(nid: str, req: Request):
    data = await req.json()
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    note = store.update_note(nid, text)
    if not note:
        return JSONResponse({"error": "not_found"}, status_code=404)
    # 编辑后重新走智能捕获（改对错字/人名后待办与归类能补上）
    try:
        import classify
        classify.classify_async(nid, text)
    except Exception:
        pass
    return {"note": note}


@app.post("/api/notes/{nid}/reminder")
async def set_reminder(nid: str, req: Request):
    """设置/取消提醒。body {"remind_at": "ISO8601"} 或 {"remind_at": null} 取消。"""
    data = await req.json()
    ra = data.get("remind_at")
    if ra:
        try:
            datetime.datetime.fromisoformat(ra)
        except (ValueError, TypeError):
            return JSONResponse({"error": "bad time"}, status_code=400)
    note = store.set_reminder(nid, ra)
    if not note:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"note": note}


# ---------------- 自定义分类 ----------------
@app.get("/api/categories")
def get_categories():
    return {"categories": store.read_categories()}


@app.post("/api/categories")
async def set_categories(req: Request):
    data = await req.json()
    cats = data.get("categories") or []
    if not isinstance(cats, list):
        return JSONResponse({"error": "bad list"}, status_code=400)
    return {"categories": store.write_categories(cats)}


# ---------------- ✨ 整理（Ollama，只追加不覆盖原文） ----------------
@app.post("/api/notes/{nid}/organize")
def organize(nid: str, allow_private: bool = False):
    import smart
    note = store.get_note(nid)
    if not note:
        return JSONResponse({"error": "not_found"}, status_code=404)
    text = note.get("text", "").split("\n\n---- ✨ 整理 ----\n\n")[0]
    # 隐私红线（2026-09-13 变更）：私密内容默认只走本地；经用户允许可外发。
    # 允许途径 = 单次授权（?allow_private=true）或全局授权（privacy 配置）。
    allow_cloud = ("私密" not in (note.get("tags") or [])) or allow_private or _privacy_granted()
    block = smart.organize(text, allow_cloud=allow_cloud)
    if block is None:
        return JSONResponse({"error": "organize_off",
                             "msg": "云端与本地模型都没连上，整理功能暂不可用"},
                            status_code=503)
    return {"note": store.organize_note(nid, block)}


# ---------------- ✨ 一键合并整理（多条笔记 → 一条汇总，原文归档软删可恢复） ----------------
@app.post("/api/notes/merge-organize")
async def merge_organize(request: Request):
    """入参 JSON {ids: [...], archive: true}。把选中的多条笔记归并成一条新笔记；
    原始笔记默认打「已合并」标签 + 软删（进回收站，可整体恢复）。
    隐私红线（2026-09-13 变更）：任一条带「私密」标签时默认只走本地模型；
    若用户显式允许（body.allow_private=true 或全局 privacy 授权）则可外发。

    注意：必须用 Request 手动解析 body。写成 `payload: dict` 会被 FastAPI
    当成 query 参数（要求 ?payload=...），前端发 JSON body 就 422。"""
    import smart
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    ids = [str(i) for i in (payload.get("ids") or []) if i]
    if len(ids) < 2:
        return JSONResponse({"error": "need_more",
                             "msg": "至少勾选 2 条笔记才能合并。"}, status_code=400)
    srcs = [n for n in (store.get_note(i) for i in ids) if n]
    if len(srcs) < 2:
        return JSONResponse({"error": "not_found",
                             "msg": "选中的笔记已不存在，刷新后再试。"}, status_code=404)
    srcs.sort(key=lambda n: n.get("created_at") or "")
    src_text = store.build_merged_text(srcs)
    # 隐私红线（2026-09-13 变更）：默认只走本地；单次授权（body.allow_private）或全局授权可外发
    allow_private = bool(payload.get("allow_private"))
    allow_cloud = (all("私密" not in (n.get("tags") or []) for n in srcs)
                   or allow_private or _privacy_granted())
    merged = smart.merge_organize(src_text, allow_cloud=allow_cloud)
    if merged is None:
        return JSONResponse({"error": "merge_off",
                             "msg": "云端与本地模型都没连上，合并整理暂不可用；笔记原样未动。"},
                            status_code=503)
    archive = payload.get("archive", True)
    if archive:
        r = store.merge_notes(ids, merged)
        if not r:
            return JSONResponse({"error": "merge_failed",
                                 "msg": "合并写入失败，笔记原样未动。"}, status_code=500)
        return {"ok": True, "note": r["note"],
                "archived": len(r["archived"]), "count": len(srcs)}
    # 不归档：只生成汇总条，原笔记完全不动
    note = store.add_note(merged, source="merge",
                          tags=["合并生成"],
                          extra={"merged_from": [n["id"] for n in srcs]})
    return {"ok": True, "note": note, "archived": 0, "count": len(srcs)}


# ---------------- 配置读写（设置抽屉点亮） ----------------
# 隐私红线：Key 永远不回传明文，只回「是否已配置」+ 尾 4 位供核对。
# 注意：必须精确匹配字段名，不能用子串——hotkey 含 "key"，子串匹配会误把热键当密钥掩掉。
_SECRET_FIELDS = ("api_key", "apikey", "key", "token", "secret", "password")


def _is_secret_field(name):
    n = (name or "").lower()
    if n == "hotkey" or n.endswith("_hotkey") or n.endswith("hotkey"):
        return False          # 热键不是密钥
    if n in ("fallback_model", "model", "model_dir"):
        return False
    return any(s == n or n.endswith("_" + s) for s in _SECRET_FIELDS) or n in _SECRET_FIELDS


def _mask_secret(v):
    v = str(v or "")
    if not v:
        return ""
    return "••••" + v[-4:] if len(v) > 4 else "••••"


@app.get("/api/config")
def get_config():
    """读配置。任何 key/token/secret 字段一律脱敏，只回掩码。"""
    cfg = config.load()

    def scrub(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if _is_secret_field(k):
                    out[k] = _mask_secret(v)
                    out[k + "_set"] = bool(v)
                else:
                    out[k] = scrub(v)
            return out
        if isinstance(node, list):
            return [scrub(x) for x in node]
        return node

    return {"ok": True, "config": scrub(cfg)}


@app.put("/api/config")
async def put_config(request: Request):
    """改配置。只接受白名单路径，掩码值（••••xx）视为「不修改」原样保留。"""
    body = await request.json()
    # 白名单：path 形如 "askaway.api_key" / "ollama.endpoint"，避免误改无关配置
    ALLOW = ("askaway.", "chat.", "ollama.", "stt.", "app.", "wechat.")   # wechat. = judge_mode/auto_send 热更新（A11）
    patch = body.get("patch") or {}
    if not isinstance(patch, dict) or not patch:
        return JSONResponse({"error": "bad_patch", "msg": "没有要修改的配置项。"},
                            status_code=400)
    cfg = config.load()
    changed, skipped = [], []
    for path, value in patch.items():
        if not any(path.startswith(p) for p in ALLOW):
            skipped.append(path)
            continue
        # 掩码值不覆盖（用户没动那个框）
        if isinstance(value, str) and (value.startswith("••••") or value.startswith("****")):
            skipped.append(path)
            continue
        parts = path.split(".")
        node = cfg
        for p in parts[:-1]:
            if not isinstance(node.get(p), dict):
                node[p] = {}
            node = node[p]
        if node.get(parts[-1]) != value:
            node[parts[-1]] = value
            changed.append(path)
    if changed:
        config.save(cfg)
    return {"ok": True, "changed": changed, "skipped": skipped}


# ---------------- 今日/本周回顾（只展示，不落库） ----------------
@app.get("/api/digest")
def digest(scope: str = "day"):
    import smart
    now = datetime.datetime.now().astimezone()
    if scope == "week":
        start = (now - datetime.timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0)
    else:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    texts = [n["text"].split("\n\n---- ✨ 整理 ----\n\n")[0]
             for n in store.list_notes(limit=200)
             if n.get("created_at", "") >= start.isoformat(timespec="seconds")]
    out = smart.digest(texts, scope="day" if scope == "day" else "week")
    if out is None:
        return JSONResponse({"error": "ollama_off",
                             "msg": "Ollama 未运行，回顾暂不可用"}, status_code=503)
    return {"digest": out, "count": len(texts)}


# ---------------- Ollama 状态徽标 ----------------
@app.get("/api/ollama")
def ollama_status():
    import smart
    return {"running": smart.ollama_running(), "model": smart.pick_model()}


@app.post("/api/ollama/wake")
def ollama_wake():
    import smart
    return {"running": smart.wake()}


# ---------------- 联系人（人脉页，格式见 SYNC_FORMAT 第八节） ----------------
@app.get("/api/contacts")
def contacts_list(q: str = "", group: str = "", sort: str = ""):
    """group=分组筛选（空=全部）；sort=sid 按学号 / letter 按拼音 / 空=自动。
    顺带把已有分组清单一并返回，省得前端再发一次请求。"""
    import contacts
    return {"contacts": contacts.list_contacts(q, group=group or None,
                                               sort=sort or None),
            "groups": contacts.list_groups()}


@app.post("/api/contacts")
async def contacts_add(req: Request):
    import contacts
    data = await req.json()
    c = contacts.add_contact(data.get("name", ""),
                             group=data.get("group", ""),
                             sid=data.get("sid", ""))
    if not c:
        return JSONResponse({"error": "empty"}, status_code=400)
    return {"contact": c}


@app.get("/api/contacts/{cid}")
def contacts_get(cid: str):
    import contacts
    c = contacts.get_contact(cid)
    if not c:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"contact": c}


@app.put("/api/contacts/{cid}")
async def contacts_update(cid: str, req: Request):
    import contacts
    data = await req.json()
    c = contacts.update_contact(cid, data)
    if not c:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"contact": c}


@app.delete("/api/contacts/{cid}")
def contacts_delete(cid: str):
    import contacts
    return {"deleted": contacts.delete_contact(cid)}


@app.post("/api/contacts/{cid}/info")
async def contacts_add_info(cid: str, req: Request):
    import contacts
    data = await req.json()
    c = contacts.add_info(cid, data.get("text", ""))
    if not c:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"contact": c}


@app.post("/api/contacts/{cid}/todos")
async def contacts_add_todo(cid: str, req: Request):
    import contacts
    data = await req.json()
    t = contacts.add_todo(cid, data.get("text", ""))
    if not t:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"todo": t, "contact": contacts.get_contact(cid)}


@app.post("/api/contacts/{cid}/todos/{tid}/toggle")
def contacts_toggle_todo(cid: str, tid: str):
    import contacts
    t = contacts.toggle_todo(cid, tid)
    if not t:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"todo": t, "contact": contacts.get_contact(cid)}


@app.post("/api/contacts/{cid}/todos/{tid}/snooze")
async def contacts_snooze_todo(cid: str, tid: str, req: Request):
    import contacts
    data = await req.json()
    hours = float(data.get("hours", 1))
    t = contacts.snooze_todo(cid, tid, hours)
    if not t:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"todo": t, "contact": contacts.get_contact(cid)}


@app.delete("/api/contacts/{cid}/todos/{tid}")
def contacts_del_todo(cid: str, tid: str):
    import contacts
    return {"deleted": contacts.delete_todo(cid, tid)}


# ---------------- 日记（负一屏，复用笔记存储 tags=["日记"]） ----------------
def _diary_days():
    days = set()
    for n in store.list_notes(tag="日记", limit=500):
        days.add(str(n.get("created_at", ""))[:10])
    return days


def _diary_streak():
    import datetime as _dt
    days = _diary_days()
    d = _dt.date.today()
    if d.strftime("%Y-%m-%d") not in days:
        d -= _dt.timedelta(days=1)   # 今天还没写，从昨天起算连续
    streak = 0
    while d.strftime("%Y-%m-%d") in days:
        streak += 1
        d -= _dt.timedelta(days=1)
    return streak


@app.get("/api/diary/today")
def diary_today():
    today = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
    ns = [n for n in store.list_notes(tag="日记", limit=50)
          if str(n.get("created_at", "")).startswith(today)]
    return {"note": ns[0] if ns else None, "streak": _diary_streak()}


@app.post("/api/diary")
async def diary_save(req: Request):
    data = await req.json()
    text = (data.get("text") or "").strip()
    if not text:
        return JSONResponse({"error": "empty"}, status_code=400)
    today = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
    ns = [n for n in store.list_notes(tag="日记", limit=50)
          if str(n.get("created_at", "")).startswith(today)]
    if ns:
        note = store.update_note(ns[0]["id"], text)
    else:
        note = store.add_note(text, tags=["日记"])
    images = data.get("images")
    if note and isinstance(images, list):
        note = store.set_images(note["id"], [i for i in images
                                             if str(i).startswith("images/")])
    return {"note": note, "streak": _diary_streak()}


@app.get("/api/diary/recent")
def diary_recent(limit: int = 30):
    return {"notes": store.list_notes(tag="日记", limit=limit)}


# ---------------- 图片（日记配图，存 data/notes/images/ 随同步） ----------------
_IMAGES_DIR = os.path.join(_BASE, "data", "notes", "images")


def _save_image_b64(b64):
    """base64 图片（jpeg/png）落盘为 jpg，返回相对路径 images/<id>.jpg。"""
    import base64
    import uuid as _uuid
    m = re.match(r"^data:image/(jpeg|jpg|png|webp);base64,(.+)$", b64 or "", re.S)
    if not m:
        return None
    raw = base64.b64decode(m.group(2))
    if len(raw) > 12 * 1024 * 1024:
        return None
    os.makedirs(_IMAGES_DIR, exist_ok=True)
    fname = _uuid.uuid4().hex[:12] + ".jpg"
    # 有 PIL 就统一转 JPEG 压一压，没有就直接存
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.save(os.path.join(_IMAGES_DIR, fname), "JPEG", quality=85)
    except Exception:
        with open(os.path.join(_IMAGES_DIR, fname), "wb") as f:
            f.write(raw)
    return "images/" + fname


@app.post("/api/upload_image")
async def upload_image(req: Request):
    data = await req.json()
    path = _save_image_b64(data.get("data", ""))
    if not path:
        return JSONResponse({"error": "bad image"}, status_code=400)
    return {"path": path}


@app.get("/media/{fname}")
def media(fname: str):
    if not re.match(r"^[\w.\-]+$", fname):
        return JSONResponse({"error": "bad name"}, status_code=400)
    fp = os.path.join(_IMAGES_DIR, fname)
    if not os.path.isfile(fp):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(fp)


@app.post("/api/capture")
def capture():
    return {"triggered": bridge.request_capture()}


@app.post("/api/capture/stop")
def capture_stop():
    bridge.request_stop()
    return {"stopped": True}


@app.get("/api/status")
def status():
    return bridge.get_status()


# ---------------- 记账（SYNC_FORMAT v2 §10.2） ----------------
@app.get("/api/expenses")
def expenses_list(month: str = ""):
    import expenses
    m = month or datetime.datetime.now().strftime("%Y-%m")
    return {"month": m, "items": expenses.list_month(m),
            "stats": expenses.month_stats(m)}


@app.post("/api/expenses")
async def expenses_add(req: Request):
    import expenses
    d = await req.json()
    e = expenses.add(d.get("amount"), d.get("item"), spent_at=d.get("spent_at"),
                     category=d.get("category"), source=d.get("source", "manual"))
    if not e:
        return JSONResponse({"error": "bad expense"}, status_code=400)
    return {"expense": e}


@app.put("/api/expenses/{eid}")
async def expenses_update(eid: str, req: Request):
    import expenses
    d = await req.json()
    e = expenses.update(eid, d)
    if not e:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"expense": e}


@app.delete("/api/expenses/{eid}")
def expenses_delete(eid: str):
    import expenses
    return {"deleted": expenses.delete(eid)}


# ---------------- 课程（SYNC_FORMAT v2 §10.1） ----------------
@app.get("/api/courses")
def courses_list():
    import courses
    cs = courses.list_courses()
    for c in cs:
        c["_teacher_contact"] = c.get("teacher") in {
            x.get("name") for x in __import__("contacts").list_contacts()}
    return {"courses": cs, "today": courses.today_courses(),
            "next": courses.next_class(), "week": courses.current_week()}


@app.post("/api/courses")
async def courses_add(req: Request):
    import courses
    d = await req.json()
    c = courses.add(d.get("name"), teacher=d.get("teacher"), place=d.get("place"),
                    weekday=d.get("weekday", 1), start=d.get("start"),
                    end=d.get("end"), weeks=d.get("weeks", "1-16"),
                    semester=d.get("semester", ""))
    if not c:
        return JSONResponse({"error": "bad course"}, status_code=400)
    return {"course": c}


@app.put("/api/courses/{cid}")
async def courses_update(cid: str, req: Request):
    import courses
    d = await req.json()
    c = courses.update(cid, d)
    if not c:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"course": c}


@app.delete("/api/courses/{cid}")
def courses_delete(cid: str):
    import courses
    return {"deleted": courses.delete(cid)}


# ---------------- 消息待办（SYNC_FORMAT v3 §10.4：手机端产出，PC 读取+完成/丢弃回写） ----------------
@app.get("/api/todos")
def todos_list():
    import todos
    return todos.overview()


@app.post("/api/todos/{tid}/done")
def todos_done(tid: str):
    import todos
    t = todos.mark_done(tid)
    if not t:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"todo": t}


@app.post("/api/todos/{tid}/undone")
def todos_undone(tid: str):
    """取消完成（2026-09-18 挂账收尾）：done 翻回 false，Syncthing 带回手机。"""
    import todos
    t = todos.unmark(tid)
    if not t:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"todo": t}


@app.post("/api/todos/{tid}/discard")
@app.delete("/api/todos/{tid}")
def todos_discard(tid: str):
    import todos
    return {"deleted": todos.discard(tid)}


@app.post("/api/todos/{tid}/update")
async def todos_update(tid: str, req: Request):
    """vc127：白名单局部更新（topic/due_at/when_text）——路远远整理智能体给待办打主题标签用。
    done/deleted 不在白名单：智能体永远不能替路河销账或删待办。"""
    import todos
    d = await req.json()
    t = todos.update_fields(tid, d if isinstance(d, dict) else {})
    if not t:
        return JSONResponse({"error": "not_found_or_no_allowed_fields"}, status_code=404)
    return {"todo": t}


# ---------------- 路远远汇报（SYNC_FORMAT §10.6：路远远产出，PC 读取+已读/删除回写，2026-10-19 批） ----------------
@app.get("/api/reports")
def reports_list():
    import reports
    return reports.overview()


@app.get("/api/reports/badge")
def reports_badge():
    """侧栏红点轮询用：只回数字，不搬全文。"""
    import reports
    return {"unread": reports.unread_count()}


@app.post("/api/reports/{rid}/read")
def reports_read(rid: str):
    import reports
    r = reports.mark_read(rid, True)
    if not r:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"report": r}


@app.post("/api/reports/{rid}/unread")
def reports_unread(rid: str):
    import reports
    r = reports.mark_read(rid, False)
    if not r:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"report": r}


@app.post("/api/reports/read_all")
def reports_read_all():
    import reports
    return {"read": reports.read_all()}


@app.post("/api/reports/create")
async def reports_create(req: Request):
    """本机调试/其他工具补写一条汇报用（路远远正常走同步文件夹落盘，不经这里）。"""
    import reports
    d = await req.json()
    r = reports.create(d.get("title") or "", d.get("text") or "",
                       category=d.get("category") or "", ref=d.get("ref"),
                       summary=d.get("summary") or "")
    return {"report": r}


@app.post("/api/reports/{rid}/discard")
@app.delete("/api/reports/{rid}")
def reports_discard(rid: str):
    import reports
    return {"deleted": reports.discard(rid)}




@app.post("/api/courses/bulk")
async def courses_bulk(req: Request):
    import courses
    d = await req.json()
    added, skipped = courses.bulk(d.get("items") or [])
    return {"added": added, "skipped": skipped}

@app.post("/api/announce")
async def announce(req: Request):
    """语音播报（Windows SAPI，零依赖）：新消息待办到达等场景。异步不阻塞。"""
    d = await req.json()
    text = str(d.get("text") or "").strip()[:120]
    if not text:
        return {"ok": False, "reason": "empty"}

    import threading

    def _speak():
        try:
            import win32com.client
            v = win32com.client.Dispatch("SAPI.SpVoice")
            v.Speak(text)
        except Exception:
            pass

    threading.Thread(target=_speak, daemon=True).start()
    return {"ok": True}


@app.post("/api/expenses/import")
async def expenses_import(req: Request):
    import expenses
    d = await req.json()
    imp, skip, errors = expenses.import_bill_text(d.get("text") or "", d.get("source") or "bill")
    return {"imported": imp, "skipped": skip, "errors": errors[:5]}


# ---------------- CSU 学业助手（校历进提醒库 + 综测/奖学金/竞赛速查） ----------------
@app.get("/api/csu/overview")
def csu_overview():
    import csu
    return {"week": csu.week_info(), "events": csu.upcoming(60)}


@app.post("/api/csu/import")
def csu_import():
    import csu
    imp, skip = csu.import_calendar()
    s_imp, s_skip = csu.seed_notes()
    return {"calendar_imported": imp, "calendar_skipped": skip,
            "seeds_imported": s_imp, "seeds_skipped": s_skip}


@app.get("/api/csu/pending")
def csu_pending():
    import csu
    return csu.pending()


@app.get("/api/csu/quick")
def csu_quick(q: str = ""):
    import csu
    return csu.quick(q)


# ---------------- 冲突二选一（SYNC_FORMAT v2 §10.5：列对+裁决，败者进隔离区） ----------------
@app.get("/api/conflicts")
def conflicts_list():
    import conflicts
    return {"conflicts": conflicts.list_conflicts()}


@app.post("/api/conflicts/resolve")
async def conflicts_resolve(req: Request):
    import conflicts
    d = await req.json()
    r = conflicts.resolve(str(d.get("conflict") or ""), d.get("keep"))
    if not r:
        return JSONResponse({"error": "bad_conflict_or_keep"}, status_code=400)
    return r


# ---------------- 收件夹待确认（P1 视觉入库管线） ----------------
@app.get("/api/inbox/pending")
def inbox_pending():
    import vision
    return {"items": vision.pending_items(),
            "vl_model": vision.vl_model(),
            "failed": vision.failed_count()}


@app.post("/api/inbox/{pid}/confirm")
async def inbox_confirm(pid: str, req: Request):
    import vision
    try:
        edits = await req.json()
    except Exception:
        edits = {}
    r = vision.confirm(pid, edits or {})
    if r is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return r


@app.post("/api/inbox/{pid}/reject")
def inbox_reject(pid: str):
    import vision
    return {"rejected": vision.reject(pid)}


@app.get("/api/shots")
def shots_image(rel: str = ""):
    """截图/存档图片安全服务：只允许 shotsync_archive/ 与 inbox/ 前缀，禁目录穿越。"""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if ".." in rel or not (rel.startswith("shotsync_archive/") or rel.startswith("inbox/")):
        return JSONResponse({"error": "bad path"}, status_code=400)
    fp = os.path.join(_BASE, "data", rel)
    if not os.path.isfile(fp):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(fp)


# ---------------- 问路远（P4，Key 只在 config.json） ----------------
@app.post("/api/ask")
async def ask_away(req: Request):
    import askaway
    d = await req.json()
    answer, engine = askaway.ask(d.get("q", ""))
    return {"answer": answer, "engine": engine}


@app.get("/api/ask/history")
def ask_history():
    import askaway
    return {"history": askaway.history(),
            "has_key": bool(__import__("askaway")._cfg()["api_key"])}


@app.post("/api/ask/clear")
def ask_clear():
    import askaway
    askaway.clear_history()
    return {"ok": True}


# ---------------- 一言（P5） ----------------
@app.get("/api/hitokoto")
def hitokoto_rotate(rotate: int = 0):
    import hitokoto
    return hitokoto.current(force_fetch=bool(rotate))


# ---------------- 超级终端（动作清单 JSON 协议 v1，契约见 动作清单JSON协议_v1.md） ----------------
@app.post("/api/terminal")
async def terminal(req: Request):
    import router
    d = await req.json()
    fi = str(d.get("force_intent") or "").strip() or None
    r = router.route(str(d.get("text") or ""),
                     source=str(d.get("source") or "panel"),
                     force_intent=fi)
    if not r.get("ok"):
        return JSONResponse({"ok": False, "error": r.get("error")},
                            status_code=r.pop("_status", 400))
    return r


@app.get("/api/terminal/pending")
def terminal_pending():
    import router
    return {"items": router.pending_items()}


@app.get("/api/terminal/history")
def terminal_history(limit: int = 50):
    """终端输入历史（命令面板/回放用，最多回溯 100 条/7 天）。"""
    import router
    return {"items": router.history_items(min(limit, 100))}


@app.post("/api/terminal/{tid}/confirm")
async def terminal_confirm(tid: str, req: Request):
    import router
    try:
        d = await req.json()
    except Exception:
        d = {}
    d = d or {}
    r = router.confirm(tid, d.get("index"), d.get("edits"))
    if not r.get("ok"):
        return JSONResponse(r, status_code=r.pop("_status", 400))
    return r


@app.post("/api/terminal/{tid}/reject")
async def terminal_reject(tid: str, req: Request):
    import router
    try:
        d = await req.json()
    except Exception:
        d = {}
    d = d or {}
    r = router.reject(tid, d.get("index"))
    if not r.get("ok"):
        return JSONResponse(r, status_code=r.pop("_status", 400))
    return r


@app.post("/api/terminal/{tid}/undo")
def terminal_undo(tid: str):
    import router
    r = router.undo(tid)
    if not r.get("ok"):
        return JSONResponse(r, status_code=r.pop("_status", 400))
    return r


@app.post("/api/terminal/{tid}/rejudge")
async def terminal_rejudge(tid: str, req: Request):
    import router
    try:
        d = await req.json()
    except Exception:
        d = {}
    d = d or {}
    r = router.rejudge(tid, d.get("index"), d.get("action"))
    if not r.get("ok"):
        return JSONResponse(r, status_code=r.pop("_status", 400))
    return r


@app.get("/api/terminal/memory")
def terminal_memory():
    import router
    return {"memory": router.memory_entries()}


@app.post("/api/terminal/memory/clear")
def terminal_memory_clear():
    """清空误判记忆表（透明可清，用户可随时重来）。"""
    import router
    return router.memory_clear()


# ---------------- 路远对话人格（DeepSeek，chat.py，与 /api/terminal 意图路由完全隔离） ----------------
@app.post("/api/chat")
async def api_chat(req: Request):
    import chat as _chat
    d = await req.json()
    r = _chat.reply(str((d or {}).get("message") or ""))
    if not r.get("ok"):
        return JSONResponse({"error": r.get("error")},
                            status_code=r.pop("_status", 503))
    return {"reply": r.get("reply", ""), "used": r.get("used", "cloud")}


CACHE_NO = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache", "Expires": "0"}


@app.get("/")
def index():
    return FileResponse(os.path.join(UI, "panel.html"), headers=CACHE_NO)


@app.get("/app.js")
def appjs():
    return FileResponse(os.path.join(UI, "app.js"),
                        media_type="application/javascript",
                        headers=CACHE_NO)


@app.get("/ui/{fname}")
def ui_file(fname: str):
    # 防目录穿越：仅允许安全文件名
    import re
    if not re.match(r"^[\w.\-]+$", fname):
        return JSONResponse({"error": "bad name"}, status_code=400)
    fp = os.path.join(UI, fname)
    if not os.path.isfile(fp):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(fp, headers=CACHE_NO)


def run(host="127.0.0.1", port=8777):
    uvicorn.run(app, host=host, port=port, log_level="warning")


if __name__ == "__main__":
    cfg = config.load()["server"]
    run(host=cfg["host"], port=cfg["port"])
