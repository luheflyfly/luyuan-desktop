"""Spike: 验证 pywebview + WebView2 在本机能开原生窗口，并确认主线程阻塞行为。
3 秒后自动销毁；不依赖 8777。"""
import sys, threading, time
import webview

html = """<!doctype html><meta charset=utf-8>
<body style="background:#F3EFE6;font:16px/1.6 'Microsoft YaHei';padding:40px;color:#224A3A">
<h1>路远 · 壳层自检</h1>
<p>如果你看到这个窗口，说明 WebView2 原生窗口可用。</p>
<p id=t></p>
<script>setInterval(()=>{document.getElementById('t').textContent='运行中 '+new Date().toLocaleTimeString()},500)</script>
</body>"""


def on_loaded(win):
    print("LOADED", flush=True)
    time.sleep(3)
    try:
        win.destroy()
    except Exception as e:
        print("destroy err", e, flush=True)
    print("DESTROYED", flush=True)


w = webview.create_window("路远", html=html, width=900, height=600)
threading.Thread(target=lambda: (time.sleep(1.0), on_loaded(w)), daemon=True).start()
print("START", flush=True)
webview.start(debug=False)
print("EXIT", flush=True)