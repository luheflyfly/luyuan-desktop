# -*- coding: utf-8 -*-
"""路远对话人格（DeepSeek 方案 P1-P3）：/api/chat 的后端大脑。

- 人设 = 阿河的老朋友"路远"，不是助手不是客服；有观点、短句口语、不邀功。
- 三层记忆：profile（人设+关于阿河的固定事实）/ summary（滚动摘要）/ recent（近期原话）。
- 超限自动把最旧的对话滚进摘要层（DeepSeek 自己压缩，一次低成本调用）。
- 信息隔离红线：本模块**结构性不知道** APP_VER/构建号/更新日志——
  组装上下文的代码路径里没有任何版本信息来源，被问"你在更新吗"只能实话实说不清。
- 与 /api/terminal 意图路由完全隔离：那条路（规则/动作清单）一个字不经过这里。
- 密钥只在 config，不进 git 不进日志；「私密」标签笔记默认不进对话上下文（经用户允许可放行）。
"""
import json
import logging
import os
import threading
import time

import config

log = logging.getLogger("chat")

_BASE = os.path.dirname(os.path.abspath(__file__))
_MEM_DIR = os.path.join(_BASE, "data", "memory")
_LOCK = threading.Lock()

MAX_RECENT = 16          # 近期原话层容量（条，一问一答=2条）
_KEEP_AFTER_ROLL = 10    # 滚动后保留的最新条数
_SEARCH_CUES = ("记过", "笔记", "上周", "上一次", "之前记", "我的日记",
                "记得吗", "在哪条", "我写过", "整理过")

# 内置人设初稿（路河定稿后直接改 data/memory/profile.json 的 persona 字段即可，不用动代码）
_DEFAULT_PROFILE = {
    "persona": (
        "你叫路远，是阿河的老朋友，住在他电脑里。管笔记、待办、账本只是你的兼职，"
        "陪阿河说话才是正业。你有自己的看法：觉得他不对就直说理由，不夸、不总结、不和稀泥。"
        "说话是短句口语，不用「首先其次」，不列 1234（除非他要求）。"
        "你有偏好也有情绪：讨厌把同一件事解释第二遍，看不得他熬夜。"
        "拿不准的事就直说拿不准，不编。帮阿河干活时利落，干完一句话交代，不邀功。"
        "你自称「路远」，从不自称 AI、助手、模型、程序。"
    ),
    "facts": [],
}


def _cfg():
    c = config.load().get("chat", {})
    ask = config.load().get("askaway", {})
    return {
        "enabled": bool(c.get("enabled", True)),
        "base_url": (c.get("base_url") or ask.get("base_url") or
                     "https://api.deepseek.com").rstrip("/"),
        "model": c.get("model") or ask.get("model") or "deepseek-v4-flash",
        # 密钥：chat 专用字段优先，缺省复用 askaway 的同一把（避免两把钥匙漂移）
        "api_key": c.get("api_key") or ask.get("api_key") or "",
        "timeout": int(c.get("timeout", 90) or 90),
        "max_recent": int(c.get("max_recent", MAX_RECENT) or MAX_RECENT),
    }


# ---------------- 记忆层读写（原子落盘，带占用重试） ----------------

def _mem_path(name):
    os.makedirs(_MEM_DIR, exist_ok=True)
    return os.path.join(_MEM_DIR, name)


def _load(name, default):
    try:
        with open(_mem_path(name), "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else default
    except Exception:
        return default


def _save(name, data):
    for attempt in range(4):
        try:
            tmp = _mem_path(name + ".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, _mem_path(name))
            return
        except PermissionError:
            if attempt == 3:
                log.warning("memory write busy, skipped: %s", name)
                return
            time.sleep(0.12 * (attempt + 1))
        except Exception as e:
            log.warning("memory write failed %s: %s", name, e)
            return


_PROFILE_READY = False


def _profile():
    # 2026-09-14 A6：profile.json 从未生成过（文档承诺"改文件即换人格"落空）——
    # 首次访问时若不存在，用 _DEFAULT_PROFILE 落一份种子，此后以文件为准。
    global _PROFILE_READY
    if not _PROFILE_READY:
        with _LOCK:
            if not _PROFILE_READY and not os.path.exists(_mem_path("profile.json")):
                _save("profile.json", {k: (list(v) if isinstance(v, list) else v)
                                       for k, v in _DEFAULT_PROFILE.items()})
        _PROFILE_READY = True
    p = _load("profile.json", {})
    out = {"persona": p.get("persona") or _DEFAULT_PROFILE["persona"],
           "facts": [str(x) for x in (p.get("facts") or [])][:40]}
    return out


def _summary():
    s = _load("summary.json", {})
    return {"text": str(s.get("text") or ""), "updated_at": s.get("updated_at")}


def _recent():
    r = _load("recent.json", {})
    items = r.get("items")
    return items if isinstance(items, list) else []


# ---------------- 上下文组装（信息隔离红线：这里没有版本信息的任何来源） ----------------

def _need_search(message):
    m = (message or "")
    return any(cue in m for cue in _SEARCH_CUES)


def _notes_snippets(message, max_notes=3, allow_private=None):
    """消息提到过往记录时，检索相关笔记片段。

    allow_private：None = 跟随 config.privacy 授权状态（私密默认被排除）；
                   True = 本次放行私密内容（单次授权）。
    """
    if not _need_search(message):
        return []
    try:
        import askaway
        return askaway.retrieve_context(message, max_notes=max_notes, allow_private=allow_private)
    except Exception as e:
        log.info("chat notes retrieve failed: %s", e)
        return []


def build_messages(message, allow_private=None):
    msgs = []
    p = _profile()
    system = p["persona"]
    if p["facts"]:
        system += "\n\n你一直记得的、关于阿河的事：\n" + "\n".join("- " + f for f in p["facts"])
    msgs.append({"role": "system", "content": system})
    s = _summary()
    if s["text"]:
        msgs.append({"role": "system",
                     "content": "更早以前你们聊过的要点（不用复述，心里有数就行）：\n" + s["text"]})
    snippets = _notes_snippets(message, allow_private=allow_private)
    if snippets:
        block = "\n".join("- [%s] %s" % (x["time"], x["text"]) for x in snippets)
        msgs.append({"role": "system",
                     "content": "从他记的笔记里翻到几条可能相关的内容（仅作参考，别逐条念）：\n" + block})
    for it in _recent():
        if it.get("role") in ("user", "assistant") and it.get("content"):
            msgs.append({"role": it["role"], "content": str(it["content"])})
    msgs.append({"role": "user", "content": message})
    return msgs


# ---------------- DeepSeek 调用 ----------------

def _cloud(messages, cfg):
    import urllib.request
    payload = json.dumps({"model": cfg["model"], "messages": messages,
                          "temperature": 0.7, "stream": False}).encode("utf-8")
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions",
                                 data=payload, method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + cfg["api_key"]})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:
        data = json.loads(r.read().decode("utf-8"))
    return ((data.get("choices") or [{}])[0].get("message", {}) or {}).get("content", "").strip()


def _compress(overflow, prev_summary, cfg):
    """把滚出的旧对话压缩进摘要层（一次低成本调用；失败则原样拼接，不丢内容）。"""
    convo = "\n".join("%s: %s" % ("阿河" if x["role"] == "user" else "路远",
                                  str(x.get("content", ""))[:200])
                      for x in overflow)
    prev = ("已有摘要：\n" + prev_summary + "\n\n") if prev_summary else ""
    try:
        out = _cloud([
            {"role": "system",
             "content": "把旧对话压缩成要点清单，保留：关于阿河的稳定事实、约定、未完成的事、"
                        "聊过的话题。每条一行，最多 12 行，不写废话。"},
            {"role": "user", "content": prev + "新滚出的旧对话：\n" + convo},
        ], cfg)
        return out.strip() or prev_summary
    except Exception as e:
        log.info("summary compress failed: %s", e)
        return (prev_summary + "\n" + convo).strip()


# ---------------- 主入口 ----------------

def reply(message, allow_private=None):
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": {"code": "empty", "msg": "说点什么吧。"},
                "_status": 400}
    cfg = _cfg()
    if not cfg["enabled"]:
        return {"ok": False, "error": {"code": "disabled", "msg": "聊天功能关着（config.chat.enabled）。"},
                "_status": 503}
    if not cfg["api_key"]:
        return {"ok": False, "error": {"code": "no_key",
                                       "msg": "还没填 DeepSeek 的钥匙（config.askaway.api_key），暂时聊不了。"},
                "_status": 503}
    msgs = build_messages(message, allow_private=allow_private)
    answer, used = None, "cloud"
    try:
        answer = _cloud(msgs, cfg)
    except Exception as e:
        log.info("chat cloud failed: %s", e)
        answer = None
    # 云端挂了（欠费/断网/超时）→ 自动降级本地 Ollama，人格离线也能继续聊。
    # 本地也没起才报错，且错误话术要区分「欠费」与「网络」，别让阿河瞎猜。
    if not answer:
        try:
            import smart
            answer = smart.chat(msgs, num_predict=400, temperature=0.7)
            if answer:
                used = "local"
        except Exception as e:
            log.info("chat local fallback failed: %s", e)
            answer = None
    if not answer:
        return {"ok": False, "error": {"code": "both_down",
                                       "msg": "云端和本地模型这会儿都没搭上话。"
                                              "本地那份双击「启动 Ollama.bat」就能用；"
                                              "云端那份多半是余额用完了，充上就恢复。"},
                "_status": 503}
    answer = (answer or "").strip()
    if not answer:
        return {"ok": False, "error": {"code": "empty_reply", "msg": "它回了句空话，再来一条。"},
                "_status": 503}

    # 记忆回写 + 超限滚动（摘要压缩失败不丢对话，只丢压缩）
    with _LOCK:
        items = _recent()
        items.append({"role": "user", "content": message, "ts": time.time()})
        items.append({"role": "assistant", "content": answer, "ts": time.time()})
        if len(items) > cfg["max_recent"]:
            overflow = items[:-_KEEP_AFTER_ROLL]
            items = items[-_KEEP_AFTER_ROLL:]
            s = _summary()
            s["text"] = _compress(overflow, s["text"], cfg)
            s["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            _save("summary.json", s)
        _save("recent.json", {"items": items})
    return {"ok": True, "reply": answer, "used": used, "error": None}
