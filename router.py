# -*- coding: utf-8 -*-
"""超级终端意图路由器（动作清单 JSON 协议 v1，契约见 动作清单JSON协议_v1.md）。

三层漏斗：误判记忆表 → 确定性规则 → 本地小模型 → 云 API（>80 字，阈值可调）。
分级执行：轻动作直接执行+可撤销（软删兜底双保险）；重动作出预览确认卡，
**没人确认绝不入库**。兜底铁律：任何一层失败/不认识 → 普通笔记，永不丢内容。
挂在 main 的 FastAPI（server.py）进程内，不新增常驻进程。
"""
import json
import logging
import os
import re
import threading
import time as _time
import datetime

import config
import store

log = logging.getLogger("router")

_BASE = os.path.dirname(os.path.abspath(__file__))
_LOCK = threading.Lock()
_SESSIONS_FILE = os.path.join(_BASE, "data", "terminal_sessions.json")
_MEMORY_FILE = os.path.join(_BASE, "data", "terminal_memory.json")

_MAX_SESSIONS = 100
_SESSION_DAYS = 7

# 界面模块名（§七双轨制：界面名 ≠ 底层字段）
_M_NOTE, _M_LEDGER, _M_COURSE, _M_CONTACT, _M_DIARY, _M_ASK = (
    "笔记", "记账", "课程", "人脉", "日记", "问路远")


def _cfg():
    t = config.load().get("terminal", {})
    return {
        "cloud_threshold": int(t.get("cloud_threshold", 80) or 80),
        "cloud_enabled": bool(t.get("cloud_enabled", True)),
        "undo_seconds": int(t.get("undo_seconds", 5) or 5),
    }


# ---------------- 会话与记忆表（落盘，进程重启可恢复） ----------------

def _load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    for attempt in range(4):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows：目标文件正被别的句柄读着（面板轮询 pending/history）
            # 时 replace 会 PermissionError——重试，最后放弃本轮写也不许 500
            #（sessions/记忆表是缓存性质，丢一次写可接受，崩路由不可接受）
            if attempt == 3:
                log.warning("save_json busy, write skipped: %s", path)
                return
            time.sleep(0.12 * (attempt + 1))


def _sessions():
    return _load_json(_SESSIONS_FILE, {"sessions": {}})


def _prune(data):
    now = _time.time()
    keep = {}
    for tid, s in sorted(data.get("sessions", {}).items(),
                         key=lambda kv: kv[1].get("ts", 0), reverse=True):
        if len(keep) < _MAX_SESSIONS and now - s.get("ts", 0) < _SESSION_DAYS * 86400:
            keep[tid] = s
    data["sessions"] = keep


def _put_session(tid, sess):
    with _LOCK:
        data = _sessions()
        data["sessions"][tid] = sess
        _prune(data)
        _save_json(_SESSIONS_FILE, data)


def _get_session(tid):
    return _sessions().get("sessions", {}).get(tid)


def _update_session(tid, **kw):
    with _LOCK:
        data = _sessions()
        s = data.get("sessions", {}).get(tid)
        if not s:
            return None
        s.update(kw)
        _prune(data)
        _save_json(_SESSIONS_FILE, data)
        return s


# ---------------- 误判记忆表 ----------------

def memory_entries():
    mem = _load_json(_MEMORY_FILE, {})
    return mem


def memory_clear():
    """清空误判记忆表（透明可清承诺的配套）。"""
    with _LOCK:
        _save_json(_MEMORY_FILE, {})
    return {"ok": True, "error": None}


def _memory_hit(text):
    """路由前查表：输入前 20 字前缀匹配 → 记住的意图。"""
    key = (text or "").strip()[:20]
    if not key:
        return None
    mem = _load_json(_MEMORY_FILE, {})
    ent = mem.get(key)
    if ent and ent.get("to"):
        return ent["to"]
    return None


def _memory_record(text, intent):
    """改判入表；同 key 记满 3 次 → promoted（按确定性规则对待）。"""
    key = (text or "").strip()[:20]
    if not key or not intent:
        return
    with _LOCK:
        mem = _load_json(_MEMORY_FILE, {})
        ent = mem.get(key) or {"key": key, "to": intent, "count": 0}
        ent["to"] = intent
        ent["count"] = int(ent.get("count", 0)) + 1
        ent["promoted"] = ent["count"] >= 3
        ent["updated_at"] = datetime.datetime.now().astimezone().isoformat(
            timespec="seconds")
        mem[key] = ent
        _save_json(_MEMORY_FILE, mem)


def _fewshot():
    """历史改判 → few-shot 示例（最多 6 条，注入模型提示词）。"""
    mem = _load_json(_MEMORY_FILE, {})
    out = []
    for ent in sorted(mem.values(), key=lambda x: x.get("count", 0), reverse=True)[:6]:
        out.append('输入"%s" 应分诊为 %s' % (ent.get("key", ""), ent.get("to", "")))
    return out


# ---------------- 时间解析（含「N 分钟后」分钟级——计时器并入提醒的补课） ----------------

_WD = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


def _clock(text):
    """抽时刻 → (hour, minute) 或 None。支持 3点半 / 15:30 / 3点05 / 早上8点。"""
    text = str(text or "")
    # 09-15：中文数字时刻（十点/两点半/下午三点）——「明天上午十点」曾被解析成缺省
    # 9 点（_clock 只认阿拉伯数字）。中文形式借 smart._extract_hm（含上午/下午语义）。
    if re.search(r"[0-9一两二三四五六七八九十]+\s*[点时:：]", text):
        try:
            import smart
            # 「明晚八点/今晚十点/明早七点」：_extract_hm 的前缀表只认 晚上八点/早上七点，
            # 先归一（日期语义由本函数 _day_offset 单独处理，不受影响）
            t2 = text.replace("明晚", "晚上").replace("今晚", "晚上")                       .replace("明早", "早上").replace("今早", "早上")
            h_c, mi_c = smart._extract_hm(t2)
            return h_c, mi_c
        except Exception:
            pass
    m = re.search(r"(?:(\d{1,2})[:：点](\d{1,2})分?|(\d{1,2})点半|(\d{1,2})点)", text)
    if not m:
        return None
    if m.group(1):
        h, mi = int(m.group(1)), int(m.group(2))
    else:
        h = int(m.group(3) or m.group(4))
        mi = 30 if m.group(3) else 0
    if not (0 <= h <= 23 and 0 <= mi <= 59):
        return None
    if re.search(r"下午|晚上|今晚|明晚|傍晚", text) and h < 12:
        h += 12
    elif re.search(r"上午|早上|清晨|凌晨|明早", text) and h == 12:
        h = 0
    return h, mi


def _day_offset(text, now):
    if re.search(r"大后天", text):
        return 3
    if re.search(r"后天", text):
        return 2
    if re.search(r"明天|明早|明晚|明日", text):
        return 1
    if re.search(r"今天|今晚|今晚|今日|现在|马上|待会|晚点", text):
        return 0
    m = re.search(r"(\d{1,2})月(\d{1,2})[日号]", text)
    if m:
        try:
            d = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                            hour=9, minute=0, second=0, microsecond=0)
            if d < now:
                d = d.replace(year=d.year + 1)
            return d
        except ValueError:
            return None
    m = re.search(r"[周礼拜星期]([一二三四五六日天])", text)
    if m:
        target = _WD.get(m.group(1))
        if target is not None:
            delta = (target - now.weekday()) % 7
            return delta
    return None


_DEFAULT_CLOCK = {"早上": (8, 30), "上午": (9, 0), "中午": (12, 0),
                  "下午": (15, 0), "晚上": (20, 0), "今晚": (20, 0)}


def _clean_name(raw):
    """建档人名清洗：去掉时间词/手机号残渣/口语助词。"""
    s = re.sub(r"(今天|昨天|刚刚?|刚才|下午|上午|晚上|早上|中午)", " ", raw)
    s = re.sub(r"\s+", "", s)
    return s.strip(" ，,。、。了一下的和跟与我你他她")


def parse_time(text, now=None):
    """从一句话抽将来时间 → ISO8601 或 None。绝不给过去时间（过去+无明确日期=顺延一天）。"""
    text = str(text or "")
    now = now or datetime.datetime.now().astimezone()
    # 相对时长：N分钟后 / 半小时后 / N(个)小时后 / N天后
    m = re.search(r"(\d+(?:\.\d+)?)\s*分钟[之后]{1,2}", text)
    if m:
        return (now + datetime.timedelta(minutes=float(m.group(1)))).isoformat(
            timespec="seconds")
    if re.search(r"半小时[之后]{1,2}", text):
        return (now + datetime.timedelta(minutes=30)).isoformat(timespec="seconds")
    m = re.search(r"(\d+(?:\.\d+)?)\s*个?小时[之后]{1,2}", text)
    if m:
        return (now + datetime.timedelta(hours=float(m.group(1)))).isoformat(
            timespec="seconds")
    m = re.search(r"(\d+)\s*天[之后]{1,2}", text)
    if m:
        d = (now + datetime.timedelta(days=int(m.group(1)))).replace(
            hour=9, minute=0, second=0, microsecond=0)
        return d.isoformat(timespec="seconds")
    clock = _clock(text)
    off = _day_offset(text, now)
    deadline = bool(re.search(r"(之前|以前|之内|以内)", text)
                    or re.search(r"[周礼拜星期][一二三四五六日天]\s*前", text))
    if isinstance(off, datetime.datetime):   # 「X月X日」直接给了完整日期
        if clock:
            off = off.replace(hour=clock[0], minute=clock[1])
        return off.isoformat(timespec="seconds")
    if off is None:
        if clock is None:
            return None
        base = now.replace(second=0, microsecond=0)
        dt = base.replace(hour=clock[0], minute=clock[1])
        if dt < now + datetime.timedelta(minutes=2):   # 裸时刻已过 → 明天同时刻
            dt += datetime.timedelta(days=1)
        return dt.isoformat(timespec="seconds")
    day = now + datetime.timedelta(days=off)
    if clock:
        hour, mi = clock
    else:
        hour, mi = 9, 0
        for word, (h, mm) in _DEFAULT_CLOCK.items():
            if word in text:
                hour, mi = h, mm
                break
    if deadline and clock is None:
        hour, mi = 21, 0   # 「周X前」这类期限，默认当天 21:00 提醒还来得及
    dt = day.replace(hour=hour, minute=mi, second=0, microsecond=0)
    return dt.isoformat(timespec="seconds")


# ---------------- 确定性规则层（强信号，不赌模型） ----------------

_URL_RE = re.compile(r"(https?://|www\.)\S+", re.I)
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_AMT_SYM_RE = re.compile(r"[¥￥]\s*(\d+(?:\.\d{1,2})?)")
_AMT_YUAN_RE = re.compile(r"(\d+(?:\.\d{1,2})?)\s*(元|块|块钱)")
_AMT_HUA_RE = re.compile(r"花了\s*(\d+(?:\.\d{1,2})?)")
_TODO_STRONG_RE = re.compile(
    r"提醒我|别忘了|要交|去取|去拿|交作业|赴约|预约|"
    r"帮(.{1,6}?)(带|买|取|送|交|拿|订)|替(.{1,6}?)(带|买|取|送|交|拿|订)")
_TODO_WEAK_RE = re.compile(r"记得|待办|别忘")
_ASK_RE = re.compile(r"^(帮我查|帮我搜|问一下|问问|路远[，,]?)")
_CONTACT_UP_RE = re.compile(r"(.+?)的?(生日|电话|手机号|号码|微信号?|QQ|qq)是\s*(.+)")
_CONTACT_NEW_RE = re.compile(r"认识了|认识一下|新同学|新同事|加个?(好友|微信|联系方式)")
_DIARY_RE = re.compile(r"^(记?日记|写日记|日记)[：:，,。\s]")
_PERSONAL_FACT_RE = re.compile(
    r".{1,8}?(喜欢|爱吃|爱喝|讨厌|不吃|过敏|害怕|怕辣)")
_TAG_RE = re.compile(r"#([^\s#]+)")

# ---------------- 微信回复指令解析（零触控语音回消息，Stage 1） ----------------
# 口语说法都要认。2026-09-13 用户实测「回一下路平坦成河说我下午有事」没触发
# （只存成了待办）——老正则只认「回X：正文」，衬词「一下」和引导语「说」都没处理。
# 现在覆盖：
#   回他：书在图书馆三楼          → 发给当前打开的聊天
#   回他一下，书在图书馆三楼       → 同上（认衬词）
#   回复张三：下午两点来领书       → Ctrl+F 搜「张三」开聊天再发
#   回一下张三说我下午去找他       → 名字 + 引导语「说」，正文=我下午去找他
#   回复张三，告诉他下午来找我      → 名字 + 引导语，正文=下午来找我
#   回刚才那个：收到了            → 发给最近看的聊天
#
# ⚠️ 安全取舍：**名字必须有明确边界**（标点分隔符 or 引导语「说/告诉/讲」，或
#   名字本身是已存联系人）。没有边界时宁可判为「不是微信指令」落笔记，
#   也不猜名字——猜错名字 = Ctrl+F 搜错人 = 消息发给错的人。
# 衬词（「回他一下」「发给李四一声」）。⚠️「一下」要排除「一下午」（后者是时间词，
#   不是衬词：「回他一下午开会」的正文该是「一下午开会」）。
_FILLER_PAT = r"(?:一下子|一下(?!午)|一声|一句|一个|一条|个|条)"

# 引导语（「说/讲/告诉/跟他说」）——名字与正文之间的分界标记
_WECHAT_LEAD_PAT = r"(?:跟(?:他|她|你)?说|告诉(?:他|她)?|说|讲)"

# 🔴 动词分强/弱两类，安全性不同：
#   强动词 = 本身就是「发消息」语义（回复/回/发给/发消息给…）→ 名字是收件人，可走全部通道。
#   弱动词 = 「给/跟/帮/替」在日常句里极常见（「给妈妈买药」「给老师交作业」「给车加油」），
#            → **只在名字有明确边界、且名字命中已存联系人**时才认，否则宁可落笔记。
_WECHAT_VERB_STRONG_RE = re.compile(
    r"^(?:回(?:个|条)?(?:消息|微信)给|转发给|回复|回|发(?:个|条)?(?:消息|微信)?给|微信发给)\s*"
    + _FILLER_PAT + r"?\s*")
#   弱动词后面常跟「我」（帮我/替我/给我）——「我」不是收件人，要一起剥掉，
#   否则「帮我回路平坦成河说…」会把名字解析成「我回路平坦成河」= 搜错人。
_WECHAT_VERB_WEAK_RE = re.compile(
    r"^(?:给|跟|帮|替)\s*(?:我|你)?\s*(?:一下子|一下(?!午)|一声|一句)?\s*")
# 仅用于「说了类似动词但没解析出来」的留痕日志，不进判定
_WECHAT_VERB_RE = re.compile(r"^(?:回复|回|发|给|跟|帮|替)")

# 出现这些词就值得问一下本地模型「这是不是要发微信」（宽一点没关系，宁可多问一句，
# 也比把用户「说一嘴」的话默默记成待办、消息压根没发出去强）。
_WECHAT_HINT_RE = re.compile(
    r"(回复|回一下|回他|回她|发消息|发微信|发个消息|发给|转告|转达|捎个话|捎句话"
    r"|说一声|告诉|跟(?!着)|给|帮"
    # A2 根因补丁（09-14）：间接转告句「让X知道…」「X那边回一句…」原先一个 HINT 词
    # 都不含 → 根本轮不到模型通道，2b 与云端全被跳过（全链路实测 0.0s 实锤）。
    # 「让」排除「让我/让你」（高频口语，不值得为它多烧一次模型）。
    r"|让(?!我|你)|那边)")

_WECHAT_LAST_RE = re.compile(
    r"^(?:刚才那个|刚那个|上一条|未读|刚才|最近那位|最近|上一个)\s*"
    + _WECHAT_LEAD_PAT + r"?\s*[：:，,]?\s*(.*)$")
_WECHAT_PRONOUN_RE = re.compile(
    r"^(他|她|它)\s*" + _FILLER_PAT + r"?\s*" + _WECHAT_LEAD_PAT + r"?\s*[：:，,]?\s*(.*)$")
# 弱动词版：引导语或标点必须出现其一，否则「给她打电话」「给他发个红包」会被当成正文发出去
_WECHAT_WEAK_PRONOUN_RE = re.compile(
    r"^(他|她|它)\s*" + _FILLER_PAT + r"?\s*"
    r"(?:" + _WECHAT_LEAD_PAT + r"\s*[：:，,]?|[：:，,。]\s*)\s*(.*)$")
# 名字 + 标点分隔符：回复张三：正文 / 回复张三，正文
_WECHAT_NAME_SEP_RE = re.compile(r"^([^：:，,。\s]{1,16}?)\s*([：:，,。])\s*(.*)$")
# 名字 + 引导语（无标点）：回一下张三说我下午有事
_WECHAT_NAME_LEAD_RE = re.compile(
    r"^([^：:，,。\s]{1,16}?)\s*" + _WECHAT_LEAD_PAT + r"\s*[：:，,]?\s*(.*)$")
# 正文里残留的引导语（「回复张三，说下午有事」→ 正文该是「下午有事」）
_WECHAT_LEAD_STRIP = re.compile(r"^" + _WECHAT_LEAD_PAT + r"\s*[：:，,]?\s*")

# 这些不是人名，避免「回复邮件」「回学校」被当成发微信
_WECHAT_NOT_NAME = {"邮件", "短信", "消息", "电话", "群", "群消息", "学校",
                    "宿舍", "家", "图书馆", "教室", "公司", "食堂", "车",
                    "去", "来", "个", "备注", "文件", "他", "她", "它"}

_CONTACT_NAMES = {"ts": 0.0, "names": []}


def _contact_names():
    """联系人名字列表（30 秒缓存，避免每次解析都读一遍目录）。"""
    now = _time.time()
    if now - _CONTACT_NAMES["ts"] < 30 and _CONTACT_NAMES["names"]:
        return _CONTACT_NAMES["names"]
    try:
        import contacts
        names = [c.get("name", "") for c in contacts.list_contacts()
                 if c.get("name") and len(c.get("name", "")) >= 2]
    except Exception:
        names = []
    _CONTACT_NAMES["names"] = names
    _CONTACT_NAMES["ts"] = now
    return names


# 正文只由衬词构成（「给张三说一下」）→ 视为没正文，绝不发一条「一下」出去
_WECHAT_BODY_FILLER = re.compile(r"^" + _FILLER_PAT + r"$")
# 正文前缀残留的衬词（「给老师说一声我明天不来」→「我明天不来」）
_WECHAT_BODY_PREFIX = re.compile(r"^(?:一下子|一下(?!午)|一声|一句)")


def _clean_body(b):
    b = (b or "").strip().lstrip("：:，,。、 ").strip()
    b = b.rstrip("：:，,。、 ").strip()
    if _WECHAT_BODY_FILLER.match(b):
        return ""
    b = _WECHAT_BODY_PREFIX.sub("", b, count=1).strip()
    return b


# 名字尾部残留的衬词（「发给李四一下：…」→ 名字该是「李四」）
# ⚠️ 名字别叫 `_clean_name`——上面 219 行那个同名函数是「联系人建档」用的
#    （会剥「今天/昨天/手机号残渣」），覆盖它会让建档名字变成「今天王雨琪」
#    （2026-09-13 实测踩坑，test_v137 两条挂）。
_WECHAT_NAME_TAIL_FILLER = re.compile(r"(?:一下|一下子|一声|一句|一个|一条)$")

# 名字尾部粘着的引导语/中缀动词（09-14 对抗实测：「给妈妈说：X」→「妈妈说」、
# 「给张三发个消息说X」→「张三发个消息」、「回复路平坦成河的微信：X」→「路平坦成河的微信」）。
# 剥整词（只剥单字「说」会把「跟他说」剥成「跟他」）；剥完不足 2 字 → 名字不可信，
# 整体判 None 落笔记。
_WECHAT_NAME_TAIL_LEAD = re.compile(
    r"(?:跟(?:他|她|你)?说|告诉(?:他|她)?"
    r"|发(?:个|条)?(?:消息|微信)?说|发(?:个|条)?(?:消息|微信)"
    r"|的微信|的消息|留言"
    r"|说|讲)$")

# 名字含多人连接词 → 收件人不确定（「跟张三李四都说到了」），宁可落笔记也不搜错人
_WECHAT_MULTI_NAME = re.compile(r"(?:和|与|以及|还有|都|跟|同)")

# 倒装句「把X告诉Y」：正文在前、收件人在后（「帮我把明天开会的事告诉张三」→ 发给张三「明天开会的事」）。
# 「帮我/替我」已被弱动词剥掉，rest 以「把」开头才进来。
_WECHAT_TELL_BACK_RE = re.compile(
    r"^把(?P<body>.{2,60}?)告诉(?:给|跟)?(?P<name>[^：:，,。\s]{2,12}?)"
    r"(?P<tail>说是|说|[：:，,。]|$)\s*(?P<rest>.*)$")


def _clean_wechat_name(n):
    n = (n or "").strip()
    for _ in range(2):
        n2 = _WECHAT_NAME_TAIL_FILLER.sub("", n)
        if n2 == n:
            break
        n = n2
    for _ in range(2):
        n2 = _WECHAT_NAME_TAIL_LEAD.sub("", n)
        if n2 == n:
            break
        n = n2
    return n.strip()


def parse_wechat(text):
    """解析『回复X：正文』指令（含口语变体）。返回 (to, body) 或 None。

    to='current' 表示发给当前打开的聊天；'last' 同 current（最近看的聊天）；
    否则为联系人名。无内容 / 不像指令 / 名字是已知非人名词 → 返回 None（走普通笔记）。

    支持的动词：
      强：回复 / 回 / 发给 / 发消息给 / 发微信给 / 回消息给 / 转发给 → 「回复张三：…」「回他…」
      弱：给 / 跟 / 帮 / 替                    → 「给路平坦成河说我下午去图书馆」
      倒装：把X告诉Y（可带「帮我/替我」前缀）  → 「把停课通知告诉张三」
    弱动词额外两条安全约束（见 _ok）：名字必须有明确边界 **且** 命中已存联系人。
    """
    t = str(text or "").strip()
    if not t:
        return None
    # 动词会叠着说：「帮我回X说Y」= 弱动词「帮我」+ 强动词「回」；「给我发给X」同理。
    # 循环剥（最多 2 层），剥到不能再剥为止；一层都没剥到 → 不是指令。
    weak = False
    rest = t
    hit = False
    for _ in range(2):
        m = _WECHAT_VERB_STRONG_RE.match(rest)
        if not m:
            m = _WECHAT_VERB_WEAK_RE.match(rest)
            if m:
                weak = True
            else:
                break
        hit = True
        rest = rest[m.end():].strip()
    if not rest:
        return None

    def _ok(name, body):
        """收尾校验：名字与正文都得在，且名字不是已知非人名词/多人连接词。"""
        if not name or not body or name in _WECHAT_NOT_NAME:
            return None
        if _WECHAT_MULTI_NAME.search(name):
            return None
        return name, body

    def _tell_back():
        """倒装「把X告诉Y」：正文在前、收件人在后。返回 (to, body) 或 None。"""
        m3 = _WECHAT_TELL_BACK_RE.match(rest)
        if not m3:
            return None
        name = _clean_wechat_name(m3.group("name"))
        body = m3.group("body")
        tail, tail_rest = m3.group("tail"), m3.group("rest") or ""
        if tail not in ("说是", "说") and tail and tail_rest:
            body = body + tail + tail_rest   # 「…告诉张三：他请假了」正文补全
        return _ok(name, _clean_body(body))

    if not hit:
        # 「把X告诉Y」倒装本身是完整指令（无动词前缀也认：「把停课通知告诉张三」）
        r = _tell_back()
        return r

    # ① 刚才那个 / 上一条 / 未读 → 发给最近看的聊天
    m2 = _WECHAT_LAST_RE.match(rest)
    if m2:
        body = _clean_body(m2.group(1))
        return ("last", body) if body else None

    # ② 他 / 她 / 它 → 发给当前打开的聊天
    #    弱动词用严格版：必须有引导语或标点，否则「给她打电话」会把「打电话」当正文发出去
    m2 = (_WECHAT_WEAK_PRONOUN_RE if weak else _WECHAT_PRONOUN_RE).match(rest)
    if m2:
        body = _clean_body(m2.group(2))
        if body:
            return ("current", body)

    # ③ 名字 + 标点分隔符：回复张三：正文 / 回复张三，正文
    m2 = _WECHAT_NAME_SEP_RE.match(rest)
    if m2:
        name = _clean_wechat_name(m2.group(1))
        # 名字尾部粘着的引导语剥掉：「给妈妈说：明天开会」→「妈妈」。
        # 剥后不足 2 字（如名字整段都是引导语）→ 不可信，宁可落笔记。
        name2 = _WECHAT_NAME_TAIL_LEAD.sub("", name)
        if name2 != name and len(name2) < 2:
            return None
        if name2:
            name = name2
        sep, body = m2.group(2), m2.group(3)
        if sep in "，,。、":
            # 「回复张三，说下午有事」→ 逗号后的「说」是引导语，不是正文
            body = _WECHAT_LEAD_STRIP.sub("", body, count=1)
        r = _ok(name, _clean_body(body))
        if r:
            return r

    # ④′ 倒装「把X告诉Y」先行于④（带动词前缀）：「帮我把明天开会的事告诉张三」——
    #     不先试倒装的话，④会把「把明天开会的事」当名字、「张三」当正文。
    #     （无动词前缀的倒装已在函数开头的 not hit 分支处理。）
    m2 = _WECHAT_TELL_BACK_RE.match(rest)
    if m2:
        r = _tell_back()
        if r:
            return r

    # ④ 名字 + 引导语（无标点）：回一下张三说我下午有事 / 给路平坦成河说我下午要去图书馆
    m2 = _WECHAT_NAME_LEAD_RE.match(rest)
    if m2:
        name = _clean_wechat_name(m2.group(1))
        r = _ok(name, _clean_body(m2.group(2)))
        if r:
            return r

    # ⑤ 无标点也无引导语 → 只认「已存联系人」的最长前缀（安全兜底，绝不瞎猜名字）
    #    ⚠️ 弱动词禁用此通道：「给妈妈买药」会命中联系人「妈妈」+ 正文「买药」→ 误发消息。
    if not weak:
        best = ""
        for n in _contact_names():
            if rest.startswith(n) and len(n) > len(best):
                best = n
        if best:
            body = _clean_body(rest[len(best):])
            if body:
                return best, body
    return None


# ---------------- 收件人名同音纠正（STT 错字对齐联系人库） ----------------
def _resolve_wechat_name(to):
    """把解析出的收件人名向联系人库对齐，返回纠正后的名字。

    🔴 背景（09-14 路河点名）：语音「张俊扬」被 STT 转成「张俊杨」这类同音错字，
    名字对不上 → 微信搜索零结果 → 回车落到不确定位置。只在「名字不在联系人库」
    时介入，三级纠错：
      ① 全拼同音且字数相同 → 替换为库内名字（张俊扬→张俊杨）
      ② 拼音前缀 ≥3 字同音且长度差 ≤2 → 替换（陆平坦乘客→路平坦成河，STT 整词听错）
      ③ RapidFuzz 相似度 ≥87 → 替换（近音错字兜一层）
      ④ 都不中 → 原名返回（交给搜索读回校验 / OCR 验证去拦，绝不瞎换人）
    """
    if not to or to in ("current", "last"):
        return to
    names = _contact_names()
    if not names or to in names:
        return to
    try:
        from pypinyin import lazy_pinyin
        to_py = "".join(lazy_pinyin(to))
        for n in names:
            if len(n) == len(to) and "".join(lazy_pinyin(n)) == to_py:
                log.info("wechat name homophone: %r -> %r", to, n)
                return n
        # ③ 拼音前缀同音：STT 把「路平坦成河」听成「陆平坦乘客」（09-13 实录）——
        #    字数还变了。逐字同音比对，≥2 字同音且候选唯一才纠（库内真实重名时
        #    保持原名不赌）；纠正方向永远朝已存联系人。
        to_py_seq = lazy_pinyin(to)
        # 前缀同音候选：≥2 字同音（09-15 增强：「张俊龙」→「张俊杨」前 2 字同音。
        # 误纠防线=候选唯一才纠——同前缀命中多个联系人时保持原名不赌。
        prefix_hits = []
        for n in names:
            n_py = lazy_pinyin(n)
            same = 0
            for a, b in zip(n_py, to_py_seq):
                if a != b:
                    break
                same += 1
            if same >= 2 and abs(len(n) - len(to)) <= 2:
                prefix_hits.append((same, n))
        if prefix_hits:
            prefix_hits.sort(reverse=True)
            best_same, best_n = prefix_hits[0]
            uniq = [n for s, n in prefix_hits if s == best_same]
            if len(uniq) == 1:
                log.info("wechat name py-prefix: %r -> %r (%d 字同音前缀)", to, best_n, best_same)
                return best_n
        try:
            from rapidfuzz import fuzz
            best, best_score = None, 0.0
            for n in names:
                s = fuzz.ratio(n, to)
                if s > best_score:
                    best, best_score = n, s
            if best and best_score >= 87.0:
                log.info("wechat name fuzz: %r -> %r (%.0f)", to, best, best_score)
                return best
        except Exception:
            pass
    except Exception as e:
        log.info("wechat name resolve err: %s", e)
    return to


def parse_wechat_resolved(text):
    """parse_wechat + 收件人名同音纠正。发送链路一律走这个入口。"""
    r = parse_wechat(text)
    if not r:
        return None
    return _resolve_wechat_name(r[0]), r[1]


# ---------------- 消息指令：本地模型兜底判定 ----------------
# 为什么不只用正则：语音口语的动词/语序/衬词组合是开放集合，规则永远追不完。
# 2026-09-13 一天内连踩两次（先漏衬词「一下」，再漏动词「给」），所以改成
# 「正则确定 → 快发；正则拿不准 → 问本地模型」。模型判定失败/离线 → 落笔记（绝不瞎发）。
_WECHAT_LLM_PROMPT = """你是「路远」的消息指令解析器。判断用户这句话是不是【要发一条微信消息给某个人】。

是 → 输出 {"send": true, "to": "收件人名字", "text": "要发出去的正文"}
    收件人是代词（他/她/当前聊天）→ "to": "current"；最近聊过的那位 → "to": "last"
不是（自己记笔记、记账、安排自己的事、让别人干别的）→ 输出 {"send": false}

例子：
给路平坦成河说我下午要去图书馆 → {"send": true, "to": "路平坦成河", "text": "我下午要去图书馆"}
回一下张三说我下午去找他 → {"send": true, "to": "张三", "text": "我下午去找他"}
帮我跟他说一声我晚点到 → {"send": true, "to": "current", "text": "我晚点到"}
跟刚才那个说收到了 → {"send": true, "to": "last", "text": "收到了"}
让路平坦成河知道明天不用等我 → {"send": true, "to": "路平坦成河", "text": "明天不用等我"}
路平坦成河那边回一句说我马上到 → {"send": true, "to": "路平坦成河", "text": "我马上到"}
给妈妈买药 → {"send": false}
跟老师请假 → {"send": false}
给车加油 → {"send": false}
明天下午三点开会 → {"send": false}

只输出一行 JSON，不要解释。用户的话："""


def _llm_wechat_judge(text, timeout=12):
    """本地模型判定「这句是不是要发微信」。返回 (to, body) 或 None。

    🔴 防幻觉两道闸：① 模型给的收件人名字必须真的在原文里出现（编的名字一律丢）；
    ② 正文不能为空。两道任一不过 → 返回 None（落笔记，绝不发错人）。
    """
    try:
        import smart
        if not smart.ollama_running():
            log.info("wechat llm skipped: ollama not running")
            return None
        out = smart.chat(
            [{"role": "user", "content": _WECHAT_LLM_PROMPT + text[:120]}],
            timeout=timeout, num_predict=100, temperature=0)
    except Exception as e:
        log.info("wechat llm failed: %s", e)
        return None
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("send"):
        return None
    to = str(data.get("to") or "").strip()
    body = _clean_body(str(data.get("text") or ""))
    if not body:
        return None
    if to in ("current", "last", "他", "她", "它", "当前聊天"):
        # 🔴 代词也必须在原文出现才算数：小模型会把纯笔记（「明天下午三点开会」）
        #    误判成「发给最近聊天」，靠这条拦住。
        if to == "last":
            if re.search(r"(刚才|最近|上一条|未读|上一个)", text):
                return ("last", body)
            log.info("wechat llm: says last but no 刚才/最近 in text, dropped")
            return None
        if re.search(r"(他|她|它|当前|这个聊天|这个群)", text):
            return ("current", body)
        log.info("wechat llm: says current but no pronoun in text, dropped")
        return None
    if to and to not in _WECHAT_NOT_NAME and to in text:
        log.info("wechat llm -> %s | %s", to, body[:40])
        return to, body
    log.info("wechat llm: name %r not found in original text, dropped", to)
    return None


# ---------------- 消息指令：DeepSeek 云端二审（本地 2b 判 None 之后再问一次云） ----------------
# 为什么：qwen3.5:2b 对「让X知道…」「X那边回一句…」这类间接转告句批量失灵（A2），
# 正则又明令不许加。路河拍板：本地判 None 的疑似微信句走 DeepSeek（deepseek-v4-flash）
# 二审，成本不设限；云端结果必须过与本地一致的防幻觉双闸，不过闸照样落笔记。
_WECHAT_CLOUD_PROMPT = """你是消息指令解析器。判断这句话是不是【要让某个人收到一条消息】（发微信/QQ/短信，直接说或间接转告都算）。

是 → 输出 {"send": true, "to": "收件人名字", "text": "要发出去的正文"}
    收件人是代词（他/她/当前聊天）→ "to": "current"；最近聊过的那位 → "to": "last"
不是 → 输出 {"send": false}

间接转告也算：「让X知道Y」「X那边回一句说Y」「帮我转告X：Y」「跟X捎个话Y」。
只是自己记笔记、安排自己的事、让别人做消息以外的事 → {"send": false}。

例子：
让路平坦成河知道明天不用等我 → {"send": true, "to": "路平坦成河", "text": "明天不用等我"}
路平坦成河那边回一句说我马上到 → {"send": true, "to": "路平坦成河", "text": "我马上到"}
帮我转告张三晚上聚餐 → {"send": true, "to": "张三", "text": "晚上聚餐"}
给妈妈买药 → {"send": false}
跟老师请假 → {"send": false}
明天下午三点开会 → {"send": false}

只输出一行 JSON，不要解释。用户的话："""

# 间接转告句识别（云端直通门槛）：命中 = 跳过 2b 直接问 DeepSeek。
# 为什么跳：实测 2b 对这类句式单句烧 4-16s 仍判 None（09-14 夜测），云端 ~2s 且准。
# 「帮我跟他说一声」这类 2b 的强项句不在此列（不劫持，仍走本地快路）。
_WECHAT_INDIRECT_RE = re.compile(r"(让.{0,8}知道|那边|转告|转达|捎个?话|带个?话)")


def _cloud_wechat_judge(text, timeout=8):
    """DeepSeek 云端二审。返回 (to, body) 或 None。

    🔴 双闸与本地一致：① 收件人名/代词必须在原文出现（防编造）；② 正文非空。
    云端不可达/超时/不过闸 → None（落笔记，绝不瞎发）。命中时收件人名过同音纠正。
    """
    try:
        import askaway
        cfg = askaway._cfg()
        if not cfg.get("api_key") or not cfg.get("enabled"):
            return None
        out = askaway._cloud_chat(
            [{"role": "user", "content": _WECHAT_CLOUD_PROMPT + text[:120]}],
            {**cfg, "timeout": timeout}, temperature=0)
    except Exception as e:
        log.info("wechat cloud judge failed: %s", e)
        return None
    m = re.search(r"\{.*\}", out or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("send"):
        return None
    to = str(data.get("to") or "").strip()
    body = _clean_body(str(data.get("text") or ""))
    if not body:
        return None
    if to in ("current", "last", "他", "她", "它", "当前聊天"):
        if to == "last":
            if re.search(r"(刚才|最近|上一条|未读|上一个)", text):
                return ("last", body)
            return None
        if re.search(r"(他|她|它|当前|这个聊天|这个群)", text):
            return ("current", body)
        return None
    if to and to not in _WECHAT_NOT_NAME and to in text:
        log.info("wechat cloud -> %s | %s", to, body[:40])
        return _resolve_wechat_name(to), body
    log.info("wechat cloud: name %r not found in original text, dropped", to)
    return None


def _wechat_to_label(to):
    return "当前聊天" if to in ("current", "last") else to


def _rules_route(text):
    """返回 (intent, fields, note_tags) 或 None。全部强信号，命中即定。"""
    # 语法糖：#标签 先摘下来；!! 前缀 = 重要
    tags = [t for t in _TAG_RE.findall(text) if len(t) <= 12][:4]
    bare = _TAG_RE.sub("", text).strip()
    if bare.startswith("!!"):
        tags.append("重要")
        bare = bare[2:].strip()

    # 微信回复指令（零触控语音回消息，Stage 1）：
    #   ① 正则能确定 → 走快速路径（0 延迟，发出去不等待）
    #   ② 正则拿不准 → 交给本地模型判定（语音口语变体太多，规则不可能穷举）
    #   注：把「说一句就发」做成了两步——正则管快、模型管懂。实测多次证明规则追不上口语
    #   （先漏「一下」，后又漏动词「给」），所以可疑句一律过模型，不再靠正则硬猜。
    wcmd = parse_wechat(bare)
    if wcmd is None and len(bare) <= 60 and _WECHAT_HINT_RE.search(bare):
        # 判定引擎选择（A2 交付，路河可改 config.wechat.judge_mode，改文件即生效）：
        #   auto（默认）= 间接转告句直上云端（2b 对它们又慢又瞎），其余走本地 2b
        #   always      = 疑似句全走云端（又快又准，代价=全部出网，见 A2 对照报告）
        #   local       = 只用本地（离线优先；云端不参与）
        mode = "auto"
        try:
            mode = (config.load().get("wechat", {}) or {}).get("judge_mode", "auto")
        except Exception:
            pass
        if mode == "always":
            wcmd = _cloud_wechat_judge(bare)
            if wcmd is None:
                wcmd = _llm_wechat_judge(bare)
        elif mode == "local":
            wcmd = _llm_wechat_judge(bare)
        elif _WECHAT_INDIRECT_RE.search(bare):
            wcmd = _cloud_wechat_judge(bare)
        else:
            wcmd = _llm_wechat_judge(bare)
    if wcmd is not None:
        return "wechat_reply", {"to": _resolve_wechat_name(wcmd[0]), "text": wcmd[1]}, tags
    if _WECHAT_VERB_RE.match(bare):
        # 类微信动词出现但正则+模型都没认出 → 留一行日志便于排查
        log.info("wechat verb seen but not parsed (rule+llm), fallback to note: %s",
                 bare[:40])

    # 问句 → 问路远（交接给 /api/ask，路由器不代跑不堵路）
    if bare.startswith("？") or bare.startswith("?") or _ASK_RE.match(bare):
        q = re.sub(r"^[?？]+|^(帮我查|帮我搜|问一下|问问|路远[，,]?)\s*", "", bare).strip()
        return "ask", {"q": q or bare}, tags

    # URL → 稍后读
    if _URL_RE.search(bare):
        return "read_later", {"text": bare}, (tags + ["稍后读"])

    # 金额 → 记账
    m = (_AMT_SYM_RE.search(bare) or _AMT_YUAN_RE.search(bare)
         or _AMT_HUA_RE.search(bare))
    if m:
        try:
            amount = float(m.group(1))
        except ValueError:
            amount = None
        if amount is not None and 0 < amount < 1000000:
            try:
                import expenses
                s = expenses.summarize(bare) or {}
            except Exception:
                s = {}
            item = s.get("item") or _AMT_SYM_RE.sub("", _AMT_YUAN_RE.sub("", bare)).strip(" ，,。的") or "（未命名）"
            item = re.sub(r"花了", "", item)
            item = re.sub(r"(今天|昨天|刚刚?|刚才)", "", item)
            item = item.replace("块钱", "").replace("块", "").replace("元", "")
            item = item.strip(" ，,。的") or "（未命名）"
            return "expense", {"amount": amount, "item": item[:40],
                               "category": s.get("category")}, tags

    # 联系人档案更新：「X的生日是…」
    m = _CONTACT_UP_RE.search(bare)
    if m:
        name = m.group(1).strip(" ，,。我和")
        field = {"生日": "birthday", "电话": "phone", "手机号": "phone",
                 "号码": "phone", "微信": "wechat", "微信号": "wechat",
                 "QQ": "qq", "qq": "qq"}.get(m.group(2), "note")
        value = m.group(3).strip(" ，,。")
        return "contact_update", {"name": name[:20], "field": field,
                                  "value": value[:80]}, tags

    # 新建联系人：「认识了X」
    if _CONTACT_NEW_RE.search(bare):
        name = _CONTACT_NEW_RE.sub("", bare)
        pm = _PHONE_RE.search(bare)
        if pm:
            name = name.replace(pm.group(0), " ")
        fields = {"name": _clean_name(name)[:20] or "（没说名字）"}
        if pm:
            fields["phone"] = pm.group(0)
        return "contact_create", fields, tags

    # 显式记日记
    if _DIARY_RE.match(bare):
        body = _DIARY_RE.sub("", bare).strip()
        if body:
            return "diary", {"text": body}, tags

    # 个人信息陈述：「X喜欢吃辣/X对花生过敏」→ 笔记+个人信息标签。
    #（09-11 事故：'王国钦喜欢吃辣' 曾被模型层判成 expense，无金额 → 记账失败）
    if (len(bare) <= 40 and not _TODO_STRONG_RE.search(bare)
            and _PERSONAL_FACT_RE.search(bare)):
        return "note", {"text": bare}, list(dict.fromkeys(tags + ["个人信息"]))

    # 循环提醒语法糖：「每天HH:MM XXX」→ 每日待办（repeat=daily，触发后自动排明天）
    if re.match(r"^每[天日]", bare):
        clock = _clock(bare)
        if clock:
            now = datetime.datetime.now().astimezone()
            dt = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
            if dt < now + datetime.timedelta(minutes=1):
                dt += datetime.timedelta(days=1)   # 今天的时刻已过 → 从明天开始
            body = re.sub(r"^每[天日]\s*(早上|上午|中午|下午|晚上|今晚)?\s*", "", bare).strip()
            return "todo", {"text": body or bare, "tags": ["待办", "每日"],
                            "remind_at": dt.isoformat(timespec="seconds"),
                            "repeat": "daily"}, tags
        # 「每天」但没说时刻 → 不硬猜，交给模型层

    # 每周循环提醒语法糖：「每周X HH:MM XXX」→ 每周待办（repeat=weekly）
    m_weekly = re.match(r"^每周([一二三四五六日天])", bare)
    if m_weekly:
        target = _WD.get(m_weekly.group(1))
        clock = _clock(bare)
        if target is not None and clock:
            now = datetime.datetime.now().astimezone()
            delta = (target - now.weekday()) % 7
            dt = (now + datetime.timedelta(days=delta)).replace(
                hour=clock[0], minute=clock[1], second=0, microsecond=0)
            if dt < now + datetime.timedelta(minutes=1):
                dt += datetime.timedelta(days=7)   # 本周该时刻已过 → 下周
            body = re.sub(
                r"^每周[一二三四五六日天]\s*(早上|上午|中午|下午|晚上)?\s*",
                "", bare).strip()
            return "todo", {"text": body or bare, "tags": ["待办", "每周"],
                            "remind_at": dt.isoformat(timespec="seconds"),
                            "repeat": "weekly"}, tags

    # 待办动词线索（2026-09-08 深夜收紧：「记得/待办」这类弱词在长文本里
    # 常是叙事提及（"待办清单""记得那天"），曾把整篇日记劫持成待办、
    # 云端层根本轮不到——「80 字切云失效」的真凶之一。弱词只对短文本生效，
    # 且"记得+回忆标记"（那天/以前/当年…）任何时候都不算待办。）
    _narrative_remember = re.search(r"记得(那天|以前|当年|小时候|上次|当初)", bare)
    if (not _narrative_remember
            and (_TODO_STRONG_RE.search(bare)
                 or (_TODO_WEAK_RE.search(bare)
                     and len(bare) <= _cfg()["cloud_threshold"]))):
        remind = parse_time(bare)
        fields = {"text": bare, "tags": ["待办"]}
        if remind:
            fields["remind_at"] = remind
        return "todo", fields, tags

    # 语法糖只剩标签 → 带标签普通笔记
    if tags and bare:
        return "note", {"text": bare, "tags": tags}, tags
    return None


# ---------------- 模型层（local → cloud） ----------------

_INTENTS = "note/todo/expense/contact_create/contact_update/diary/ask/wechat_reply"

_SYS_PROMPT = (
    "你是路远的输入分诊器。对用户输入输出且只输出一行 JSON（不要解释不要代码块）："
    '{"intent":"<意图>","fields":{...},"confidence":"high或low"}。intent 只能是：%s。'
    "判断：将来要做的具体事/被布置/帮带取送交/提醒我/别忘了 → todo，fields.text=核心句(去时间词)，"
    "有时间就加 fields.remind_at='YYYY-MM-DD HH:MM'；"
    "金额(¥/元/块/花了) → expense，fields={amount:数字,item:名目}；expense 必须真有金额；"
    "某人的生日/电话/微信/QQ是多少被告知 → contact_update，fields={name,field,value}；"
    "认识了某人/新同学/加好友 → contact_create，fields={name}；"
    "长篇第一人称叙事/情绪感受/一天流水账 → diary，fields.text=原文；"
    "？开头或帮我查/问一下 → ask，fields.q=原文；"
    "语音/文字明确要回微信消息（'回复张三：…'/'回他：…'/'发消息给李四：…'）→ wechat_reply，"
    "fields={to:'他'/'她'表示当前聊天否则为联系人名, text:回复正文}；"
    "其余一切 → note，fields.text=原文。"
    "强信号规则：有金额的想买/想吃=expense 不是 diary；"
    "没金额的吃/买/喜好陈述（如'X喜欢吃辣'）=note 不是 expense；"
    "描述某人的喜好/习惯/特征=note；已发生(含'了')=note 不是 todo。"
    "confidence 判定：拿不准是两种意图中的哪种（如既像 todo 又像 note、"
    "像 expense 又像 note 的模糊句）→ low，并加 \"candidates\":[\"意图A\",\"意图B\"]"
    "（最多3个，按可能性排序）；基本确定 → high，不要 candidates。"
)


def _model_route(text, threshold):
    """local（短文本）→ cloud（超长/复杂）。
    返回 (intent, fields, model, confidence, candidates) 或 None。"""
    messages = [{"role": "system", "content": _SYS_PROMPT % _INTENTS}]
    shots = _fewshot()
    if shots:
        messages.append({"role": "system",
                         "content": "历史改判示例（用户纠正过，优先照办）：" + "；".join(shots)})
    now = datetime.datetime.now().astimezone()
    wk = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
    messages.append({"role": "user",
                     "content": "现在是 %s %s。输入：%s" % (
                         now.strftime("%Y-%m-%d %H:%M"), wk, text[:600])})
    use_cloud = _cfg()["cloud_enabled"] and len(text) > threshold
    order = (["cloud", "local"] if use_cloud else ["local"])
    for tier in order:
        out = None
        try:
            if tier == "local":
                import smart
                out = smart.chat(messages, timeout=30, num_predict=160,
                                 temperature=0)
            else:
                import askaway
                cfg = askaway._cfg()
                if not cfg.get("api_key"):
                    continue
                out = askaway._cloud_chat(messages, cfg)
        except Exception as e:
            log.info("terminal %s route failed: %s", tier, e)
            out = None
        if not out:
            continue
        # 解析：优先整段 JSON；失败再抠 {...}（贪婪，兼容嵌套 fields）；
        # 最后兜底单独抠 "intent":"xxx"（2026-09-08 修：旧正则遇嵌套 fields 全灭，
        # 长文本切云层解析不出来 → 全部落普通笔记，这就是「80 字切云失效」主因）
        data = None
        try:
            data = json.loads(out.strip())
        except Exception:
            m = re.search(r"\{.*\}", out, re.S)
            if m:
                try:
                    data = json.loads(m.group(0))
                except Exception:
                    data = None
        if not isinstance(data, dict) or not data.get("intent"):
            mi = re.search(r'"intent"\s*:\s*"([a-z_]+)"', out)
            if mi:
                data = {"intent": mi.group(1), "fields": {}}
        if not isinstance(data, dict):
            continue
        intent_ = str(data.get("intent", "")).strip()
        if intent_ not in _INTENTS.split("/"):
            continue
        fields = data.get("fields") if isinstance(data.get("fields"), dict) else {}
        # 置信度：模型自报 low 且给不出≥2个合法候选时，补默认候选（不硬猜）
        conf = "low" if str(data.get("confidence", "")).strip() == "low" else "high"
        cands = [str(c).strip() for c in (data.get("candidates") or [])
                 if str(c).strip() in _INTENTS.split("/")]
        cands = list(dict.fromkeys(cands))[:3]
        if conf == "low" and len(cands) < 2:
            cands = list(dict.fromkeys(
                c for c in (intent_, "note", "todo") if c in _INTENTS.split("/")))[:2]
        # 没金额的 expense = 模型误判，降级为笔记（09-11：'X喜欢吃辣'→记账→失败）
        if intent_ == "expense":
            try:
                amt_ok = fields.get("amount") is not None and float(fields["amount"]) > 0
            except (TypeError, ValueError):
                amt_ok = False
            if not amt_ok:
                log.info("terminal route: expense without amount downgraded to note")
                intent_, fields = "note", {"text": text}
        return intent_, fields, tier, conf, cands
    return None


# ---------------- 执行器 ----------------

def _exec_light(intent, fields, tid, idx, tags):
    """轻动作：直接执行，返回 (action_obj, note_id)。失败返回 (failed_obj, None)。"""
    text = str(fields.get("text") or "").strip()
    try:
        if intent == "read_later":
            n = store.add_note(text, source="terminal",
                               tags=list(dict.fromkeys((tags or []) + ["稍后读"])))
            act = {"action": "read_later.create", "module": _M_NOTE,
                   "confirm": False, "status": "done",
                   "label": "已存稍后读，回头慢慢看", "fields": dict(fields)}
        elif intent == "todo":
            repeat = fields.get("repeat")
            repeat_tag = {"daily": "每日", "weekly": "每周"}.get(repeat)
            n = store.add_note(text, source="terminal",
                               tags=["待办"] + ([repeat_tag] if repeat_tag else []))
            if n and fields.get("remind_at"):
                store.set_reminder(n["id"], str(fields["remind_at"]))
            if n and repeat in ("daily", "weekly"):
                store.set_field(n["id"], "repeat", repeat)
            if repeat == "daily":
                label_ = "已记每日待办（每天到点自动提醒）"
            elif repeat == "weekly":
                label_ = "已记每周待办（每周到点自动提醒）"
            else:
                label_ = "已记待办" + ("，到点会提醒你" if fields.get("remind_at") else "")
            act = {"action": "todo.create", "module": _M_NOTE, "confirm": False,
                   "status": "done", "label": label_, "fields": dict(fields)}
        else:   # note（兜底铁律：拿不准就落普通笔记）
            is_pinfo = "个人信息" in list(tags or [])
            n = store.add_note(text, source="terminal", tags=list(tags or []))
            act = {"action": "note.create", "module": _M_NOTE, "confirm": False,
                   "status": "done",
                   "label": "已记入个人信息" if is_pinfo else "已记下一笔",
                   "fields": dict(fields)}
            if is_pinfo:
                act["personal_fact"] = True   # 前端弹左下角询问卡：是否从笔记移除
                _pinfo_to_contact_async(text)   # 本地 LLM 抽（人名，信息）→ 后台挂名片
        if not n:
            return {"action": "note.create", "module": _M_NOTE, "confirm": False,
                    "status": "failed", "label": "没存进去（内容是空的？）",
                    "fields": {}}, None
        act["fields"]["note_id"] = n["id"]
        # 既有智能捕获（联系人待办/归课/归类）后台跑，与打字记事同待遇
        if intent in ("todo", "note"):
            try:
                import classify
                classify.process_async(n["id"], text)
            except Exception as e:
                log.info("terminal classify error: %s", e)
        return act, n["id"]
    except Exception as e:
        log.warning("terminal exec_light failed: %s", e)
        return {"action": "note.create", "module": _M_NOTE, "confirm": False,
                "status": "failed", "label": "存储出问题了，内容还在卡片里",
                "fields": {"text": text}}, None


def _default_fields(intent, text):
    """记忆表直出重动作卡时的兜底字段提取（尽力而为，卡片可改）。"""
    fields = {}
    if intent == "expense":
        m = (_AMT_SYM_RE.search(text) or _AMT_YUAN_RE.search(text)
             or _AMT_HUA_RE.search(text))
        if m:
            try:
                fields["amount"] = float(m.group(1))
            except ValueError:
                pass
        try:
            import expenses
            s = expenses.summarize(text) or {}
            fields.setdefault("item", s.get("item") or text[:20])
            fields.setdefault("category", s.get("category"))
        except Exception:
            fields.setdefault("item", text[:20])
    elif intent == "contact_create":
        name = _CONTACT_NEW_RE.sub("", text)
        pm = _PHONE_RE.search(text)
        if pm:
            name = name.replace(pm.group(0), " ")
        fields = {"name": _clean_name(name)[:20] or text[:20]}
        if pm:
            fields["phone"] = pm.group(0)
    elif intent == "contact_update":
        m = _CONTACT_UP_RE.search(text)
        if m:
            fields = {"name": m.group(1).strip(" ，,。我和")[:20],
                      "field": {"生日": "birthday", "电话": "phone",
                                "手机号": "phone", "号码": "phone",
                                "微信": "wechat", "微信号": "wechat",
                                "QQ": "qq", "qq": "qq"}.get(m.group(2), "note"),
                      "value": m.group(3).strip(" ，,。")[:80]}
    if intent == "diary":
        fields = {"text": _DIARY_RE.sub("", text).strip() or text}
    return fields


def _card_sig(action, fields):
    """确认卡指纹：动作+关键字段（排除 spent_at 这类每次必变的项）。"""
    try:
        f = {}
        for k in sorted(fields):
            if k == "spent_at":
                continue
            v = fields[k]
            if k == "amount":
                try:
                    v = round(float(v), 2)
                except (TypeError, ValueError):
                    pass
            f[k] = v
        return json.dumps({"a": action, "f": f}, sort_keys=True,
                          ensure_ascii=False)
    except Exception:
        return None


def _find_dup_pending(action, fields, fresh_seconds=600):
    """10 分钟内已有一张同指纹的待确认卡 → 返回它（防手滑重复建卡）。"""
    sig = _card_sig(action, fields)
    if not sig:
        return None
    now = _time.time()
    for tid, s in sorted(_sessions().get("sessions", {}).items(),
                         key=lambda kv: kv[1].get("ts", 0), reverse=True):
        if now - s.get("ts", 0) > fresh_seconds:
            continue
        for i, a in enumerate(s.get("actions", [])):
            if a.get("status") != "pending" or a.get("action") != action:
                continue
            if _card_sig(action, a.get("fields") or {}) == sig:
                return tid, i, a
    return None


def _heavy_action(intent, fields):
    """重动作：只组卡不执行。"""
    catalog = {
        "expense": ("expense.create", _M_LEDGER, "记一笔：{item} ¥{amount}"),
        "course": ("course.create", _M_COURSE, "建课程：{name}"),
        "contact_create": ("contact.create", _M_CONTACT, "建联系人：{name}"),
        "contact_update": ("contact.update", _M_CONTACT,
                           "更新{name}的{field}"),
        "diary": ("diary.merge", _M_DIARY, "并入今天的日记"),
    }
    action, module, label_tpl = catalog[intent]
    f = dict(fields)
    try:
        label = label_tpl.format(**{k: f.get(k, "") for k in
                                    ("item", "amount", "name", "field")})
    except Exception:
        label = action
    return {"action": action, "module": module, "confirm": True,
            "status": "pending", "label": label, "fields": f}


def _pinfo_to_contact_async(text):
    """个人信息 → 人脉名片：后台用本地 LLM 抽（人名, 信息短语）再挂。
    名单约束：人名必须精确命中已有联系人，抽不出/挂不上就静默放弃（笔记兜底）。"""
    def _work():
        try:
            import contacts as _contacts
            import smart
            names = [c.get("name") for c in _contacts.list_contacts() if c.get("name")]
            if not names:
                return
            prompt = (
                "从句子中提取人名和关于此人的个人信息。候选人名：" + "、".join(names[:80]) + "。"
                "人名必须是候选人之一（否则放弃）。只输出一行 JSON："
                '{"name":"人名","info":"关于TA的个人信息短语"}；提取不到输出 {}。'
                "示例：输入'刚刚王国钦说他喜欢吃辣'输出 {\"name\":\"王国钦\",\"info\":\"喜欢吃辣\"}。"
                "输入：" + text[:120])
            out = smart.chat([{"role": "user", "content": prompt}],
                             timeout=25, num_predict=80, temperature=0)
            m = re.search(r"\{.*\}", out or "", re.S)
            if not m:
                return
            try:
                data = json.loads(m.group(0))
            except Exception:
                return
            nm = str(data.get("name") or "").strip()
            val = str(data.get("info") or "").strip()
            if not nm or not val or nm not in names:
                return
            _fp, c = _contacts._find_by_name(nm)
            if c:
                _contacts.add_info(c["id"], val[:40])
                log.info("pinfo -> contact %s: %s", nm, val[:40])
        except Exception as e:
            log.info("pinfo llm extract failed: %s", e)
    threading.Thread(target=_work, daemon=True).start()


def _wechat_send_action(to, body):
    """执行微信发送（零触控回消息）。返回 (act_dict, note_id_or_None)。

    出错不抛：任何异常都降级为「复制文本 + 失败状态」，内容永丢——同时记一笔
    「微信回复」笔记留下痕。
    收件人名在此统一做同音纠正（rules/forced/intent 三条入口都汇到这里，
    一处接线全覆盖；resolve 幂等，重复调用无副作用）。"""
    to = _resolve_wechat_name(to)
    try:
        import wechat
        cfg = config.load().get("wechat", {})
        res = wechat.send_reply(to, body, cfg)
    except Exception as e:
        res = {"ok": False, "sent": False, "copied": False,
               "label": "微信模块出错：%s" % str(e)[:40]}
    try:
        n = store.add_note("→%s：%s" % (_wechat_to_label(to), body),
                           source="wechat", tags=["微信回复"])
        nid = n["id"] if n else None
    except Exception:
        nid = None
    act = {"action": "wechat.send", "module": "微信", "confirm": False,
           "status": "done" if res.get("sent") else "failed",
           "label": res.get("label") or "已处理微信回复",
           "fields": {"to": to, "text": body,
                      "sent": bool(res.get("sent")),
                      "verified": bool(res.get("verified")),
                      "copied": bool(res.get("copied"))}}
    return act, nid


def _exec_heavy(action, fields):
    """确认后真入库。返回 result dict（给前端回执）。抛 ValueError = 人话错误。"""
    if action == "expense.create":
        import expenses
        e = expenses.add(fields.get("amount"), fields.get("item"),
                         spent_at=fields.get("spent_at") or None,
                         category=fields.get("category") or None,
                         source="terminal")
        if not e:
            raise ValueError("金额没认出来，改一下再确认")
        return {"expense": e}
    if action == "course.create":
        import courses
        try:
            wd = int(fields.get("weekday", 1))
        except (TypeError, ValueError):
            wd = 1
        c = courses.add(str(fields.get("name") or "").strip(),
                        teacher=fields.get("teacher") or None,
                        place=fields.get("place") or None,
                        weekday=wd if 1 <= wd <= 7 else 1,
                        start=fields.get("start") or None,
                        end=fields.get("end") or None,
                        weeks=fields.get("weeks") or "1-16")
        if not c:
            raise ValueError("课程名是空的，改一下再确认")
        return {"course": c}
    if action == "contact.create":
        import contacts
        c = contacts.add_contact(str(fields.get("name") or "").strip())
        if not c:
            raise ValueError("名字是空的，改一下再确认")
        extra = {k: fields[k] for k in ("phone", "wechat", "qq", "birthday",
                                        "relation", "note")
                 if fields.get(k)}
        if extra:
            try:
                c = contacts.update_contact(c["id"], extra) or c
            except Exception as e:
                log.info("terminal contact extra failed: %s", e)
        return {"contact": c}
    if action == "contact.update":
        import contacts
        name = str(fields.get("name") or "").strip()
        target = next((x for x in contacts.list_contacts()
                       if x.get("name") == name), None)
        if not target:
            raise ValueError("没找到联系人「%s」，先建档案再更新" % name)
        field = str(fields.get("field") or "note")
        if field not in ("phone", "wechat", "qq", "birthday", "relation", "note"):
            raise ValueError("这个字段我改不了")
        c = contacts.update_contact(target["id"], {field: fields.get("value", "")})
        if not c:
            raise ValueError("更新没写进去，再试一次")
        return {"contact": c}
    if action == "diary.merge":
        text = str(fields.get("text") or "").strip()
        if not text:
            raise ValueError("日记内容是空的")
        today = datetime.datetime.now().astimezone().strftime("%Y-%m-%d")
        ns = [n for n in store.list_notes(tag="日记", limit=50)
              if str(n.get("created_at", "")).startswith(today)]
        if ns:
            old = ns[0].get("text", "")
            merged = (old + "\n\n" + text).strip()
            n = store.update_note(ns[0]["id"], merged)
        else:
            n = store.add_note(text, source="terminal", tags=["日记"])
        return {"note": n}
    raise ValueError("不认识这个动作")


# ---------------- 主入口 ----------------

def _err(code, msg, status=400):
    return {"ok": False, "error": {"code": code, "msg": msg}, "_status": status}


_DEBOUNCE = {}     # text -> (ts, response)：8 秒内同文本直接回上一次结果（防手滑双发）
_DEBOUNCE_CAP = 200


# ---------------- 语音断句（口语长句预处理，09-11 定案） ----------------

_PUNCT_RE = re.compile(r"[，。,．!?？;；、\n]")


def _looks_like_speech(text):
    """无标点（或极少标点）的长输入 → 大概率是语音转写原文。"""
    return len(text) >= 24 and len(_PUNCT_RE.findall(text)) <= 2


def _parse_split(out, text):
    """解析断句输出 + 合理性校验（句数 2~6、总字数不缩水超三成）。"""
    if not out:
        return None
    m = re.search(r"\[.*\]", out, re.S)
    if not m:
        return None
    try:
        arr = json.loads(m.group(0))
    except Exception:
        return None
    if not isinstance(arr, list):
        return None
    segs = [str(s).strip() for s in arr if str(s).strip()]
    if not (2 <= len(segs) <= 6):
        return None
    if sum(len(s) for s in segs) < len(text) * 0.7:   # 防模型偷懒吞句
        return None
    return segs


def _split_speech(text):
    """本地 LLM 口语断句：只切分不解读。极速模型切不好 → 主力模型重试一次。
    失败/异常一律返回 None（按原句走瀑布，永不因断句丢内容）。"""
    try:
        import smart
        if not smart.ollama_running():
            return None
        msgs = [{"role": "system",
                 "content": "把用户输入按语义切成独立的短句。只做切分，不改字、"
                            "不解读、不归类。输出且只输出 JSON 数组："
                            '[\"句子1\",\"句子2\"]。单句就原样返回一行数组。'},
                {"role": "user", "content": text}]
        segs = _parse_split(smart.chat(msgs, timeout=20, num_predict=300,
                                       temperature=0), text)
        if not segs:
            big = smart.pick_big_model()
            if big:
                segs = _parse_split(smart.chat(msgs, timeout=45, num_predict=300,
                                               temperature=0, model=big), text)
                if segs:
                    log.info("speech split rescued by big model: %s", big)
        return segs
    except Exception as e:
        log.info("speech split failed: %s", e)
        return None


def _route_multi(orig_text, segs, source):
    """逐句走完整瀑布后合并回执。任一句都失败 → 原句兜底。"""
    subs = [route(s, source=source, _depth=1) for s in segs]
    actions, deadlines, models = [], [], []
    for r in subs:
        if not r.get("ok"):
            continue
        actions.extend(r.get("actions") or [])
        u = r.get("undo") or {}
        if u.get("can") and u.get("deadline_ts"):
            deadlines.append(u["deadline_ts"])
        models.append(r.get("model") or "rules")
    if not actions:
        return route(orig_text, source=source, _depth=1)
    resp = {
        "ok": True, "id": subs[0].get("id"),
        "model": "voice_split" if len(set(models)) > 1 else models[0],
        "intent": "multi", "actions": actions,
        "undo": {"can": bool(deadlines),
                 "deadline_ts": min(deadlines) if deadlines else None},
        "split": segs, "error": None,
    }
    _DEBOUNCE[orig_text] = (_time.time(), resp)
    return resp


def route(text, source="panel", force_intent=None, _depth=0):
    text = (text or "").strip()
    if not text:
        return _err("empty", "说点什么吧，空白的。")
    if len(text) > 6000:
        return _err("too_long", "太长了，先拆两条记。")
    # 防手滑：8 秒内同一句输入 → 原样返回上一次结果，不重复入库。
    # 但误判记忆表有新命中（用户刚改判过）时必须放行——学习路径优先。
    mem_to_early = _memory_hit(text)
    prev = _DEBOUNCE.get(text)
    if (prev and _time.time() - prev[0] < 8 and not force_intent
            and not (mem_to_early and mem_to_early != prev[1].get("intent"))):
        resp = dict(prev[1])
        resp["dedup"] = True
        return resp
    model, intent, actions = "rules", "note", []
    note_ids, session_actions = [], []

    # ⓪ 用户在低置信确认卡上拍板 → 直连执行，不再猜；并记入误判记忆表（学习闭环）
    forced = force_intent if force_intent in _INTENTS.split("/") else None
    if forced:
        model, intent = "user", forced
        _memory_record(text, forced)
        if forced in ("expense", "contact_create", "contact_update", "diary"):
            fields = _default_fields(forced, text)
            act = _heavy_action(forced, fields)
            dup = _find_dup_pending(act["action"], act["fields"])
            if dup:
                dup_tid, dup_idx, dup_act = dup
                act = dict(dup_act)
                act["status"] = "ref"
                act["label"] = dup_act["label"] + "（10分钟内已建过相同卡，这是同一张）"
                act["fields"] = dict(dup_act.get("fields") or {})
                act["fields"]["dup_of"] = "%s/%d" % (dup_tid, dup_idx)
            else:
                session_actions.append((act, fields))
            actions.append(act)
        elif forced == "wechat_reply":
            wto, wbody = (parse_wechat(text) or ("current", text))
            fields = {"to": wto, "text": wbody}
            act, nid = _wechat_send_action(wto, wbody)
            session_actions.append((act, fields))
            if nid:
                note_ids.append(nid)
            actions.append(act)
        else:   # note / todo / read_later
            fields = {"text": text, "tags": (["待办"] if forced == "todo" else [])}
            if forced == "todo":
                r = parse_time(text)
                if r:
                    fields["remind_at"] = r
            act, nid = _exec_light(forced, fields, None, 0, [])
            session_actions.append((act, fields))
            if nid:
                note_ids.append(nid)
            actions.append(act)
    # ⓪′ 语音长句断句：口语无标点 → 本地 LLM 切分，逐句走瀑布（只切分不解读）
    #   ⚠️ 微信回复指令是强信号，绝不能被断句拆散——否则「回复X：正文」会被切成
    #   「回复X：」+「正文」两条待办，微信压根不发（2026-09-13 实测踩坑）。
    elif (_depth == 0 and _looks_like_speech(text)
          and parse_wechat(text) is None):
        segs = _split_speech(text)
        if segs and len(segs) > 1:
            return _route_multi(text, segs, source)
        # 切分失败/单句 → 落回正常瀑布

    # ① 误判记忆表（压过一切）
    mem_to = _memory_hit(text)
    if not forced and mem_to and mem_to in ("expense", "contact_create", "contact_update",
                             "diary"):
        model, intent = "memory", mem_to
        fields = _default_fields(mem_to, text)
        act = _heavy_action(intent, fields)
        dup = _find_dup_pending(act["action"], act["fields"])
        if dup:
            dup_tid, dup_idx, dup_act = dup
            act = dict(dup_act)
            act["status"] = "ref"
            act["label"] = dup_act["label"] + "（10分钟内已建过相同卡，这是同一张）"
            act["fields"] = dict(dup_act.get("fields") or {})
            act["fields"]["dup_of"] = "%s/%d" % (dup_tid, dup_idx)
        else:
            session_actions.append((act, fields))
        actions.append(act)
    elif not forced and mem_to and mem_to in ("note", "todo", "read_later"):
        model, intent = "memory", mem_to
        fields = {"text": text, "tags": (["待办"] if mem_to == "todo" else [])}
        if mem_to == "todo":
            r = parse_time(text)
            if r:
                fields["remind_at"] = r
        act, nid = _exec_light(mem_to, fields, None, 0, [])
        session_actions.append((act, fields))
        if nid:
            note_ids.append(nid)
        actions.append(act)
    elif not forced:
        # ② 确定性规则
        ruled = _rules_route(text)
        fields = None
        rule_tags = None   # 规则层第三元组位的标签（09-11 修复：原先被丢弃，
                           # 导致「个人信息」标签与弹窗标记在真实接口上失效）
        if ruled:
            intent, fields, rule_tags = ruled
        else:
            # ③ 模型层（local/cloud）
            got = _model_route(text, _cfg()["cloud_threshold"])
            if got:
                raw_intent, mfields, model, mconf, mcands = got
                fields = dict(mfields or {})
                if mconf == "low" and len(mcands) >= 2:
                    intent = "clarify"   # 低置信 → 不硬猜，弹卡让用户拍板
                elif raw_intent == "read_later":
                    intent = "read_later"
                    fields.setdefault("text", text)
                elif raw_intent in ("todo", "note", "diary", "expense",
                                    "contact_create", "contact_update", "ask"):
                    intent = raw_intent
                    if intent in ("todo", "note", "diary") and not fields.get("text"):
                        fields["text"] = text
                    if intent == "expense" and not fields.get("amount"):
                        intent = "note"          # 金额没数出来 → 落笔记兜底
                        fields["text"] = text
                else:
                    intent, fields = "note", {"text": text}
            else:
                intent, fields = "note", {"text": text}   # 全层失败 → 兜底铁律

        if intent == "clarify":
            actions.append({
                "action": "intent.clarify", "module": _M_NOTE,
                "confirm": False, "status": "clarify",
                "label": "这条拿不准，你说了算",
                "fields": {"orig_text": text, "candidates": list(mcands)}})
        elif intent == "ask":
            actions.append({"action": "ask.handoff", "module": _M_ASK,
                            "confirm": False, "status": "handoff",
                            "label": "这个问题去问问路远",
                            "fields": {"q": fields.get("q") or text}})
        elif intent in ("expense", "course", "contact_create", "contact_update",
                        "diary"):
            act = _heavy_action(intent, fields)
            # 10 分钟内已有同指纹待确认卡 → 引用旧卡，不生成重复卡
            dup = _find_dup_pending(act["action"], act["fields"])
            if dup:
                dup_tid, dup_idx, dup_act = dup
                act = dict(dup_act)
                act["status"] = "ref"   # 引用卡：非独立卡，pending 统计与确认都指向原卡
                act["label"] = dup_act["label"] + "（10分钟内已建过相同卡，这是同一张）"
                act["fields"] = dict(dup_act.get("fields") or {})
                act["fields"]["dup_of"] = "%s/%d" % (dup_tid, dup_idx)
            else:
                session_actions.append((act, fields))
            actions.append(act)
        elif intent == "wechat_reply":
            wto = fields.get("to") or "current"
            wbody = fields.get("text") or text
            act, nid = _wechat_send_action(wto, wbody)
            session_actions.append((act, fields))
            if nid:
                note_ids.append(nid)
            actions.append(act)
        else:
            light_intent = intent if intent in ("todo", "read_later") else "note"
            if light_intent == "note" and "text" not in fields:
                fields["text"] = text
            act, nid = _exec_light(light_intent, fields, None, 0,
                                   rule_tags if rule_tags is not None
                                   else (fields.get("tags") or []))
            actions.append(act)
            session_actions.append((act, fields))
            if nid:
                note_ids.append(nid)

    tid = "t_" + datetime.datetime.now().strftime("%H%M%S") + \
        os.urandom(2).hex()
    sess = {
        "id": tid, "ts": _time.time(), "text": text, "source": source,
        "model": model, "intent": intent, "actions": actions,
        "note_ids": note_ids, "undone": False,
    }
    _put_session(tid, sess)
    undoable = bool(note_ids) and not any(a.get("status") == "failed"
                                          for a in actions)
    resp = {
        "ok": True, "id": tid, "model": model, "intent": intent,
        "actions": actions,
        "undo": {"can": undoable,
                 "deadline_ts": (_time.time() + _cfg()["undo_seconds"])
                 if undoable else None},
        "error": None,
    }
    _DEBOUNCE[text] = (_time.time(), resp)
    if len(_DEBOUNCE) > _DEBOUNCE_CAP:   # 淘汰最旧的缓存
        for k in sorted(_DEBOUNCE, key=lambda k: _DEBOUNCE[k][0])[:-_DEBOUNCE_CAP]:
            _DEBOUNCE.pop(k, None)
    return resp


def history_items(limit=50):
    """终端输入历史（命令面板/「今天我干了啥」的后端）。"""
    out = []
    for tid, s in sorted(_sessions().get("sessions", {}).items(),
                         key=lambda kv: kv[1].get("ts", 0), reverse=True)[:limit]:
        out.append({
            "id": tid, "ts": s.get("ts"), "text": s.get("text", ""),
            "source": s.get("source"), "model": s.get("model"),
            "intent": s.get("intent"),
            "actions": [{"action": a.get("action"), "label": a.get("label"),
                         "status": a.get("status")}
                        for a in s.get("actions", [])],
        })
    return out


# ---------------- 会话级操作 ----------------

def pending_items():
    out = []
    for tid, s in sorted(_sessions().get("sessions", {}).items(),
                         key=lambda kv: kv[1].get("ts", 0), reverse=True):
        for i, a in enumerate(s.get("actions", [])):
            if a.get("status") == "pending":
                item = dict(a)
                item["tid"], item["index"], item["when"] = tid, i, s.get("text", "")
                item["ts"] = s.get("ts")   # 卡片创建时间（UI 显示等了多久）
                out.append(item)
    return out


def confirm(tid, index, edits=None):
    s = _get_session(tid)
    if not s:
        return _err("not_found", "这张确认卡不在了（可能已被处理）。", 404)
    try:
        index = int(index)
    except (TypeError, ValueError):
        return _err("bad_index", "动作序号不对。")
    actions = s.get("actions", [])
    if not (0 <= index < len(actions)):
        return _err("bad_index", "动作序号不对。")
    act = actions[index]
    if act.get("status") != "pending":
        return _err("not_pending", "这张卡不是等确认的状态。")
    fields = dict(act.get("fields") or {})
    for k, v in (edits or {}).items():
        if k in ("amount",):
            try:
                fields[k] = round(float(v), 2)
                continue
            except (TypeError, ValueError):
                return _err("bad_field", "金额得是个数。")
        fields[k] = v
    try:
        result = _exec_heavy(act["action"], fields)
    except ValueError as e:
        return _err("confirm_fix", str(e))          # 卡片留着，等用户改完再点
    except Exception as e:
        log.warning("terminal confirm failed: %s", e)
        return _err("exec_failed", "入库失败了，数据没动，再试一次。")
    act["status"] = "done"
    act["fields"] = fields
    act["label"] += "（已入库）"
    _update_session(tid, actions=actions)
    return {"ok": True, "result": result, "error": None}


def reject(tid, index):
    s = _get_session(tid)
    if not s:
        return _err("not_found", "这张确认卡不在了。", 404)
    actions = s.get("actions", [])
    try:
        index = int(index)
    except (TypeError, ValueError):
        return _err("bad_index", "动作序号不对。")
    if not (0 <= index < len(actions)):
        return _err("bad_index", "动作序号不对。")
    if actions[index].get("status") != "pending":
        return _err("not_pending", "这张卡不是等确认的状态。")
    actions[index]["status"] = "rejected"
    actions[index]["label"] += "（已放弃）"
    _update_session(tid, actions=actions)
    return {"ok": True, "error": None}


def undo(tid):
    s = _get_session(tid)
    if not s:
        return _err("not_found", "这条记录不在了。", 404)
    if s.get("undone"):
        return _err("already", "这条已经撤销过了。")
    n = 0
    for nid in s.get("note_ids", []):
        if store.soft_delete(nid):
            n += 1
    if not n:
        return _err("nothing", "这条没有可直接撤销的动作（重动作本来就没入库）。")
    _update_session(tid, undone=True)
    return {"ok": True, "undone": n, "error": None}


def rejudge(tid, index, action):
    s = _get_session(tid)
    if not s:
        return _err("not_found", "这条记录不在了。", 404)
    intent = str(action or "").strip()
    if intent == "read_later.create":
        intent = "read_later"
    elif intent in ("todo.create",):
        intent = "todo"
    elif intent in ("contact.create",):
        intent = "contact_create"
    elif intent in ("contact.update",):
        intent = "contact_update"
    elif intent in ("expense.create",):
        intent = "expense"
    elif intent in ("diary.merge",):
        intent = "diary"
    elif intent in ("note.create",):
        intent = "note"
    if intent not in ("note", "todo", "expense", "contact_create",
                      "contact_update", "diary", "read_later"):
        return _err("bad_action", "改判的目标动作不认识。")
    _memory_record(s.get("text", ""), intent)
    # 用户刚纠正过 → 清掉该句防抖缓存，下次同句必须走记忆表重新路由（学习闭环）
    _DEBOUNCE.pop((s.get("text") or "").strip(), None)
    return {"ok": True, "memory": _memory_hit(s.get("text", "")), "error": None}
