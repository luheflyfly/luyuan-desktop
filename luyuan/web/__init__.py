"""Web 层：FastAPI 应用的**唯一装配处**。

旧结构里 server.py（879 行）+ router.py（1600 行 / 84 条路由）互相 import、
共用一堆模块级全局，谁也说不清 app 是在哪儿配起来的。
新规则：只有 `create_app()` 能构造 app，路由按域放在 routes/ 下，每个文件
声明自己的 APIRouter，不许 import 别的路由文件。
"""
