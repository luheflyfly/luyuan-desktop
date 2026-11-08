"""路远的数据域（core）：所有落盘的记录都从这里进出。

一个域 = 一个仓储子类（见 store.JsonRepo），不写额外的 if/else。
旧结构里 todo / expense / course / contact / report 各有一套读写，字段校验
散在 router.py 的 84 个路由里；现在每个域自己声明字段白名单。
"""
