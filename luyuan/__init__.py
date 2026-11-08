"""路远（Luyuan）· 新大脑包。

设计契约（改代码前先读）：
  1. 任何模块不得直接读写 data/ 下文件 —— 只能走 luyuan.core.store 的仓储。
  2. 任何模块不得自己拼路径 —— 只能走 luyuan.paths。
  3. 任何模型调用只能走 luyuan.ai.gateway（think:false 内建）。
  4. 任何定时任务只能注册到 luyuan.jobs.scheduler，不得自己 while True。
  5. 包内一律绝对导入（from luyuan.x import y）：根目录还躺着旧的 config.py / store.py，
     裸 import 会拿到旧模块。
"""

__version__ = "2.0.0.dev0"
