"""下载路远所需的本地语音模型文件（完全离线，不依赖 ModelScope 自动下载）。
用法: D:\Luyuan\.venv\Scripts\python.exe download_models.py
"""
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = r"D:\Luyuan\models"
RESOLVE = "https://www.modelscope.cn/models/{repo}/resolve/master/{path}"

# (本地目录, 模型repo, 远程文件名)  —— 只取推理必需文件，跳过 example/fig/README
JOBS = [
    # SenseVoiceSmall
    ("SenseVoiceSmall", "iic/SenseVoiceSmall", "model.pt"),
    ("SenseVoiceSmall", "iic/SenseVoiceSmall", "config.yaml"),
    ("SenseVoiceSmall", "iic/SenseVoiceSmall", "am.mvn"),
    ("SenseVoiceSmall", "iic/SenseVoiceSmall", "tokens.json"),
    ("SenseVoiceSmall", "iic/SenseVoiceSmall", "configuration.json"),
    ("SenseVoiceSmall", "iic/SenseVoiceSmall", "chn_jpn_yue_eng_ko_spectok.bpe.model"),
    # VAD
    ("VAD", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "model.pt"),
    ("VAD", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "config.yaml"),
    ("VAD", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "am.mvn"),
    ("VAD", "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch", "configuration.json"),
]


def fetch(job):
    local_dir, repo, path = job
    out_dir = os.path.join(BASE, local_dir)
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, path)
    if os.path.exists(out) and os.path.getsize(out) > 0:
        return f"skip  {local_dir}/{path}"
    url = RESOLVE.format(repo=repo, path=path)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as f:
        f.write(r.read())
    return f"OK    {local_dir}/{path} ({os.path.getsize(out)//1024} KB)"


if __name__ == "__main__":
    with ThreadPoolExecutor(max_workers=4) as ex:
        for msg in ex.map(fetch, JOBS):
            print(msg)
    print("ALL MODEL FILES READY")
