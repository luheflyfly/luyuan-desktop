# -*- coding: utf-8 -*-
"""问路远（开发计划 P4）：面板里的对话式查笔记。
- 云 API：OpenAI 兼容接口（默认 DeepSeek，base_url/model 可配 GLM 等）；
  **API Key 只存 config.json，前端/App 永不接触**（木案铁律）。
- 上下文 = 本地检索（bge 语义 + 关键词）相关笔记片段 + 今日待办摘要；
  打「私密」标签的笔记**默认不外发**；经用户允许（全局开关 / 来源白名单 / 单次授权）可外发。
- Ollama 本地模型兜底（断网/无 Key 时降级，问答质量降级但可用）。
- 会话历史只在内存（进程重启即清），不落 notes、不进同步。
"""
import json
import logging
import urllib.request
from collections import deque

log = logging.getLogger("askaway")

_HISTORY = deque(maxlen=12)   # [{"role","content"}]
HISTORY_LIMIT = 12


def _cfg():
    import config as _cfg
    cfg = _cfg.load()
    a = cfg.get("askaway", {})
    pr = cfg.get("privacy", {}) or {}
    return {
        "enabled": a.get("enabled", True),
        "base_url": (a.get("base_url") or "https://api.deepseek.com").rstrip("/"),
        "model": a.get("model") or "deepseek-chat",
        "api_key": a.get("api_key") or "",
        "timeout": int(a.get("timeout", 60) or 60),
        "private_tag": a.get("private_tag", "私密"),
        "max_notes": int(a.get("max_notes", 8) or 8),
        "fallback_model": a.get("fallback_model") or "qwen3.5:4b",
        "allow_private_outbound": bool(pr.get("allow_private_outbound", False)),
        "allowed_sources": pr.get("allowed_sources") or [],
    }


def _private_tag():
    return _cfg()["private_tag"]


def _is_private(note):
    tag = _private_tag()
    return bool(tag) and tag in (note.get("tags") or [])


def privacy_granted(source=None):
    """私密内容是否获准外发（2026-09-13 红线变更）。

    旧规则「私密永不外发」→ 新规则「默认不外发，经用户允许可外发」。
    授权来源（任一满足即放行）：
      ① 全局开关 config.privacy.allow_private_outbound = true
      ② 来源白名单 config.privacy.allowed_sources 里含 source
    单次授权由调用方显式传 allow_private=True 覆盖（优先级最高）。
    读取失败一律返回 False —— 保护性默认，宁可本地整理也不误发。
    """
    try:
        c = _cfg()
        if c["allow_private_outbound"]:
            return True
        if source and source in c["allowed_sources"]:
            return True
    except Exception:
        pass
    return False


def retrieve_context(question, max_notes=None, allow_private=None):
    """关键词 + 语义双路检索相关笔记（排除软删/日记；私密笔记默认排除）。

    allow_private：None = 跟随 config.privacy 授权状态；True = 本次放行私密（单次授权）；
                   False = 本次强制排除（哪怕全局开关开着）。
    """
    import store
    import semsearch
    max_notes = max_notes or _cfg()["max_notes"]
    if allow_private is None:
        allow_private = privacy_granted()
    q = (question or "").strip()
    out, seen = [], set()

    def _add(ns):
        for n in ns:
            if n.get("id") in seen or (not allow_private and _is_private(n)):
                continue
            seen.add(n["id"])
            text = (n.get("text") or "").replace("\n", " ")
            out.append({"id": n["id"], "time": str(n.get("created_at", ""))[:16],
                        "text": text[:200]})

    if q:
        try:
            _add(store.search_notes(q)[: max_notes // 2 or 2])
        except Exception:
            pass
        try:
            _add(semsearch.search(q)[:max_notes])
        except Exception:
            pass
    return out[:max_notes]


def _today_brief():
    """今日待办摘要：联系人待办（未完成）+ 今天到期的笔记提醒。"""
    import contacts as _ct
    import store
    import datetime
    lines = []
    for it in _ct.pending_contact_todos():
        t = it["todo"]
        ra = t.get("remind_at", "")
        lines.append("· %s（%s）%s" % (t.get("text", ""), it["contact"].get("name", ""),
                                       ra[5:16] if ra else "未定时"))
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    for n in store.due_reminders():
        if str(n.get("remind_at", "")).startswith(today):
            lines.append("· " + (n.get("text", "") or "")[:40])
    return "\n".join(lines[:10]) or "（今天没有待办）"


SYSTEM_PROMPT = (
    "你是「路远」，用户（路河）的个人记事助理。回答要口语、简短、直接可用。"
    "下面是检索到的用户历史笔记片段和今日待办，仅作为回答依据；"
    "片段覆盖不了就直说没查到，不要编造。片段里的时间是笔记记录时间。"
)


def _history():
    return list(_HISTORY)


def _push_history(question, answer):
    _HISTORY.append({"role": "user", "content": question})
    _HISTORY.append({"role": "assistant", "content": answer})


def _cloud_chat(messages, cfg, temperature=0.4):
    url = cfg["base_url"] + "/chat/completions"
    payload = json.dumps({"model": cfg["model"], "messages": messages,
                          "temperature": temperature, "stream": False}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + cfg["api_key"]})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        data = json.loads(r.read().decode("utf-8"))
    return (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()


def _ollama_chat(messages, cfg):
    import urllib.request
    model = cfg["fallback_model"]
    try:
        with urllib.request.urlopen(cfg_ollama() + "/api/tags", timeout=3) as r:
            tags = [m.get("name", "") for m in json.loads(
                r.read().decode("utf-8")).get("models", [])]
        if model not in tags:
            model = tags[0] if tags else None
    except Exception:
        model = None
    if not model:
        raise RuntimeError("Ollama 也不可用")
    payload = json.dumps({"model": model, "messages": messages, "stream": False,
                          "think": False,   # 2026-09-13：qwen3.5 关思考，否则答案预算被烧在推理上
                          "options": {"temperature": 0.4}}).encode("utf-8")
    req = urllib.request.Request(cfg_ollama() + "/api/chat", data=payload,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode("utf-8")).get("message", {}).get("content", "").strip()


def cfg_ollama():
    import config as _cfg
    return _cfg.load().get("stt", {}).get("correct", {}).get(
        "endpoint", "http://localhost:11434").rstrip("/")


def ask(question, allow_private=None):
    """主入口：检索 → 组装 → 云 API（有 Key 时）/ Ollama 兜底。返回 (answer, engine)。

    allow_private 见 retrieve_context：None 跟随配置，True 单次放行私密内容。
    """
    q = (question or "").strip()
    if not q:
        return "问点啥？", "empty"
    cfg = _cfg()
    if not cfg["enabled"]:
        return "问路远功能已关闭（config.askaway.enabled）。", "disabled"
    snippets = retrieve_context(q, allow_private=allow_private)
    brief = _today_brief()
    ctx = "【相关笔记片段】\n" + ("\n".join(
        "- [%s] %s" % (s["time"], s["text"]) for s in snippets) or "（没检索到相关笔记）")
    messages = ([{"role": "system", "content": SYSTEM_PROMPT}] + _history() +
                [{"role": "user",
                  "content": ctx + "\n\n【今日待办】\n" + brief + "\n\n【问题】" + q}])
    engine = "cloud"
    try:
        if cfg["api_key"]:
            answer = _cloud_chat(messages, cfg)
        else:
            raise RuntimeError("no key")
    except Exception as e:
        log.info("cloud ask failed (%s), falling back to ollama", e)
        engine = "ollama"
        try:
            answer = _ollama_chat(messages, cfg)
        except Exception as e2:
            log.warning("ollama fallback also failed: %s", e2)
            return ("云端和本地模型都没连上，这条答不了；记事、提醒不受影响。"), "error"
    answer = (answer or "").strip() or "（空回复）"
    _push_history(q, answer)
    return answer, engine


def history():
    return _history()


def clear_history():
    _HISTORY.clear()
