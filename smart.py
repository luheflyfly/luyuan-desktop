# -*- coding: utf-8 -*-
"""统一智能层：所有 Ollama 小模型功能（归类/整理/抽提醒/回顾/状态）都走这里。

设计约束：
- 绝不影响主流程：Ollama 没开 / 超时 / 输出不对 → 返回 None，调用方自行降级。
- 模型优先挑小的（0.5b~4b），没有小模型再退回普通 chat 模型（7b/8b 也能干，就是慢）。
- 用 /api/chat 接口（小模型对 chat 格式听话得多）。
"""
import json
import re
import logging
import subprocess
import threading
import urllib.request
from datetime import datetime, timedelta

import config

log = logging.getLogger("smart")

_LOCK = threading.Lock()
_model_cache = {"name": None, "ts": 0.0}
_running_cache = {"val": False, "ts": 0.0}

_SMALL_RE = re.compile(r"(0\.5b|1\.5b|1\.7b|2b|3b|4b)", re.I)
_CHAT_KW = ("qwen", "llama", "gemma", "deepseek")

# 2026-09-13 换装：qwen3.5:2b 顶替 qwen2.5:1.5b（智能层），qwen3.5:4b 顶替 qwen3:8b（主力/重试）。
# 显式写死优先级，避免 /api/tags 的返回顺序变化导致挑错模型（旧库里 1.5b 还在）。
_SMALL_PREF = ("qwen3.5:2b", "qwen3.5:1.7b", "qwen2.5:1.5b")
_BIG_PREF = ("qwen3.5:4b", "qwen3.5:9b")


def endpoint():
    return config.load().get("stt", {}).get("correct", {}).get(
        "endpoint", "http://localhost:11434").rstrip("/")


def ollama_running(max_age=15):
    """Ollama 是否在跑（带 15 秒缓存，避免面板轮询压爆它）。"""
    now = datetime.now().timestamp()
    with _LOCK:
        if now - _running_cache["ts"] < max_age:
            return _running_cache["val"]
    try:
        with urllib.request.urlopen(endpoint() + "/api/tags", timeout=3) as r:
            ok = r.status == 200
    except Exception:
        ok = False
    with _LOCK:
        _running_cache["val"] = ok
        _running_cache["ts"] = now
    return ok


def pick_model():
    """挑一个模型：优先小模型（快、省内存），没有则退普通 chat 模型。缓存 5 分钟。"""
    now = datetime.now().timestamp()
    with _LOCK:
        if _model_cache["name"] and now - _model_cache["ts"] < 300:
            return _model_cache["name"]
    try:
        with urllib.request.urlopen(endpoint() + "/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return None
    if not names:
        return None
    smalls = [n for n in names if _SMALL_RE.search(n)]
    chosen = next((p for p in _SMALL_PREF if p in smalls), None)  # 先按白名单挑
    if not chosen and smalls:  # 小模型里再优先 qwen
        qw = [n for n in smalls if "qwen" in n.lower()]
        chosen = (qw or smalls)[0]
    if not chosen:
        for kw in _CHAT_KW:
            for n in names:
                if kw in n.lower():
                    chosen = n
                    break
            if chosen:
                break
        chosen = chosen or names[0]
    with _LOCK:
        _model_cache["name"] = chosen
        _model_cache["ts"] = now
    return chosen


def pick_big_model():
    """主力模型（排除 0.5b~4b 小模型和视觉模型，优先 qwen 7b/8b）。不缓存。"""
    try:
        with urllib.request.urlopen(endpoint() + "/api/tags", timeout=3) as r:
            names = [m.get("name", "") for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return None
    pref = next((p for p in _BIG_PREF if p in names), None)
    if pref:
        return pref
    bigs = [n for n in names
            if not _SMALL_RE.search(n) and "vl" not in n.lower()
            and re.search(r"(7b|8b|14b|32b)", n, re.I)]
    qw25 = [n for n in bigs if "qwen2.5" in n.lower()]   # 优先非思考模型（qwen3 会烧光预算在思考上）
    return (qw25 or bigs or [None])[0]


def wake():
    """尝试拉起 Ollama（`ollama list` 会自动把服务带起来，仅限安装版）。
    注意：必须带 OLLAMA_MODELS=D:\\ollama-models，否则裸起的 serve 会读 C 盘默认库。"""
    import shutil
    exe = shutil.which("ollama")
    if not exe:
        return False
    try:
        env = dict(os.environ)
        env["OLLAMA_MODELS"] = r"D:\ollama-models"
        env.setdefault("OLLAMA_HOST", "127.0.0.1:11434")
        subprocess.run([exe, "list"], capture_output=True, timeout=20, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        log.info("wake ollama failed: %s", e)
    with _LOCK:  # 失效缓存，强制重新探测
        _running_cache["ts"] = 0.0
        _model_cache["ts"] = 0.0
    return ollama_running(max_age=0)


def _post_chat(payload, timeout):
    req = urllib.request.Request(endpoint() + "/api/chat",
                                 data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def chat(messages, timeout=60, num_predict=400, temperature=0.3, model=None):
    """调 /api/chat。失败返回 None。model 可显式指定（如切分重试用主力模型）。"""
    model = model or pick_model()
    if not model or not ollama_running():
        return None
    payload = {
        "model": model, "messages": messages, "stream": False,
        # 2026-09-13：qwen3.5 默认带思考，会把 num_predict（分类只有 10）烧在思考上 → 显式关掉
        "think": False,
        "options": {"temperature": temperature, "num_predict": num_predict},
    }
    try:
        data = _post_chat(payload, timeout)
    except Exception as e:
        log.info("chat failed (think=false): %s", e)
        try:  # 老版 Ollama 不认识 think 字段 → 去掉再试一次
            payload.pop("think", None)
            data = _post_chat(payload, timeout)
        except Exception as e2:
            log.info("chat failed: %s", e2)
            return None
    return ((data.get("message") or {}).get("content") or "").strip()


# ---------------- 高层功能 ----------------

def classify_note(text, categories):
    """把记事归入 categories 之一。失败返回 None。"""
    if not text.strip() or not categories:
        return None
    cats = " / ".join(categories)
    sys_p = (
        "你是记事分类器。只输出一个词：" + cats + "。不解释。"
        "判断：将来要做的具体事/赴约/去取去拿去办 → 待办；买东西要吃的用的 → 购物；"
        "点子看法创意 → 想法；写的文字片段素材 → 写作素材；"
        "已经发生或正在发生的生活记录（含 今天/刚才/了）→ 日常。"
    )
    out = chat([
        {"role": "system", "content": sys_p},
        {"role": "user", "content": text[:200]},
    ], num_predict=10)
    if not out:
        return None
    for c in categories:
        if c in out:
            return c
    return None


def _parse_localdt(s):
    """模型给的本地时间串 → 带时区 datetime；无效/过去/超一年返回 None。"""
    if not s:
        return None
    s = str(s).strip().replace("T", " ").rstrip("Z")
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{1,2})", s)
    if not m:
        return None
    try:
        y, mo, d, h, mi = (int(x) for x in m.groups())
        dt = datetime.now().astimezone().replace(year=y, month=mo, day=d,
                                                 hour=h, minute=mi, second=0, microsecond=0)
    except ValueError:
        return None
    now = datetime.now().astimezone()
    if dt < now + timedelta(minutes=2) or dt > now + timedelta(days=365):
        return None
    return dt


_WEEKDAY_CN = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_RE_WEEKDAY = re.compile(r"(下)?周([一二三四五六日天])")
_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
_RE_TIME = re.compile(
    r"(上午|早上|早晨|中午|下午|傍晚|晚上|夜里)?\s*([0-9]{1,2}|[一两二三四五六七八九十]+)[点时:：]"
    r"(?:\s*(半|一刻|三刻|([0-9]{1,2}))\s*分?)?")


def _cn2int(s):
    """一~二十三 的中文数字 → int；解析不了返回 None。"""
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if "十" in s:
        a, _, b = s.partition("十")
        if (a and a not in _CN_NUM) or (b and b not in _CN_NUM):
            return None
        return ((_CN_NUM.get(a, 1) if a else 1) * 10) + (_CN_NUM.get(b, 0) if b else 0)
    return _CN_NUM.get(s)


def _extract_hm(text):
    """从文本抽时:分（下午三点/晚上八点半/中午12点/两点半/15:30 都认）。
    只有余上午下午词没有钟点 → 缺省整点（上午9/中午12/下午15/傍晚18/晚上20/夜里21）；
    什么都没有 → 默认上午 9 点。"""
    m = _RE_TIME.search(text)
    if m:
        h = _cn2int(m.group(2))
        minute = {"半": 30, "一刻": 15, "三刻": 45}.get(m.group(3))
        if minute is None:
            minute = int(m.group(4) or 0)
        if h is not None:
            if m.group(1) in ("下午", "晚上", "傍晚", "夜里") and h < 12:
                h += 12
            elif m.group(1) == "中午" and h <= 2:
                h += 12
            if 0 <= h <= 23 and 0 <= minute <= 59:
                return h, minute
        return 9, 0
    ap = next((w for w in ("上午", "早上", "早晨", "中午", "下午", "傍晚", "晚上", "夜里")
               if w in text), None)
    return {"中午": (12, 0), "下午": (15, 0), "傍晚": (18, 0),
            "晚上": (20, 0), "夜里": (21, 0)}.get(ap, (9, 0))


def _resolve_relative_weekday(text, now=None):
    """确定性解析「周X / 下周X」→ 那一天的 datetime。「周X」=下一个该星期几（今天恰是该天取
    7 天后）；「下周X」=下一周该星期几；「上周X」属过去，跳过。返回 (datetime, 命中词)，解析不了
    返回 (None, None)。2026-09-14 A1：qwen3.5:2b 对「周五前」3/3 算错，正则结果优先于模型输出。"""
    now = now or datetime.now().astimezone()
    for m in _RE_WEEKDAY.finditer(text):
        if m.start() > 0 and text[m.start() - 1] == "上":
            continue
        wd = _WEEKDAY_CN[m.group(2)]
        if m.group(1):  # 下周X：先到下周一（今天周一则下周一是 7 天后），再加 wd 天
            day = now + timedelta(days=7 - now.weekday())
            day += timedelta(days=wd)
        else:
            delta = (wd - now.weekday()) % 7
            if delta == 0:
                delta = 7
            day = now + timedelta(days=delta)
        h, mi = _extract_hm(text)
        dt = now.replace(year=day.year, month=day.month, day=day.day,
                         hour=h, minute=mi, second=0, microsecond=0)
        return dt, m.group(0)
    return None, None


def process_note(text, categories):
    """一步到位：归类 + 抽时间承诺。返回 {"category":..|None, "remind_at": iso|None}。"""
    if not text.strip():
        return {"category": None, "remind_at": None}
    now = datetime.now().astimezone()
    wk = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    cats = " / ".join(categories)
    sys_p = (
        "你是记事分析器。对用户记事输出且只输出一行 JSON（不要解释不要代码块）："
        '{"category":"<分类>","remind_at":"<YYYY-MM-DD HH:MM 或 null>"}。'
        "分类必须是这些之一：" + cats + "。"
        "判断：自己要做的事、别人布置/要求你做的事、有截止期限的事 → 待办；"
        "赴约、去取去拿去办 → 待办；"
        "想买、要买、想换、想入手任何东西（电脑壳/手机/吃的用的都算）→ 购物，"
        "注意'想买/想吃'虽然有'想'字但是购物意图不是想法；"
        "点子、看法、方案（不涉及花钱买东西）→ 想法；"
        "文字素材 → 写作素材；已经发生或正在发生的事（含 今天/刚才/了）→ 日常。"
        "只要出现'交/交作业/交报告/deadline/之前完成'等任务词 → 待办。"
        "只有当记事含明确的将来时间或期限（如'明天下午三点''周五前''10点之前'）才给 remind_at，"
        "换算成具体日期时间（期限为'X之前'时设为那个时间点；若已过期则填 null）；没有就填 null。"
        f"现在是 {now.strftime('%Y-%m-%d %H:%M')} {wk}。"
    )
    out = chat([
        {"role": "system", "content": sys_p},
        {"role": "user", "content": text[:200]},
    ], num_predict=80)
    res = {"category": None, "remind_at": None}
    if not out:
        return res
    m = re.search(r"\{[^{}]*\}", out, re.S)
    if not m:
        return res
    try:
        data = json.loads(m.group(0))
    except Exception:
        return res
    cat = data.get("category")
    if cat:
        res["category"] = next((c for c in categories if c in str(cat)), None)
    # 确定性覆盖：出现"买/换新/入手"就是购物意图（1.5b 常被"想"字带偏成想法）
    if "购物" in categories and re.search(r"买|换个新|入手|想吃(?!.*了)", text):
        res["category"] = "购物"
    # 确定性覆盖：正则算出的「周X/下周X」优先于模型输出（2026-09-14 A1，模型对「周五前」3/3 算错）
    wdt, _w = _resolve_relative_weekday(text, now)
    if wdt and wdt > now + timedelta(minutes=2):
        res["remind_at"] = wdt.isoformat(timespec="seconds")
        return res
    dt = _parse_localdt(data.get("remind_at"))
    if dt:
        res["remind_at"] = dt.isoformat(timespec="seconds")
    return res


_ORG_SEP = "\n\n---- ✨ 整理 ----\n\n"


def organize(text, allow_cloud=True):
    """口语原文 → 「要点/疑问」整理块。云 API（DeepSeek）优先、本地兜底。
    私密内容由调用方传 allow_cloud=False（不外发）。失败返回 None。"""
    if not text.strip():
        return None
    messages = [
        {"role": "system", "content": (
            "你是笔记整理助手。严格按下面模板输出，模板结构原样保留，只填内容：\n"
            "【要点】\n- <关键信息短句，每行一个，保留数字/时间/名字>\n"
            "【疑问】\n- <原文里待确认的问题，没有则只写：无>\n"
            "不要输出模板以外的任何字。")},
        {"role": "user", "content": text[:1200]},
    ]
    out = None
    if allow_cloud:
        try:
            import askaway
            cfg = askaway._cfg()
            if cfg.get("enabled") and cfg.get("api_key"):
                out = askaway._cloud_chat(messages, cfg)
        except Exception as e:
            log.info("organize cloud failed: %s", e)
            out = None
    if not out:
        out = chat(messages, num_predict=300)
    if not out:
        return None
    if "要点" not in out:
        return None
    return _ORG_SEP + out.strip()


def digest(notes_texts, scope="day"):
    """把一段时间内的笔记揉成 200 字内回顾。失败返回 None。"""
    if not notes_texts:
        return None
    body = "\n".join("- " + t.replace("\n", " ")[:80] for t in notes_texts[:60])
    label = "今天" if scope == "day" else "本周"
    out = chat([
        {"role": "system",
         "content": f"你是记事回顾助手。把用户{label}的记事揉成一段不超过200字的口语化回顾，"
                    "按主题串起来，突出要做的事和有意思的想法，最后一句给个轻松的收尾。只输出回顾正文。"},
        {"role": "user", "content": body},
    ], num_predict=350)
    return (out or "").strip() or None


_MERGE_SYS = (
    "你是笔记归并助手。用户一次写了很多条零散笔记，其实讲的是同一件事的若干点。\n"
    "请把它们归并成一份结构清晰的汇总笔记，严格按下面格式输出（不要输出格式之外的任何字）：\n"
    "第一行：一句话概括这批笔记共同在讲什么，不超过 30 字，句末不加冒号。\n"
    "空一行。\n"
    "之后每行一条要点，以「- 」开头，短句、保留数字/时间/人名。\n"
    "规则：\n"
    "1) 相同或高度重复的要点必须合并成一条，不要重复罗列；\n"
    "2) 原文没说的不要编，拿不准的宁可略过；\n"
    "3) 不要输出「汇总」「要点」这类标题词，直接给内容；\n"
    "4) 不要用代码块包裹，不要加任何解释。"
)


def merge_organize(src_text, allow_cloud=True):
    """多条笔记 → 一份汇总笔记正文。云 API（DeepSeek）优先、本地兜底。
    失败返回 None。防误判：模型输出过短（<20 字）视为无效。"""
    if not (src_text or "").strip():
        return None
    messages = [
        {"role": "system", "content": _MERGE_SYS},
        {"role": "user", "content": src_text[:4000]},
    ]
    out = None
    if allow_cloud:
        try:
            import askaway
            cfg = askaway._cfg()
            if cfg.get("enabled") and cfg.get("api_key"):
                out = askaway._cloud_chat(messages, cfg)
        except Exception as e:
            log.info("merge cloud failed: %s", e)
            out = None
    if not out:
        out = chat(messages, num_predict=700)
    if not out:
        return None
    out = out.strip()
    if len(out) < 20:
        return None
    return out

