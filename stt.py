"""STT 引擎封装：FunASR (SenseVoiceSmall + FSMN-VAD)，完全本地、离线。

转写后置处理（v1.15 起）：
  1) 确定性清洗：折叠语音识别常见的“结巴/重复” artifacts（如连续重复汉字）。
  2) 本地大模型纠错（Ollama，可选）：用用户词库(vocab.txt)做偏置，
     修正同音错别字（逆天/一天）、重复词等；保留情绪表情与原文语义。
     若 Ollama 未运行或没有模型，自动跳过，绝不丢内容。
"""
import os
import re
import json
import logging
import urllib.request

import config

log = logging.getLogger("stt")

_MODEL = None
_VOCAB_CACHE = None


def _pick_device():
    dev = config.load().get("stt", {}).get("device", "cpu")
    if dev and dev != "auto":
        return dev
    try:
        import torch
        return "cuda:0" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def get_model():
    """懒加载 ASR 模型（每个进程只加载一次）。指向本地模型目录，不联网。"""
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    from funasr import AutoModel

    cfg = config.load().get("stt", {})
    sv_dir = config.abs_path(cfg.get("sensevoice_dir", "models/SenseVoiceSmall"))
    vad_dir = config.abs_path(cfg.get("vad_dir", "models/VAD"))

    _MODEL = AutoModel(
        model=sv_dir,
        vad_model=vad_dir,
        device=_pick_device(),
        disable_update=True,
        disable_pbar=True,
    )
    return _MODEL


# ---------------- 三层纠错 ----------------

def _cleanup(text):
    """确定性清洗：折叠连续重复汉字/字母，去多余空白。零延迟、零风险。"""
    if not text:
        return text
    # 3 个及以上连续相同汉字 → 2 个（保留“哈哈/呃呃”等正常叠词）
    text = re.sub(r"([\u4e00-\u9fff])\1{2,}", r"\1\1", text)
    # 4 个及以上连续相同 ASCII 字母（兜底）
    text = re.sub(r"([a-zA-Z])\1{3,}", r"\1\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _load_vocab():
    """读取 <project-root>\\vocab.txt：每行一个常用词/网络语，# 开头为注释。"""
    global _VOCAB_CACHE
    if _VOCAB_CACHE is not None:
        return _VOCAB_CACHE
    path = config.abs_path("vocab.txt")
    vocab = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                vocab.append(line)
    except FileNotFoundError:
        vocab = []
    _VOCAB_CACHE = vocab
    return vocab


def _load_corrections():
    """读取 <project-root>\\corrections.txt：每行 `错词=对词`，转写后确定性替换，# 注释。
    用户自己维护（Task #29 确定性同音表）；文件不存在/无规则 → 不做任何替换。"""
    path = config.abs_path("corrections.txt")
    rules = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                wrong, right = line.split("=", 1)
                wrong, right = wrong.strip(), right.strip()
                if wrong and right and wrong != right:
                    rules.append((wrong, right))
    except FileNotFoundError:
        pass
    return rules


def apply_corrections(text):
    """按 corrections.txt 顺序做确定性替换（每次转写现读文件，改完即生效）。"""
    for wrong, right in _load_corrections():
        if wrong in text:
            text = text.replace(wrong, right)
    return text


def _ollama_model(endpoint, preferred):
    """返回 (选定模型名, 可用模型列表)；连不上或没有则返回 (None, [])。"""
    try:
        with urllib.request.urlopen(endpoint + "/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        models = [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return None, []
    if not models:
        return None, []
    if preferred and preferred != "auto" and preferred in models:
        return preferred, models
    # 自动挑选：优先名字含 instruct/chat/coder 的 qwen/llama/gemma/deepseek
    for kw in ("qwen", "llama", "gemma", "deepseek"):
        for m in models:
            ml = m.lower()
            if kw in ml and ("instruct" in ml or "chat" in ml or "coder" in ml):
                return m, models
    return models[0], models


def correct(text, vocab=None):
    """本地大模型纠错（Ollama）。出错/未配置/未运行均回退原文。"""
    cfg = config.load().get("stt", {}).get("correct", {})
    if not cfg.get("enabled", False):
        return text
    endpoint = cfg.get("endpoint", "http://localhost:11434").rstrip("/")
    preferred = cfg.get("model", "auto")
    model, available = _ollama_model(endpoint, preferred)
    if not model:
        log.warning("LLM 纠错跳过：Ollama 未运行或没有可用模型（可用：%s）", available)
        return text
    if vocab is None:
        vocab = _load_vocab()
    vocab_block = "\n".join("- " + v for v in vocab) if vocab else "（无）"
    # 联系人名单：人名是同音错字重灾区（向文成→谢凤您），必须优先纠正
    contact_names = []
    try:
        import contacts as _ct
        contact_names = [c.get("name", "") for c in _ct.list_contacts() if c.get("name")]
    except Exception:
        pass
    # 微信常用收件人动态热词（09-15）：「→路河：」式回复笔记的收件人不一定在联系人库
    # （如大号昵称），但 STT 同样会把它们听错——从微信回复笔记里提取近 20 个收件人。
    try:
        import store as _store
        import re as _re
        seen = set(contact_names)
        for n in _store.list_notes():   # 默认新在前 → 近期收件人优先进入热词
            if len(contact_names) >= 50:
                break
            if n.get("source") != "wechat" and "微信回复" not in (n.get("tags") or []):
                continue
            m = _re.match(r"→([^：]+)：", n.get("text") or "")
            if m:
                who = m.group(1).strip()
                if who and who not in ("当前聊天", "最近聊天") and who not in seen:
                    seen.add(who)
                    contact_names.append(who)
    except Exception:
        pass
    contact_block = "、".join(contact_names) if contact_names else "（暂无）"
    prompt = (
        "你是一个中文语音识别(ASR)纠错助手。下面是本地语音识别的原始结果，"
        "可能存在同音错别字或重复字。\n"
        "用户常用词表（若原文与词表中某词发音相近，优先采用词表中的正确写法）：\n"
        f"{vocab_block}\n\n"
        "联系人名单（用户认识的人；若原文出现与名单发音相近的名字，必须改成名单里的准确写法）：\n"
        f"{contact_block}\n\n"
        "规则（严格遵守）：\n"
        "1. 只修正明显的语音识别错误（同音/近音错别字、重复啰嗦的字词），"
        "不要改动用户真实想表达的意思、语气和句式。\n"
        "2. 必须完整保留原文中的情绪表情符号（😊😡😮😔😰🤢）以及原有标点。\n"
        "3. 不要新增、删减或重述内容，不要添加任何解释、引号或前后缀。\n"
        "4. 若原文基本正确，原样返回。\n"
        "5. 只输出纠正后的纯文本，不要输出任何其他内容。\n\n"
        "原始识别文本：\n" + text + "\n\n纠正后文本："
    )
    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0, "num_predict": 200},
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint + "/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=cfg.get("timeout", 30)) as r:
            data = json.loads(r.read().decode("utf-8"))
        out = (data.get("response") or "").strip()
    except Exception as e:
        log.warning("LLM 纠错失败，保留原文：%s", e)
        return text
    if not out:
        return text
    # 防御：去掉模型可能多带的“纠正后文本：”前缀或首尾引号
    out = re.sub(r"^纠正后文本[：:]\s*", "", out)
    out = out.strip().strip("\"").strip("'").strip()
    if not out:
        return text
    return out


def _highpass_copy(wav_path):
    """vc110 P4：80Hz 高通（scipy butter SOS + 零相位 filtfilt），返回临时副本路径。

    人声基频 >85Hz，教室空调嗡嗡声/桌椅/手持摩擦 <80Hz——滤掉后识别少被杂音带偏。
    只滤临时副本喂模型，原声文件一个字节不动（原声=唯一真相）。
    任何失败（scipy 缺失/非 PCM WAV/太短）都返回原路径，绝不让滤波挡了转写。
    """
    try:
        import wave
        import tempfile
        import numpy as np
        import scipy.signal as sps

        with wave.open(wav_path, "rb") as w:
            sr = w.getframerate()
            nch = w.getnchannels()
            if w.getsampwidth() != 2 or nch < 1:
                return wav_path
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if nch > 1:
            pcm = pcm.reshape(-1, nch).mean(axis=1).astype(np.int16)
        samples = pcm.astype(np.float32) / 32768.0
        if samples.size < sr // 2:
            return wav_path  # 不足半秒不必滤
        sos = sps.butter(2, 80.0, btype="highpass", fs=sr, output="sos")
        filtered = sps.sosfiltfilt(sos, samples).astype(np.float32)
        fd, tmp_path = tempfile.mkstemp(prefix="luyuan_hp_", suffix=".wav")
        os.close(fd)
        with wave.open(tmp_path, "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(sr)
            out.writeframes((filtered * 32767.0).astype(np.int16).tobytes())
        return tmp_path
    except Exception as e:
        log.warning("高通滤波跳过，用原声转写：%s", e)
        return wav_path


def transcribe(wav_path, return_raw=False):
    """对 wav 文件转写。

    返回纠正后的文本（默认）；若 return_raw=True 返回 (纠正后, 原始ASR文本) 元组，
    原始文本用于留底恢复。
    """
    if not os.path.exists(wav_path):
        raise FileNotFoundError(wav_path)
    model = get_model()
    # vc110 P4：转写前滤 <80Hz 教室杂音，只滤临时副本，原声不动
    feed_path = _highpass_copy(wav_path)
    try:
        res = model.generate(
            input=feed_path,
            cache={},
            language="auto",
            use_itn=True,
            batch_size_s=60,
            merge_vad=True,
            merge_length_s=15,
        )
    finally:
        if feed_path != wav_path:
            try:
                os.remove(feed_path)
            except Exception:
                pass
    if not res:
        return ("", "") if return_raw else ""
    raw = res[0].get("text", "")
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess
        raw = rich_transcription_postprocess(raw).strip()
    except Exception:
        raw = re.sub(r"<\|[^|]+\|>", "", raw).strip()

    cleaned = _cleanup(raw)
    cleaned = apply_corrections(cleaned)
    corrected = correct(cleaned)

    if return_raw:
        return corrected, raw
    return corrected
