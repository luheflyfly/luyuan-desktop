# -*- coding: utf-8 -*-
"""语义搜索：本地 bge-small-zh 模型给笔记建"意思索引"，搜意思不只搜字。

设计约束：
- 懒加载：第一次用到才载模型（约 20 秒），之后常驻。
- 增量索引：每条笔记按 id+正文哈希缓存向量，新改的笔记才算，其余复用。
- 绝不抛错出去：模型/索引任何问题，调用方拿到的就是空结果，关键字搜索照常。
"""
import os
import json
import hashlib
import logging

import config
import store

log = logging.getLogger("semsearch")

_MODEL_DIR_NAME = "models/bge-small-zh-v1.5"
_INDEX_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "data", "sem_index.json")
_MIN_SCORE = 0.45   # bge 余弦：相关句约 0.6+，无关约 0.3-，取中间偏下
_TOP_K = 5

_tok = None
_model = None
_index = None   # {id: {"hash":..., "vec":[...]}}


def _enabled():
    return config.load().get("stt", {}).get("semsearch", {}).get("enabled", True)


def _load_model():
    global _tok, _model
    if _model is not None:
        return True
    d = config.abs_path(_MODEL_DIR_NAME)
    if not os.path.isdir(d):
        log.warning("语义模型目录不存在：%s", d)
        return False
    from transformers import AutoTokenizer, AutoModel
    import torch
    _tok = AutoTokenizer.from_pretrained(d)
    _model = AutoModel.from_pretrained(d)
    _model.eval()
    return True


def _embed(texts):
    import torch
    enc = _tok(texts, padding=True, truncation=True, max_length=256,
               return_tensors="pt")
    with torch.no_grad():
        out = _model(**enc)
    v = out.last_hidden_state[:, 0]
    return torch.nn.functional.normalize(v, dim=1)


def _load_index():
    global _index
    if _index is not None:
        return _index
    try:
        with open(_INDEX_PATH, "r", encoding="utf-8") as f:
            _index = json.load(f)
    except Exception:
        _index = {}
    return _index


def _save_index():
    try:
        os.makedirs(os.path.dirname(_INDEX_PATH), exist_ok=True)
        with open(_INDEX_PATH, "w", encoding="utf-8") as f:
            json.dump(_index, f, ensure_ascii=False)
    except Exception as e:
        log.warning("索引保存失败：%s", e)


def _text_hash(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def _ensure_index(notes):
    """增量补齐缺失/已变更笔记的向量。返回 id 列表与向量矩阵(嵌套 list)。"""
    idx = _load_index()
    need = []
    for n in notes:
        h = _text_hash(n.get("text", ""))
        rec = idx.get(n["id"])
        if not rec or rec.get("hash") != h:
            need.append(n)
    if need:
        if not _load_model():
            return None
        vecs = _embed([n.get("text", "") for n in need])
        for n, v in zip(need, vecs.tolist()):
            idx[n["id"]] = {"hash": _text_hash(n.get("text", "")), "vec": v}
        _save_index()
    return idx


def search(q, exclude=None, top_k=_TOP_K):
    """语义搜索。返回附了 _semantic/_score 的 note 列表；任何失败返回 []。"""
    exclude = exclude or set()
    if not (q or "").strip() or not _enabled():
        return []
    try:
        notes = store.list_notes(limit=500)
        if not notes:
            return []
        idx = _ensure_index(notes)
        if idx is None:
            return []
        qv = _embed([q.strip()])[0].tolist()
        scored = []
        for n in notes:
            rec = idx.get(n["id"])
            if not rec or n["id"] in exclude:
                continue
            score = sum(a * b for a, b in zip(qv, rec["vec"]))
            if score >= _MIN_SCORE:
                scored.append((score, n))
        scored.sort(key=lambda x: -x[0])
        out = []
        for score, n in scored[:top_k]:
            n = dict(n)
            n["_file"] = n.get("_file")
            n["_semantic"] = True
            n["_score"] = round(score, 3)
            out.append(n)
        log.info("semsearch %r -> %d hits", q, len(out))
        return out
    except Exception as e:
        log.warning("语义搜索失败（回退空）：%s", e)
        return []
