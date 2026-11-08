# 路远 · 跨端同步数据格式规范（SYNC_FORMAT）

> **目的**：让电脑端（路远 Python）与手机端（安卓 App）通过 Syncthing 双向同步记事时，使用**同一种数据契约**，避免冲突 / 丢失 / 解析失败。
> **核心原则**：**手机端适配电脑端现有格式，电脑端零改动兼容**；新增字段一律向后兼容（电脑端不读也不报错）。

---

## 一、现状（电脑端，已验证）
- **存储粒度**：每笔记一个独立 JSON 文件
- **目录**：`D:\Luyuan\data\notes\`
- **文件名**：`YYYY-MM-DD_HH-MM-SS_<id前8位>.json`
  - 例：`2026-09-05_13-10-21_e911f055.json`
- **单条结构（实测）**：
```json
{
  "id": "e911f055-12be-46ca-8593-999dfb9822f0",
  "created_at": "2026-09-05T13:10:21+08:00",
  "text": "测试一条手动记事",
  "source": "manual",
  "tags": []
}
```

---

## 二、统一格式（向后兼容扩展）
在现有字段基础上**新增**以下字段；旧字段含义、必填性不变。

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string(UUID) | ✅ | 全局唯一；两端都用 UUID（避免时间戳撞车） |
| `created_at` | string(ISO8601±hh:mm) | ✅ | 创建时间，带时区 |
| `updated_at` | string(ISO8601) | ✅ 新增 | 最后修改时间；冲突解决依据「后者胜」 |
| `text` | string | ✅ | 记事正文（STT 结果或手输） |
| `source` | enum | ✅ | `manual` / `voice` |
| `tags` | string[] | ✅ | 标签 |
| `device` | string | ✅ 新增 | 创建端：`pc` / `phone`，便于过滤与排查 |
| `audio` | string? | ⬜ | 关联音频相对路径（如 `audio/<id>.wav`），无则省略 |
| `transcribed` | bool | ⬜ | 是否已转写（手机录音待电脑转写时为 `false`） |
| `deleted` | bool | ⬜ | 软删标记，默认 `false`（见第四节） |
| `images` | string[]? | ⬜ 新增(2026-09-06) | 关联图片相对路径列表（如 `["images/ab12cd.jpg"]`，实际文件在 notes 同级的 images/ 目录，随 Syncthing 同步）。目前用于日记页；手机端可暂不显示 |
| `remind_at` | string(ISO8601±hh:mm)? | ⬜ 新增(2026-09-06) | 提醒时间；缺省/null=不提醒。PC 端到点弹窗提醒后置 `remind_fired=true`。手机端可不支持（忽略此字段即可） |
| `remind_fired` | bool | ⬜ 新增(2026-09-06) | 提醒是否已触发过（防重复弹）。仅与 `remind_at` 搭配出现 |
| `schema` | int | ✅ 新增 | 格式版本号，当前 `1` |

> **兼容兜底**：电脑端现有笔记缺 `updated_at/device/schema` 时，读取方一律视为
> `updated_at = created_at`、`device = "pc"`、`schema = 1`。手机端读取时做同样兜底。

---

## 三、存储粒度与文件名
- **保持「每笔记一文件」**：对 Syncthing 最友好——新增=新文件不冲突，修改=改单文件。
- **文件名沿用** `创建时间_id前8位.json`；因 `id` 全局唯一，两端不会重名。
- 手机端示例：`2026-09-05_20-30-11_a1b2c3d4.json`

---

## 四、冲突与删除策略
- **同文件两端都改**：Syncthing 生成 `.sync-conflict-<时间戳>` 副本。
  应用层策略：**以 `updated_at` 较新者为主版本**，旧副本保留（不自动删），用户在面板手动合并。
- **删除 = 软删**：不物理删文件，而是置 `deleted: true`。同步后另一端也标记删除（列表隐藏），避免「一端删、另一端复活」。
  彻底清除由用户显式操作。
- **新增**：Syncthing 默认双向，新文件自动出现在对端。

---

## 五、音频文件约定
- 手机录音存 `<共享根>/audio/<id>.wav`（或 `.m4a`）
- note 的 `audio` 字段填相对路径 `audio/<id>.wav`
- 电脑端 STT 处理完写 `text` + 置 `transcribed: true`
- 音频随 Syncthing 一起同步（大文件也 OK）

---

## 六、目录约定（两端对齐）
- 电脑：`D:\Luyuan\data\notes\*.json` + `D:\Luyuan\data\audio\`
- 手机：`/storage/emulated/0/Luyuan/notes/*.json` + `.../audio/`
  - Syncthing 在手机上共享 `Luyuan/` 根目录
- 两边结构一致 → Syncthing 双向同步无缝

---

## 七、两端实现清单
- **电脑端（路远 Python）**：基本零改动。
  - `store.py` 读取时兼容新增字段（缺省兜底）。
  - 可选增强：新建笔记时补 `device:"pc"`、`schema:1`、`updated_at`。
- **手机端（安卓 App）**：严格按本规范读写。
  - 生成 UUID、写 `device:"phone"`、默认 `transcribed:false`、实现软删。
  - 录音写 `audio/` 子目录并填 `audio` 字段。

---

## 八、联系人格式（2026-09-06 新增，PC 端先行；v2 补 kind/relation/note；v3 补 group/sid）
- **目录**：`data/notes/contacts/`（⚠️ 2026-09-06 修正：故意放进 notes 子目录——Syncthing 现有共享只覆盖 data/notes，放这里**手机端零操作自动同步**；笔记扫描器会因缺 text 字段自动跳过联系人文件）一人一文件：`<letter>_<name>.json`（letter=姓氏拼音首字母大写）
- **v2 起**：新写文件带 `"kind": "contact"` 与 `relation`（关系，如"同学"）、`note`（一句话备注）可选字段；
  老文件无 kind 照常识别（目录即语义），读方对 `letter`/`initial` 双写法兼容（同义）。
- **v3 起（2026-09-13）**：新增 `"group"`（分组名，空=未分组）与 `"sid"`（学号，字符串，
  排序取前导数字）。读方对缺字段的老文件必须补默认值 `""`（`contacts._norm()`）；
  手机端不读也不影响——加字段不改旧字段，向后兼容。
- **随 data/ 同步到手机**；手机端暂不读，将来人脉页对齐此格式。
```json
{
  "id": "uuid",
  "name": "向文成",
  "letter": "X",
  "group": "大学同班同学",
  "sid": "18",
  "phone": "",
  "wechat": "",
  "qq": "",
  "birthday": "10月20日",
  "info": ["男", "学号：18"],
  "todos": [
    {"id": "uuid", "text": "帮他带午饭", "done": false, "created_at": "ISO8601",
     "remind_at": "ISO8601 或省略", "reminded": false}
  ],
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```
- `info`：个人信息条目数组（自由文本，如「生日：10月20日」），主界面说「X的生日是…」会自动追加。
- `group` / `sid`（2026-09-13）：`group` 是人脉页的分组（如「大学同班同学」），`sid` 是学号。
  约定：`sid` 是**唯一事实源**，`info` 里那行「学号：X」由 `contacts.sync_sid_info()` 派生并自动
  插到「性别（男/女）那条之后」；改 `sid` 会同步改写该行，清空 `sid` 则删掉该行。
  人脉页选中某个分组时默认按 `sid` 数字升序（无学号的排最后），也可以手动切成按拼音。
- `todos`：与该人相关的待办；未完成 → 联系人页置顶+红点；勾选完成 → 收回普通列表。
- `todos[].remind_at`（2026-09-06 新增，可选）：该待办的提醒时间，到点 PC 弹原生通知后置 `reminded:true`；省略=不提醒。老数据无此字段完全兼容。

## 九、日记（2026-09-06 新增）
- 复用笔记存储：日记=带 `tags:["日记"]` 的普通笔记，一天一条（当天重复保存=更新同一条）。
- 主笔记列表默认**排除**「日记」标签（`/api/notes` 与 `/api/search` 自动排除）；日记页用 `tag=日记` 读取。
- 手机端可见（就是普通笔记），无额外契约。

## 十、SYNC_FORMAT v2（2026-09-07 打包新增，开发计划终稿 §1）

> v2 一次性引入三类 `kind` 实体 + 笔记扩展字段，两端只升一次级。
> **兼容铁律（两端都必须遵守）**：
> 1. 解析器对**未知 `kind` 一律安全跳过**（不显示、不报错、不当坏文件）；
> 2. **未知字段一律忽略**；
> 3. 笔记缺 `updated_at/device/schema` 按原兜底（updated_at=created_at / device=pc / schema=1）。
> 4. 新实体文件**没有 `text` 字段**，笔记扫描器天然跳过（联系人同款机制）。

### 10.1 课程 `kind:"course"`
文件：`course_<id前8位>.json`，存现有同步文件夹（与联系人同模式，随 Syncthing 同步）。
```json
{
  "kind": "course", "id": "uuid", "schema": 2, "device": "pc", "deleted": false,
  "name": "高等数学", "teacher": "王老师", "place": "一教 302",
  "weekday": 1, "start": "08:00", "end": "09:40",
  "weeks": "1-16", "semester": "2026-2027-1",
  "created_at": "ISO8601", "updated_at": "ISO8601"
}
```
- `weekday` 1=周一…7=周日；`weeks` 形如 `1-16`，周次过滤用；`semester` 自由文本。
- `teacher` 存名字快照，与联系人 `name` 精确同名即视为关联（不强制先建联系人）。
- 课堂笔记自动归课**复用现有 tags 字段**（打课程名标签），零格式新增。

### 10.2 消费 `kind:"expense"`
文件：`expense_<id前8位>.json`，同上存储。
```json
{
  "kind": "expense", "id": "uuid", "schema": 2, "device": "pc", "deleted": false,
  "amount": 12.5, "item": "午饭", "category": "餐饮",
  "spent_at": "ISO8601", "source": "screenshot", "image": "inbox/processed/xx.jpg",
  "tags": ["记账"], "created_at": "ISO8601", "updated_at": "ISO8601"
}
```
- `source`: `screenshot`（截图识别）| `manual`（手动补记）；`image` 可选，原图相对路径。
- `category` 可选（餐饮/交通/学习/生活/其他…），缺省="其他"。
- `amount` 数字（元）。

### 10.3 笔记扩展字段（全部可选，旧端忽略）
| 字段 | 类型 | 说明 |
|---|---|---|
| `people` | [{id,name}] | 关联联系人（name 为快照，改名/删除不碎） |
| `todo_done` / `todo_done_at` | bool / ISO? | 待办完成标记与时间 |
| `filed` | contactId? | 被吸收进联系人档案的笔记标记（主列表可隐藏，档案留痕） |

### 10.4 待办 `kind:"todo"`（2026-09-13 新增，手机端先行；PC 端 09-14 起读取、09-15 升级为一级「待办」页）
文件：`todo_<id前8位>.json`，存同步根目录（同 expense/course），**不写 `data/notes`**。
```json
{
  "kind": "todo", "id": "uuid", "schema": 3, "device": "phone", "deleted": false,
  "text": "明天下午三点要交材料", "who": "张三", "when_text": "明天下午三点",
  "raw": "明天下午三点提醒我交材料", "source": "wechat", "sender": "张三",
  "done": false, "done_at": null,
  "created_at": "ISO8601", "updated_at": "ISO8601"
}
```
- 来源：手机端「消息待办」（备用机微信/QQ 通知 → 云端抽取 → 用户确认后才落盘）。
- 📌 **语义（2026-09-15 两端敲定，别再改动）**：手机端点「✓ 收下」才写文件，因此
  **文件出现在同步根目录 = 用户已确认**。PC 端**不得再要求二次「收下」**，只提供
  「✓ 完成」（写 `done` + `done_at`，Syncthing 带回手机）与「✗ 不要」（删文件）。
  手机侧勾完成 → `done:true` 同步回 PC 后，PC 自动移出未完成列表（`todos.list_todos` 按 `done` 过滤）。
- `text` 要办的事；`who` 谁说的；`when_text` 时间描述**原文**（不做结构化，避免猜错）；
  `raw` 原始消息（溯源）；`source` = `wechat` | `qq` | `manual`；`sender` 通知发送者。
- `done` / `done_at` 与笔记的 `todo_done` / `todo_done_at` 语义一致。
- **vc98/v1.31.0 增补（2026-09-18，向后兼容）**：
  - `due_at`（可选，ISO8601 字符串）：截止**绝对时间**——手机端抽取改窗口版后由模型锚定
    抽取时刻算出；空=没识别出截止（回退按 `when_text` 原文展示层解析）。PC 端读取可先忽略，
    `todos.py` 的 done/discard 走「读盘→改字段→回写」，未知字段自然保留。
  - `deleted`（软删墓碑）自此**双端生效**：手机端新增删除/清空已办入口，删=写 `deleted:true`
    （不物理删，避免 Syncthing 删除传播歧义）；PC `list_todos` 本就过滤，无需改码。
    PC 端「✗ 不要」仍是物理删（保留现状，双端语义都成立）。
  - **写入纪律**：手机端对既有待办的任何改动一律「fresh 读盘→只改目标字段→bump `updated_at`
    →写回」，绝不拿旧内存副本整文件覆盖（09-18 诊断的同步病根）；PC 端 `mark_done` 本就如此。
- **vc127 增补（2026-10-20，向后兼容）**：`topic`（可选，string，≤20 字）——**主题标签**，
  由路远远「工作台整理」智能体写入（同活动/同事项的多条待办打同一个 topic，如「团章团纪竞赛」）；
  双端展示为待办卡上的小签，晨报按主题前缀。手机端 Todo 数据类已收录该字段（改完成态不丢）；
  PC `todos.update_fields` 白名单只放 `topic`/`due_at`/`when_text`，**绝不允许智能体改 done/deleted**。
  未知值端按普通字段忽略即可。
  - 手机端抽取侧：同聊天消息攒 5 分钟窗一次性抽取（任务数组合并去重），单窗出网 1 次。
- ✅ **PC 端已实装**：`todos.py` 读取 + `GET /api/todos`、`POST /api/todos/{id}/done`、
  `POST /api/todos/{id}/discard`；面板「待办」页展示与操作。（本节前文那句「PC 端对未知
  `kind` 安全跳过」仍成立——未知 kind 一律跳过，只是 `todo` 已不再未知。）
  ⚠️ 消息待办**只在「待办」页显示**：2026-09-15 起笔记页不再挂待办条（含已办的），
  笔记页只负责笔记。
- 🧾 ~~**挂账（PC 侧，09-18）**：PC「✓ 完成」不可撤销~~ → **已收尾（09-18 晚）**：`todos.unmark` +
  `POST /api/todos/{id}/undone` + 面板已办行「取消完成」按钮，done 翻回 false 后 Syncthing 带回手机。

### 10.5 冲突处理升级（v2，木案模式）
同文件双端修改产生的 `.sync-conflict-*` 副本：面板提供「二选一」界面
（**本机为准 / 云端为准**）供用户一键裁决，替代无限堆积孤儿文件；
裁决前副本照旧保留、解析器照旧跳过（PC 端 v1.31 起）。

### 10.6 汇报 `kind:"report"`（2026-10-19 新增，路远远先行产出；PC 面板同日读取）
文件：`report_<id前8位>.json`，存同步根目录（同 todo/expense/course），**不写 `data/notes` 的笔记命名**。
路远远（luyuan3\路远助手）把原 QQ 私聊播报（晨报/新收录/到点提醒/管家讲解/群简报）改写为此实体
（2026-10-19 路河拍板：QQ 不留播报）；PC 工作台「路远远」页签 + 手机 App 页签两端呈现。
```json
{
  "kind": "report", "id": "uuid", "schema": 3, "device": "pc", "deleted": false,
  "title": "心理普测两份问卷",
  "summary": "不影响评奖毕业；10月20日前两份都提交",
  "category": "管家",
  "text": "【影响】…\n【截止】…\n【入口】…",
  "ref": "todo_xxxxxxxx",
  "source": "luyuanyuan",
  "read": false, "read_at": null,
  "created_at": "ISO8601", "updated_at": "ISO8601"
}
```
- **三件套（2026-10-20 vc126 增补，向后兼容）**：`title`（人话标题，≤30 字，禁文件名/流水句）+
  `summary`（一行摘要，≤60 字，列表第二眼；缺省=渲染端取正文首行兜底）+ `text`（正文，点开再看）。
  列表页只渲染 title+summary+时间+分类签（A 方案，路河 10-20 拍板）。
- `category` 约定枚举：`晨报` / `新收录` / `提醒` / `管家`（通知管家讲解与出稿）/
  `简报`（订阅群摘要）/ `来件`（收件箱文件讲解，原「收件」更名）；未知值按「汇报」兜底展示。
  注：`新收录` 自 2026-10-19 晚起不再产出（待办页/红点已覆盖，工作台不复读）——读侧保留枚举兼容旧数据。
- `ref` 可选：关联实体 id（如来源 todo id），仅供溯源，不做外键约束。
- `read` / `read_at`：**谁点谁写**——fresh 读盘只改 `read`/`read_at`，bump `updated_at` 回写；
  两端都点只分先后，不做每端独立已读。
- 保留策略：同步根按最老先软删封顶 500 条（`reports.py` `_prune_locked`）；单条删除=物理删（同 PC 端 todo ✗不要 款）。
- 路远远侧写入纪律：**只新增文件，绝不改写既有汇报**（Syncthing 零冲突的根本）。
- PC 端 API：`GET /api/reports`（含未读数）、`GET /api/reports/badge`（红点轮询）、
  `POST /api/reports/{id}/read|unread`、`POST /api/reports/read_all`、`POST /api/reports/create`、
  `POST|DELETE /api/reports/{id}/discard|删除`。

*本规范为「去中心化」数据契约的地基。任何一端改动格式前，必须先回到此文档对齐。*
