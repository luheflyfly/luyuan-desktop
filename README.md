# 路远 · 桌面端（Luyuan Desktop）

**本地优先的个人语音记事与日程系统。** 按一个键说一句话，本机转写、自动归类、按时提醒；
数据只在你自己的机器与 Syncthing 目录里，没有服务端、没有账号、没有遥测。

> 手机端（安卓 App，Kotlin + Compose）：[luheflyfly/luyuan](https://github.com/luheflyfly/luyuan)
> 两端共用同一份 JSON，通过 Syncthing 双向同步。

---

## 一、它做什么

| 能力 | 说明 |
|---|---|
| **语音记一笔** | 全局热键（默认 F10）按下即录，本机 STT 转写，自动分类入笔记；支持唤醒词「路远」 |
| **自动整理** | 晨报 / 周报 / 复盘自动生成；日记到点提醒；桌面悬浮岛显示当日要点 |
| **待办与提醒** | 从笔记里抽待办；课前提醒、天气提醒、生日提醒、日程冲突检测 |
| **课表与学期** | 按教学周 / 单双周 / 调课计算，"下周三"这类中文相对日期直接解析 |
| **消息转待办** | 监听通知与聊天窗口（微信），把「要回谁、要做什么」落成待办；通知按钮可直接作答 |
| **三端一致** | 桌面面板（pywebview）+ 手机 App 读同一份笔记 JSON，改动走 Syncthing 同步 |
| **全离线可跑** | 转写用本地模型（SenseVoice），对话可回落本地 Ollama；云端 API 只在显式配置后启用 |

## 二、架构

```
main.py              入口：托盘 + 全局热键 + 后台调度
server.py            本地 HTTP 服务（默认 8777），面板与手机端都走它
router.py            意图分诊：一句话判断该记笔记、加待办、查课表还是问模型
store.py             笔记存储（Markdown + JSON 索引，带回收站与版本）
luyuan/              核心包
  ├── core/          配置、日志、路径
  ├── io/            同步、推送、文件读写
  ├── jobs/          调度器与各类提醒任务
  └── web/           路由与应用装配
ui/                  桌面面板（panel.html / app.js / modules.js）+ 手机 Web 版
desktop/shell.py     桌面壳（pywebview + 打包脚本 Luyuan.spec）
stt.py / smart.py    本地转写、模型问答与兜底
courses.py / csu.py  课表、学期与校历
wechat.py / transwatch.py   消息监听与转待办
tests/               单元与冒烟测试
```

## 三、跑起来

```bash
# 1) 依赖（Python 3.11+）
pip install -r requirements.txt

# 2) 配置：模板复制成 config.json，填自己的路径与 key
cp config.example.json config.json      # Windows: copy config.example.json config.json

# 3) 模型：本地转写模型按需下载（首次约 1 GB，缓存在 models/）
python download_models.py

# 4) 启动
python main.py            # 或双击 launch.bat
```

**必需**：Windows 10/11、Python 3.11+。
**可选**：Syncthing（三端同步）、Ollama（本地模型问答）、微信客户端（消息转待办）。

## 四、打包成 exe（Windows 单机版）

```bat
pip install pyinstaller
cd desktop
build_shell.bat
:: 产物：desktop\dist\Luyuan\Luyuan.exe
```

打包用 PyInstaller onedir 模式（`desktop/Luyuan.spec`），webview / pythonnet / pystray 全部 collect-all。
`build_shell.bat` 里的解释器优先读环境变量 `PY`，没设就用 PATH 里的 `python`。

## 五、隐私与数据

- **没有服务端**：所有数据在你本机，`data/` 目录 + Syncthing 同步目录。
- **没有遥测**：代码里没有任何上报端点。
- **密钥只在本地**：`config.json` 已在 `.gitignore` 中，永不入库；模板里是 `PASTE_YOUR_KEY_HERE`。
- **私密内容默认不外发**：`privacy.allow_private_outbound` 默认 `false`，要发必须显式登记来源。

## 六、状态

- 桌面端：长期自用、按周迭代（`PROGRESS.md` 在私有分支维护，本仓库只放可运行代码）。
- 重构进行中：模块已按 `luyuan/core|io|jobs|web` 分层，旧脚本仍在根目录待迁移。
- 手机端：[luheflyfly/luyuan](https://github.com/luheflyfly/luyuan)（versionCode 131，已发布正式包）。

## 七、许可

[MIT](LICENSE) © 2026 路河
