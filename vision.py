# -*- coding: utf-8 -*-
"""视觉入库管线 v3（安全文件夹流水线，用户 09-07 口径）：

手机截图夹 ←Syncthing→ 电脑 data/shotsync/（同步夹）
每张新截图的旅程：
  1. **先完整复制到安全文件夹** data/shotsync_safe/（保底，识别崩溃也不丢图）
  2. 千问识别安全副本
  3. 分流：
     - 付款/消费 → 安全副本留在 shotsync_safe/月份/（=存档）+ 记账（默认进「待确认」，
       config.vision.auto_confirm=true 可全自动）→ **删除同步夹里的那份**
     - 课表 → 待确认供课程导入 → **删除同步夹里的那份**
     - 无关 → 安全副本挪 _unrelated/（7 天后悔期自动清）+ **删除同步夹里的那份**
     - 识别报错 → 重试 3 次，期间同步夹/安全夹都保留
  终态：**同步夹清空 = 手机截图夹干干净净**；账目图永久在安全文件夹。
防洪水：历史截图在手机端配对前自行挪走（见 截图同步协同.md §二）；本管线只管送进来的。
隐私红线：只连本机 Ollama。
"""
import os
import re
import json
import shutil
import glob
import time
import uuid
import base64
import logging
import datetime

log = logging.getLogger("vision")

_BASE = os.path.dirname(os.path.abspath(__file__))
SHOTS_DIR = os.path.join(_BASE, "data", "shotsync")            # Syncthing 同步夹（会清空）
SAFE_DIR = os.path.join(_BASE, "data", "shotsync_safe")        # 安全文件夹（账目存档）
UNRELATED_DIR = os.path.join(SAFE_DIR, "_unrelated")           # 无关图 7 天后悔期
PENDING_DIR = os.path.join(_BASE, "data", "inbox_pending")     # 待确认状态（PC 本地）
STATE_FILE = os.path.join(_BASE, "data", "shotsync_state.json")
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
MAX_ATTEMPTS = 3
UNRELATED_DAYS = 7

_cfg_cache = {"model": None, "ts": 0.0}
_sizes = {}   # 同步夹文件大小稳定性检查（防读到半截同步文件）


def _vcfg():
    import config as _cfg
    v = _cfg.load().get("vision", {})
    return {
        "auto_confirm": bool(v.get("auto_confirm", False)),
        "delete_unknown": bool(v.get("delete_unknown", True)),
    }


def _shots_dir():
    import config as _cfg
    custom = _cfg.load().get("vision", {}).get("shotsync_dir") or ""
    # shotsync_dir 未配置时是 None——os.path.isabs(None) 抛 TypeError，就是
    # 日志里每 60 秒一条 "shotsync watch error" 的来源（2026-09-08 深夜修）
    d = (custom if custom and os.path.isabs(custom)
         else os.path.join(_BASE, custom or "data/shotsync"))
    os.makedirs(d, exist_ok=True)
    return d


def _safe_dir():
    os.makedirs(SAFE_DIR, exist_ok=True)
    return SAFE_DIR


def _read_json(fp, default=None):
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write_json(fp, obj):
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def _state():
    return _read_json(STATE_FILE, {})


def _save_state(st):
    _write_json(STATE_FILE, st)


def ollama_base():
    import config as _cfg
    return _cfg.load().get("stt", {}).get("correct", {}).get(
        "endpoint", "http://localhost:11434").rstrip("/")


_VL_PREF = ("qwen3.5:4b", "qwen3.5:2b")   # 2026-09-13：qwen3.5 全系原生多模态，优先用它们
_VL_KW = ("vl", "vision", "llava", "minicpm-v", "moondream", "qwen3.5")


def vl_model(force=False):
    """探测本机 Ollama 视觉模型（先查白名单，再按名字含 vl/vision/llava 兜底）。5 分钟缓存。"""
    if not force and _cfg_cache["model"] and time.time() - _cfg_cache["ts"] < 300:
        return _cfg_cache["model"]
    model = None
    try:
        import urllib.request
        with urllib.request.urlopen(ollama_base() + "/api/tags", timeout=4) as r:
            tags = [m.get("name", "") for m in json.loads(
                r.read().decode("utf-8")).get("models", [])]
    except Exception as e:
        log.info("ollama tags unreachable: %s", e)
        return None
    model = next((p for p in _VL_PREF if p in tags), None)   # 白名单优先，别赌标签顺序
    if not model:
        for kw in _VL_KW:
            for t in tags:
                if kw in t.lower():
                    model = t
                    break
            if model:
                break
    _cfg_cache.update(model=model, ts=time.time())
    return model


PROMPT = (
    "你是截图识别器。看这张截图并判断类型，只输出一行 JSON，不要任何其他文字：\n"
    "1) 支付/消费记录（微信/支付宝账单、收款码记录等）→ "
    '{"type":"expense","amount":数字,"item":"名目","category":"餐饮|交通|学习|生活|娱乐|其他之一",'
    '"spent_at":"YYYY-MM-DDTHH:MM:SS"}（时间不确定用截图里能确定的精度）\n'
    "2) 课程表 → {\"type\":\"courses\",\"courses\":[{\"name\":\"课名\",\"teacher\":\"老师\","
    "\"place\":\"教室\",\"weekday\":1到7表示周一到周日,\"start\":\"HH:MM\",\"end\":\"HH:MM\","
    "\"weeks\":\"1-16\"}]}，把表里每一格都列出来；单双周在 weeks 后加（单）或（双）\n"
    "3) 都不是 → {\"type\":\"unknown\"}"
)


def recognize(image_path):
    """调本地 Ollama 视觉模型识别一张图。返回 (dict, None) 或 (None, 错误信息)。"""
    model = vl_model()
    if not model:
        return None, "本机 Ollama 没有视觉模型（如 qwen3.5:4b）"
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
    except OSError as e:
        return None, str(e)
    import urllib.request
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": PROMPT, "images": [b64]}],
        "stream": False,
        "think": False,   # 2026-09-13：qwen3.5 默认带思考，会把 num_predict 烧在推理上、JSON 出不来
        "options": {"temperature": 0, "num_predict": 800},
    }).encode("utf-8")
    req = urllib.request.Request(ollama_base() + "/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read().decode("utf-8")).get("message", {}).get("content", "")
    except Exception as e:
        return None, "ollama: %s" % e
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None, "模型输出不含 JSON: %s" % out[:80]
    try:
        return json.loads(m.group(0)), None
    except json.JSONDecodeError:
        return None, "模型 JSON 解析失败: %s" % m.group(0)[:80]


def pending_items():
    """全部待确认条目，新→旧。"""
    os.makedirs(PENDING_DIR, exist_ok=True)
    out = []
    for fp in sorted(glob.glob(os.path.join(PENDING_DIR, "*.json")), reverse=True):
        it = _read_json(fp)
        if it:
            it["_file"] = os.path.basename(fp)
            out.append(it)
    return out


def failed_count():
    return sum(1 for v in _read_json(STATE_FILE, {}).get("attempts", {}).values()
               if v.get("attempts", 0) >= MAX_ATTEMPTS)


def _safe_copy(sync_fp, fname):
    """同步夹 → 安全文件夹完整复制（已存在同名同大小则复用）。返回安全副本路径。"""
    dst = os.path.join(_safe_dir(), fname)
    if not os.path.exists(dst):
        shutil.copy2(sync_fp, dst)
    return dst


def _archive_from_safe(safe_fp):
    """账目存档：安全副本挪进 月份/ 子夹。返回相对 data/ 的路径（写进 expense.image）。"""
    month_dir = os.path.join(_safe_dir(), time.strftime("%Y-%m"))
    os.makedirs(month_dir, exist_ok=True)
    dst = os.path.join(month_dir, os.path.basename(safe_fp))
    i = 1
    stem, ext = os.path.splitext(os.path.basename(safe_fp))
    while os.path.exists(dst):
        dst = os.path.join(month_dir, "%s_%d%s" % (stem, i, ext))
        i += 1
    shutil.move(safe_fp, dst)
    return "shotsync_safe/%s/%s" % (time.strftime("%Y-%m"), os.path.basename(dst))


def _delete_sync(sync_fp):
    """删同步夹里的那份（双向同步 → 手机也干净）。"""
    try:
        os.remove(sync_fp)
        return True
    except OSError as e:
        log.warning("delete sync copy failed: %s", e)
        return False


def _purge_unrelated():
    """_unrelated/ 里超过 7 天的无关图自动清除（后悔期）。"""
    cutoff = time.time() - UNRELATED_DAYS * 86400
    os.makedirs(UNRELATED_DIR, exist_ok=True)
    for fp in glob.glob(os.path.join(UNRELATED_DIR, "*")):
        try:
            if os.path.getmtime(fp) < cutoff:
                os.remove(fp)
        except OSError:
            pass


def scan_once(max_per_scan=15):
    """扫一轮同步夹：复制→识别→分流。返回 (入账/待确认数, 删除数, 失败数)。"""
    global _sizes
    shots = _shots_dir()
    if not vl_model():
        return 0, 0, 0
    st = _state()
    auto = _vcfg()["auto_confirm"]
    booked = deleted = failed = 0
    processed = 0
    for fp in sorted(glob.glob(os.path.join(shots, "*")),
                     key=os.path.getmtime, reverse=False):
        if processed >= max_per_scan:
            break
        fname = os.path.basename(fp)
        if not fname.lower().endswith(IMG_EXT):
            continue
        try:
            size = os.path.getsize(fp)
        except OSError:
            continue
        if _sizes.get(fp) != size:
            _sizes[fp] = size      # 大小还在变 = Syncthing 还在传，下轮再说
            continue
        safe_fp = _safe_copy(fp, fname)
        att = st.get("attempts", {}).get(fname, {"attempts": 0})
        if att.get("attempts", 0) >= MAX_ATTEMPTS:
            continue   # 反复失败：两份都留着，面板有计数
        data, err = recognize(safe_fp)
        if err or not isinstance(data, dict):
            att["attempts"] = att.get("attempts", 0) + 1
            att["error"] = err or "bad output"
            st.setdefault("attempts", {})[fname] = att
            _save_state(st)
            failed += 1
            processed += 1
            log.info("shot recognize fail %s x%d: %s", fname, att["attempts"], err)
            continue
        kind = data.get("type")
        os.makedirs(PENDING_DIR, exist_ok=True)
        if kind == "expense":
            rel = _archive_from_safe(safe_fp)
            _delete_sync(fp)
            if auto:
                import expenses
                expenses.add(data.get("amount"), data.get("item"),
                             spent_at=data.get("spent_at"),
                             category=data.get("category"), source="screenshot", image=rel)
                log.info("shot auto-booked %s -> %s", fname, rel)
            else:
                item = {"id": uuid.uuid4().hex[:12], "file": rel, "type": "expense",
                        "data": data, "status": "pending",
                        "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
                _write_json(os.path.join(PENDING_DIR, item["id"] + ".json"), item)
                log.info("shot -> pending %s (%s)", fname, rel)
            booked += 1
        elif kind == "courses":
            item = {"id": uuid.uuid4().hex[:12], "file": fname, "type": "courses",
                    "data": data, "status": "pending",
                    "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
            _write_json(os.path.join(PENDING_DIR, item["id"] + ".json"), item)
            _delete_sync(fp)   # 识别完成，同步夹清掉（安全副本保留到确认/忽略）
            booked += 1
            log.info("shot course table -> pending %s", fname)
        else:
            # 无关：安全副本挪 _unrelated/（7 天后悔期），同步夹删除
            os.makedirs(UNRELATED_DIR, exist_ok=True)
            try:
                shutil.move(safe_fp, os.path.join(UNRELATED_DIR, fname))
            except OSError:
                pass
            if _vcfg()["delete_unknown"]:
                _delete_sync(fp)
            st.setdefault("ignored", {})[fname] = True
            _save_state(st)
            deleted += 1
            log.info("shot unrelated -> _unrelated + sync deleted: %s", fname)
        processed += 1
    _purge_unrelated()
    _sizes = {k: v for k, v in _sizes.items() if os.path.exists(k)}
    return booked, deleted, failed


def confirm(pending_id, edits=None):
    """确认入账（expense 记账 / courses 建课后清掉安全副本）。"""
    os.makedirs(PENDING_DIR, exist_ok=True)
    fp = os.path.join(PENDING_DIR, pending_id + ".json")
    it = _read_json(fp)
    if not it:
        return None
    edits = edits or {}
    created = []
    if it.get("type") == "expense":
        import expenses
        d = dict(it.get("data") or {})
        d.update({k: edits[k] for k in ("amount", "item", "category", "spent_at")
                  if edits.get(k) is not None})
        e = expenses.add(d.get("amount"), d.get("item"), spent_at=d.get("spent_at"),
                         category=d.get("category"), source="screenshot",
                         image=it.get("file"))
        if e:
            created.append({"kind": "expense", "id": e["id"]})
    elif it.get("type") == "courses":
        import courses
        for c in (it.get("data") or {}).get("courses", []):
            c.update(edits.get("course_fields", {}) or {})
            cc = courses.add(c.get("name"), teacher=c.get("teacher"), place=c.get("place"),
                             weekday=c.get("weekday"), start=c.get("start"),
                             end=c.get("end"), weeks=c.get("weeks", "1-16"))
            if cc:
                created.append({"kind": "course", "id": cc["id"], "name": cc["name"]})
        # 课程建完，安全副本任务完成
        try:
            os.remove(os.path.join(_safe_dir(), os.path.basename(it.get("file") or "")))
        except OSError:
            pass
    else:
        return None
    try:
        os.remove(fp)
    except OSError:
        pass
    log.info("shot confirmed %s: %d entities", pending_id, len(created))
    return {"created": created}


def reject(pending_id):
    """忽略：付款类安全副本已存档（保留）；课表类删安全副本。删待确认条目。"""
    os.makedirs(PENDING_DIR, exist_ok=True)
    fp = os.path.join(PENDING_DIR, pending_id + ".json")
    it = _read_json(fp)
    if not it:
        return False
    if it.get("type") == "courses":
        try:
            os.remove(os.path.join(_safe_dir(), os.path.basename(it.get("file") or "")))
        except OSError:
            pass
    try:
        os.remove(fp)
    except OSError:
        pass
    return True


def watch_loop(interval=60):
    """常驻扫描线程（main 起 daemon）。"""
    while True:
        try:
            scan_once()
        except Exception as e:
            log.warning("shotsync watch error: %s", e)
        time.sleep(interval)
