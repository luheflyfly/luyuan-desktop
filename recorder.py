"""麦克风录音：固定时长 + 基于能量的端点检测（说完自动停）。"""
import queue
import time
import numpy as np
import sounddevice as sd
import soundfile as sf
import config


def record_wav(path, duration=6.0, samplerate=None):
    """固定时长录音（用于测试 / P1）。"""
    if samplerate is None:
        samplerate = int(config.load().get("samplerate", 16000))
    sd.default.samplerate = samplerate
    sd.default.channels = 1
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate,
                   channels=1, dtype="float32")
    sd.wait()
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if 0 < peak < 1.0:
        audio = audio / max(peak, 1e-6) * 0.9
    sf.write(path, audio, samplerate)
    return path


def record_until_silence(path, samplerate=None, max_seconds=12,
                         silence_seconds=1.2, min_seconds=0.6, threshold=0.012):
    """录音直到检测到静音或超时才停。返回 wav 路径。
    用法：用户开口说，说完停顿 silence_seconds 即自动保存。"""
    if samplerate is None:
        samplerate = int(config.load().get("samplerate", 16000))
    q = queue.Queue()
    frames = []
    speech_started = False
    silence_start = None
    start = time.time()

    def cb(indata, frames_count, time_info, status):
        q.put(indata.copy())

    try:
        with sd.InputStream(samplerate=samplerate, channels=1,
                            dtype="float32", callback=cb):
            while True:
                elapsed = time.time() - start
                if elapsed > max_seconds:
                    break
                try:
                    data = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                frames.append(data)
                rms = float(np.sqrt(np.mean(data ** 2)))
                if rms > threshold:
                    speech_started = True
                    silence_start = None
                elif speech_started:
                    if silence_start is None:
                        silence_start = time.time()
                    elif time.time() - silence_start > silence_seconds and elapsed > min_seconds:
                        break
    except sd.PortAudioError as e:
        raise RuntimeError(f"麦克风不可用: {e}")
    except Exception as e:
        raise RuntimeError(f"录音失败: {e}")

    if not frames:
        raise RuntimeError("未检测到麦克风输入")

    audio = np.concatenate(frames, axis=0)
    sf.write(path, audio, samplerate)
    return path


def record_until_stop(path, stop_event, samplerate=None, max_seconds=120):
    """录音直到 stop_event 被置位，或达到安全上限 max_seconds（秒）才停。
    用法：用户开口说，想停就手动触发 stop_event（按钮 / 再按一次热键）。"""
    if samplerate is None:
        samplerate = int(config.load().get("samplerate", 16000))
    q = queue.Queue()
    frames = []
    start = time.time()

    def cb(indata, frames_count, time_info, status):
        q.put(indata.copy())

    try:
        with sd.InputStream(samplerate=samplerate, channels=1,
                            dtype="float32", callback=cb):
            while True:
                if stop_event.is_set():
                    break
                if time.time() - start > max_seconds:
                    break
                try:
                    data = q.get(timeout=0.4)
                except queue.Empty:
                    continue
                frames.append(data)
    except sd.PortAudioError as e:
        raise RuntimeError(f"麦克风不可用: {e}")
    except Exception as e:
        raise RuntimeError(f"录音失败: {e}")

    if not frames:
        raise RuntimeError("未检测到麦克风输入（是否没说话或麦克风被占用？）")

    audio = np.concatenate(frames, axis=0)
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if 0 < peak < 1.0:
        audio = audio / max(peak, 1e-6) * 0.9
    sf.write(path, audio, samplerate)
    return path


if __name__ == "__main__":
    # 直接运行可手动测试：说一句话，自动停止。
    import sys
    out = "temp_rec.wav"
    print("请开口说话，说完停顿约 1 秒自动保存…")
    try:
        record_until_silence(out)
        print("已保存:", out)
    except Exception as e:
        print("错误:", e)
        sys.exit(1)
