# -*- coding: utf-8 -*-
"""记账存储（SYNC_FORMAT v2 §10.2）：kind:"expense" 一条一文件，落 data/notes/。
随 Syncthing 同步；无 text 字段，笔记扫描器天然跳过。"""
import os
import re
import uuid
import datetime
import threading

_BASE = os.path.dirname(os.path.abspath(__file__))
_DIR = os.path.join(_BASE, "data", "notes")   # 与笔记同目录（kind 区分，扫描器按无 text 跳过）
_LOCK = threading.Lock()

CATEGORIES = ["餐饮", "交通", "学习", "生活", "娱乐", "其他"]


def _now_iso():
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def _dir():
    os.makedirs(_DIR, exist_ok=True)
    return _DIR


def _write(fp, e):
    import json
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=2)


def _read(fp):
    import json
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _all_files():
    import glob
    return sorted(f for f in glob.glob(os.path.join(_dir(), "expense_*.json"))
                  if ".sync-conflict" not in os.path.basename(f))


def add(amount, item, spent_at=None, category=None, source="manual", image=None):
    """新增一条消费。amount 数字（元）；spent_at 缺省=现在。返回 expense dict。"""
    try:
        amount = round(float(amount), 2)
    except (TypeError, ValueError):
        return None
    item = (item or "").strip() or "（未命名）"
    if not spent_at:
        spent_at = _now_iso()
    e = {
        "kind": "expense", "id": str(uuid.uuid4()), "schema": 2, "device": "pc",
        "deleted": False,
        "amount": amount, "item": item,
        "category": (category or "其他").strip() or "其他",
        "spent_at": spent_at, "source": source,
        "tags": ["记账"],
        "created_at": _now_iso(), "updated_at": _now_iso(),
    }
    if image:
        e["image"] = image
    with _LOCK:
        _write(os.path.join(_dir(), "expense_%s.json" % e["id"][:8]), e)
    return e


def list_month(month=None):
    """某月消费（month='YYYY-MM'，缺省当月），按 spent_at 倒序。"""
    month = month or datetime.datetime.now().strftime("%Y-%m")
    out = []
    for fp in _all_files():
        e = _read(fp)
        if e and not e.get("deleted") and str(e.get("spent_at", "")).startswith(month):
            out.append(e)
    out.sort(key=lambda e: e.get("spent_at", ""), reverse=True)
    return out


def month_stats(month=None):
    """月度统计：合计 + 分类占比。"""
    items = list_month(month)
    by_cat = {}
    for e in items:
        c = e.get("category") or "其他"
        by_cat[c] = round(by_cat.get(c, 0) + float(e.get("amount") or 0), 2)
    total = round(sum(float(e.get("amount") or 0) for e in items), 2)
    cats = sorted(by_cat.items(), key=lambda kv: kv[1], reverse=True)
    return {"month": month, "total": total, "count": len(items),
            "categories": [{"category": c, "amount": a} for c, a in cats]}


def update(eid, fields):
    """更新条目（amount/item/category/spent_at）。"""
    with _LOCK:
        for fp in _all_files():
            e = _read(fp)
            if e and e.get("id") == eid:
                for k in ("amount", "item", "category", "spent_at"):
                    if k in (fields or {}):
                        e[k] = fields[k]
                e["updated_at"] = _now_iso()
                _write(fp, e)
                return e
    return None


def delete(eid):
    with _LOCK:
        for fp in _all_files():
            e = _read(fp)
            if e and e.get("id") == eid:
                try:
                    os.remove(fp)
                    return True
                except OSError:
                    return False
    return False


_CATEGORY_WORDS = [
    ("餐饮", ["饭", "餐", "奶茶", "咖啡", "吃", "喝", "外卖", "面", "粉",
              "餐饮美食", "美团", "饿了么", "肯德基", "麦当劳", "食品", "零食", "生鲜"]),
    ("交通", ["地铁", "公交", "车", "打车", "票", "油", "交通出行", "滴滴", "高铁", "铁路", "机票", "共享单车"]),
    ("学习", ["书", "笔", "课", "打印", "资料", "学费", "教材", "淘宝网", "京东", "文具"]),
    ("娱乐", ["电影", "游戏", "会员", "唱", "影音娱乐", "视频", "音乐"]),
    ("生活", ["日用", "纸", "洗", "话费", "电", "水", "日用百货", "服饰打扮", "医疗健康", "房租"]),
]


# 账单交易类型 → 路远分类（微信/支付宝的类型列是粗分类，直接映射最准）
_BILL_TYPE_MAP = [
    ("餐饮美食", "餐饮"), ("外卖", "餐饮"), ("食物", "餐饮"), ("水果", "餐饮"), ("烟酒", "餐饮"),
    ("交通", "交通"), ("出行", "交通"), ("打车", "交通"), ("火车", "交通"), ("机票", "交通"),
    (" 学习", "学习"), ("教育培训", "学习"), ("书籍", "学习"), ("文具", "学习"),
    ("影音娱乐", "娱乐"), ("游戏", "娱乐"), ("会员", "娱乐"),
    ("日用百货", "生活"), ("服饰", "生活"), ("医疗", "生活"), ("话费", "生活"), ("水电", "生活"),
]


def _bill_category(item, counterparty, bill_type):
    """账单行分类：①交易类型列精确映射 ②商品/对方关键词走 _CATEGORY_WORDS。"""
    hay = "%s %s %s" % (bill_type, item, counterparty)
    for key, cat in _BILL_TYPE_MAP:
        if key.strip() and key.strip() in (bill_type or ""):
            return cat
    for cat_name, words in _CATEGORY_WORDS:
        if any(w in hay for w in words):
            return cat_name
    return "其他"


def summarize(text):
    """从一句话里抽记账（「午饭 12.5」式），够用就纯规则。返回 dict 或 None。"""
    text = (text or "").strip()
    m = re.search(r"([0-9]+(?:\.[0-9]{1,2})?)\s*元?", text)
    if not m:
        return None
    amount = float(m.group(1))
    item = text.replace(m.group(0), "").strip(" ，,。的") or "（未命名）"
    cat = "其他"
    for cat_name, words in _CATEGORY_WORDS:
        if any(w in text for w in words):
            cat = cat_name
            break
    return {"amount": amount, "item": item[:40], "category": cat}


# ---------------- 账单导入（2026-09-14：微信/支付宝导出 CSV） ----------------
def _parse_money(s):
    """'¥25.00' / '25.00' / '25.00元' → float；解析不出 None。"""
    m = re.search(r"(\d+(?:\.\d{1,2})?)", str(s or "").replace(",", ""))
    return float(m.group(1)) if m else None


def _norm_spent(s):
    """'2026-09-14 12:30:45' → ISO（缺秒补 :00）；解析不出 None。"""
    s = str(s or "").strip().replace("/", "-")
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.group(1), int(m.group(2)), int(m.group(3)), int(m.group(4)), m.group(5), m.group(6) or "00"
    try:
        return "%s-%02d-%02dT%02d:%s:%s" % (y, mo, d, hh, mm, ss)
    except Exception:
        return None


# 列名候选（不同账单版本字段名略有差异，按包含匹配）
_BILL_COLS = {
    "time": ["交易时间", "交易创建时间", "付款时间"],
    "counterparty": ["交易对方", "交易对象"],
    "item": ["商品", "商品名称", "说明"],
    "direction": ["收/支", "收支", "收 / 支"],
    "amount": ["金额(元)", "金额（元）", "金额"],
    "type": ["交易类型", "类型"],
}


def _find_cols(header):
    cols = {}
    for key, cands in _BILL_COLS.items():
        for i, h in enumerate(header):
            hn = str(h or "").strip()
            for cand in cands:
                if hn == cand or (cand in hn and len(hn) <= len(cand) + 4):
                    cols.setdefault(key, i)
                    break
    return cols


def import_bill_text(text, source="bill"):
    """解析微信/支付宝导出账单（CSV 文本），只导「支出」行。返回 (imported, skipped, errors)。

    去重：同 spent_at + amount + item 已存在 → 跳过（可重复粘贴同一份账单）。
    分类留空走「其他」（后续在面板可改）；item=「商品名（交易对方）」。
    """
    import csv as _csv
    import io as _io
    text = (text or "").replace("	", ",").replace("﻿", "")
    rows = [r for r in _csv.reader(_io.StringIO(text)) if any(c.strip() for c in r)]
    if not rows:
        return 0, 0, ["空账单"]
    # 找表头行：含「交易时间/交易创建时间」且含「金额」
    head_i = -1
    for i, r in enumerate(rows[:30]):
        joined = ",".join(r)
        if ("交易时间" in joined or "交易创建时间" in joined) and "金额" in joined:
            head_i = i
            break
    if head_i < 0:
        return 0, 0, ["没找到账单表头（需要微信/支付宝导出的原始 CSV）"]
    cols = _find_cols(rows[head_i])
    if "time" not in cols or "amount" not in cols:
        return 0, 0, ["表头缺「交易时间」或「金额」列"]
    existing = {(str(e.get("spent_at", ""))[:16], round(float(e.get("amount") or 0), 2),
                 (e.get("item") or "")[:30])
                for e in list_all()}
    imported = skipped = 0
    errors = []
    for r in rows[head_i + 1:]:
        def cell(k):
            i = cols.get(k)
            return r[i].strip() if i is not None and i < len(r) else ""
        direction = cell("direction")
        bill_type = cell("type") if "type" in cols else ""
        if direction and "支" not in direction:   # 收入 / 不计收支 → 跳过
            skipped += 1
            continue
        amount = _parse_money(cell("amount"))
        spent_at = _norm_spent(cell("time"))
        if amount is None or spent_at is None:
            if any(cell(k) for k in cols):
                errors.append("跳过无法解析行：%s" % (cell("time") or cell("amount"))[:24])
            continue
        item = cell("item") or cell("counterparty") or "账单消费"
        cp = cell("counterparty")
        if cp and cp not in item:
            item = "%s（%s）" % (item[:40], cp[:20])
        key = (spent_at[:16], round(amount, 2), item[:30])
        if key in existing:
            skipped += 1
            continue
        e = add(amount, item, spent_at=spent_at, source=source,
                category=_bill_category(item, cp, bill_type))
        if e:
            existing.add(key)
            imported += 1
        else:
            errors.append("入库失败：%s" % item[:20])
    return imported, skipped, errors


def list_all():
    """全部未删消费（导入去重用）。"""
    out = []
    for fp in _all_files():
        e = _read(fp)
        if e and not e.get("deleted"):
            out.append(e)
    return out
