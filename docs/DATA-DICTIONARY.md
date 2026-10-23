# 数据库及 JSON 字段字典

依据当前建表 SQL、C++ 读写实现及部署库结构核对。数据库为 PostgreSQL，`public` 下共 **9 张表、2 个视图**；自增序列、索引、触发器不是业务表。所有检索、统计、分页、关联和配置均取自数据库；图片原图和缩略图取自私有磁盘目录。

JSON 字段是当前应用约定，不代表 PostgreSQL 对每个 JSON 键都有 NOT NULL / 类型约束。旧记录可能缺少后来新增字段；未列出的自定义扩展属性可存在，应用不一定使用。本文枚举为当前应用使用值。业务 JSON 时间字符串为北京时间 `YYYY-MM-DD HH:mm:ss`，`createdAt` 例外为 Unix 秒；SQL `TIMESTAMPTZ` 是带时区的时间点。

## 1. 全部表及视图

| 对象 | 类型 | 用途 / 关联 |
| --- | --- | --- |
| users | 表 | 账号、角色、禁用状态及密码哈希 |
| user_tokens | 表 | 登录会话，user_id → users.id，删除账号级联清理 |
| operation_logs | 表 | 操作审计，操作者快照；没有到 users 的强外键，保留已删除账号历史 |
| endpoints | 表 | 专门的终端表，endpoint_uid UUID 为不可变主键 |
| dlp_records | 表 | 9 类业务 JSON，(kind,id) 联合主键；endpoint_uid → endpoints.endpoint_uid |
| dlp_settings | 表 | id=1 的系统设置 JSON |
| dlp_catalogs | 表 | 部门和通道字典，(category,key) 联合主键 |
| dlp_watermark_images | 表 | 图片存储索引、哈希和磁盘相对路径 |
| dlp_migrations | 表 | 已执行的初始化 / 迁移标记 |
| endpoint_records | 视图 | endpoints 的接口 JSON 投影，无重复存储 |
| dlp_record_view | 视图 | dlp_records UNION ALL endpoint_records，统一查询 / 统计 |

`dlp_records` 不再存放 kind=endpoints，数据库触发器拒绝该写入。当前 9 个 kind：`events`、`assets`、`policies`、`rules`、`approvals`、`scans`、`reports`、`watermarks`、`watermarkImages`。

### users

| 字段 | SQL 类型 | 可空 / 默认 / 说明 |
| --- | --- | --- |
| id | SERIAL / INTEGER | 主键，自增 |
| username | VARCHAR(64) | 非空、唯一，登录账号 |
| password_hash | VARCHAR(128) | 非空，bcrypt(SHA256十六进制密码)，不存明文 |
| role | VARCHAR(16) | 非空，默认 user；admin / user |
| disabled | BOOLEAN | 非空，默认 false；true 不能登录 |
| created_at | TIMESTAMPTZ | 可空，默认 now() |

### user_tokens

| 字段 | SQL 类型 | 可空 / 默认 / 说明 |
| --- | --- | --- |
| id | SERIAL / INTEGER | 自增主键 |
| user_id | INTEGER | 非空，外键 users.id，ON DELETE CASCADE |
| token | VARCHAR(64) | 非空、唯一，会话凭证，不应导出至业务 JSON |
| expire_at | TIMESTAMPTZ | 非空，过期时间 |
| created_at | TIMESTAMPTZ | 可空，默认 now() |

### operation_logs

| 字段 | SQL 类型 | 可空 / 默认 / 说明 |
| --- | --- | --- |
| id | SERIAL / INTEGER | 自增主键 |
| operator_id | INTEGER | 可空；账号 ID，未登录审计可为 0，脚本导入为 NULL |
| operator_name | VARCHAR(64) | 可空，写入时用户名快照；脚本为 business_data.py |
| action | TEXT | 非空；账号操作如 login/logout/create/delete/disable/enable/change_password，业务操作可为中文描述 |
| target | TEXT | 可空，被操作账号 / 资源 / 文件等 |
| detail | TEXT | 可空；当前既有普通说明，也有 JSON 字符串，并非 JSONB |
| ip | VARCHAR(64) | 可空，操作来源 IP |
| success | BOOLEAN | 非空，默认 true |
| created_at | TIMESTAMPTZ | 可空，默认 now() |

`detail` 没有统一 JSON schema；不要假定每行能强转 JSON。`business_data.py` 导入时写 JSON 计数对象，例如 `{"endpoints":2,"events":6,"skipped":1}`；键是本次新增记录的 kind、settings、catalogs 或 skipped，值为整数。其他登录、用户管理、业务审计的 detail 为说明文本。

### endpoints

| 字段 | SQL 类型 | 可空 / 默认 / 接口映射 |
| --- | --- | --- |
| endpoint_uid | UUID | 非空主键，默认 gen_random_uuid()；JSON endpointUid；更新触发器禁止改变 |
| endpoint_code | TEXT | 非空唯一、禁止空串；JSON id，如 EP-0001 |
| seq | BIGSERIAL / BIGINT | 非空、唯一，用于稳定排序 |
| name | TEXT | 非空，默认空串；终端名称 |
| username | TEXT | 非空，默认空串；JSON user，终端使用人，不是 users 外键 |
| department | TEXT | 非空，默认空串；部门名称快照 |
| ip_address | TEXT | 非空，默认空串；JSON ip；IP 不唯一，不作为关联键 |
| os | TEXT | 非空，默认空串；操作系统 |
| status | TEXT | 非空，默认 offline；online / offline |
| risk | TEXT | 非空，默认 low；high / medium / low |
| agent_version | TEXT | 非空，默认空串；JSON version |
| policy | TEXT | 非空，默认空串；策略名称，非外键 |
| last_seen | TEXT | 非空，默认空串；JSON lastSeen，北京时间字符串 |
| isolated | BOOLEAN | 非空，默认 false；隔离状态 |
| extra | JSONB | 非空，默认 {}；未映射到上述字段的扩展属性，无固定内置键 |
| created_at | TIMESTAMPTZ | 非空，默认 now()；不在现有终端接口投影中 |
| updated_at | TIMESTAMPTZ | 非空，默认 now()；更新触发器维护，不在现有投影中 |

终端接口 JSON 字段（加上 extra 扩展键）：

| 字段 | JSON 类型 | 对应列 / 说明 |
| --- | --- | --- |
| id | string | endpoint_code |
| endpointUid | string(UUID) | endpoint_uid |
| name | string | name |
| user | string | username |
| department | string | department |
| ip | string | ip_address |
| os | string | os |
| status | string | status，online / offline |
| risk | string | risk，high / medium / low |
| version | string | agent_version |
| policy | string | policy，策略名称 |
| lastSeen | string | last_seen，北京时间 |
| isolated | boolean | isolated |

显式结构化字段覆盖同名 extra 键。列表隐藏 UUID 仅影响显示，字段仍由接口返回，详情、检索和关联照常使用。

### dlp_records

| 字段 | SQL 类型 | 可空 / 默认 / 说明 |
| --- | --- | --- |
| seq | BIGSERIAL / BIGINT | 非空、唯一，自增排序序号 |
| kind | TEXT | 非空，与 id 构成主键，业务类型见下文 |
| id | TEXT | 非空，与 kind 构成主键；约定与 data.id 一致 |
| data | JSONB | 非空；字段见第 2 节 |
| endpoint_uid | UUID | 可空；外键 endpoints.endpoint_uid，ON UPDATE / DELETE RESTRICT |

`record_endpoint_sync` 触发器同步 `endpoint_uid` 列与 JSON `endpointUid`。业务关联以 UUID 外键列为准；名称 / IP / 旧编号仅是展示快照。未知来源允许 NULL。新数据应显式填写 endpointUid；不要用历史 endpointId 自动推断来源。`policy`、`policyId`、`rule` 等字符串不具备 SQL 外键约束，部分写接口会额外核验。

### dlp_settings

| 字段 | SQL 类型 | 说明 |
| --- | --- | --- |
| id | INTEGER | 主键，CHECK(id=1)，只有一行 |
| data | JSONB | 非空，全部键见第 3 节 |

### dlp_catalogs

| 字段 | SQL 类型 | 说明 |
| --- | --- | --- |
| category | TEXT | 非空，联合主键；department / channel |
| key | TEXT | 非空，联合主键；稳定字典编码 |
| label | TEXT | 非空，界面中文名称 |
| position | INTEGER | 非空，默认 0，排序位置 |
| config | JSONB | 非空，默认 {}；部门为 {}，通道用 icon 字符串指定图标 |

部门 key：rd、marketing、finance、hr、design、admin。通道 key：im、usb、web、mail、print、clipboard；其 `config.icon` 分别为 message、usb、globe、mail、printer、clipboard。事件 JSON 的 channel 保存中文 label，而非这些 key。

### dlp_watermark_images

| 字段 | SQL 类型 | 说明 |
| --- | --- | --- |
| id | TEXT | 主键，WIMG- 加 12 位大写十六进制；与 watermarkImages 的 JSON id 逻辑对应 |
| original | BYTEA | 可空，旧版本迁移入口；迁移后 NULL，运行接口不读此列 |
| thumbnail | BYTEA | 可空，旧版本迁移入口；迁移后 NULL |
| hash | TEXT | 非空、唯一，原图 SHA-256 十六进制，内容去重依据 |
| mime | TEXT | 非空，image/png、image/jpeg、image/webp |
| original_path | TEXT | 可空（兼容旧库）；当前写入 hash/original，相对 DLP_FILE_ROOT |
| thumbnail_path | TEXT | 可空（兼容旧库）；当前写入 hash/thumbnail.jpg |
| size | BIGINT | 非空，默认 0；原图字节数 |

这张表与 dlp_records(kind=watermarkImages,id) **没有声明复合外键**，由图片接口在同一事务维护逻辑对应。字节、缩略图不进入业务 JSON。删除图片时删除两表记录，接口不再提供图片；不可变磁盘文件保留供备份，需另行做存储回收。

### dlp_migrations

| 字段 | SQL 类型 | 说明 |
| --- | --- | --- |
| name | TEXT | 主键，迁移唯一名称 |
| applied_at | TIMESTAMPTZ | 非空，默认 now() |

已有迁移名包括 endpoints-uuid-v1、image-disk-v1、prototype-demo-v1、watermarks-v1；这是内部兼容标记，不是页面文案，不应通过测试数据工具伪造。

### 查询视图

| 视图 | 字段 | 说明 |
| --- | --- | --- |
| endpoint_records | id TEXT、seq BIGINT、kind TEXT、data JSONB | kind 恒为 endpoints，data 为终端投影 |
| dlp_record_view | seq BIGINT、kind TEXT、id TEXT、data JSONB、endpoint_uid UUID | 合并业务记录与终端投影，用于统一检索统计，不作为写入入口 |

## 2. dlp_records.data 全部应用字段

下表 `string` 为 JSON 字符串、`integer` 为整数、`number` 为数值、`boolean` 为真假、`array<string>` 为字符串数组、`object` 为对象。除特别说明外，字段为当前界面及生成工具约定，并非数据库对 JSON 键的强制约束。

### 通用关联字段

| JSON 路径 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 记录编号，与表列 id 一致；每个 kind 均有 |
| endpointUid | string(UUID)，未关联时省略 | events / assets / approvals / watermarkImages 可使用；与真实外键同步，空串存库后会移除 |
| endpointId | string，可选 | 历史终端编码，events 常见；兼容导入可使用，新的关联采用 endpointUid |
| endpoint | string，可选 | 发生时终端名称快照 |
| ip | string，可选 | 发生时 IP 快照 |

endpointUid 仅能绑定真实存在的终端。全局策略、分类规则、扫描任务及汇总报告没有单终端语义，默认不绑定。

### events：风险事件

| 字段 | 类型 | 含义 / 取值 |
| --- | --- | --- |
| id | string | 事件编号 |
| title | string | 事件标题 |
| file | string | 涉及文件名 |
| user | string | 使用人快照 |
| department | string | 部门快照 |
| endpoint | string | 终端名称快照 |
| endpointId | string | 历史终端编号 |
| endpointUid | string(UUID)，可选 | 终端外键投影 |
| ip | string | 事件来源 IP |
| channel | string | 即时通讯 / USB 外设 / 浏览器上传 / 电子邮件 / 打印输出 / 剪贴板等通道标签 |
| severity | string | high / medium / low |
| action | string | blocked（阻断）/ audited（审计） |
| status | string | pending / processing / resolved |
| time | string | 发生时间 |
| policy | string | 命中策略名称快照，非外键 |
| matches | integer | 命中次数 |
| destination | string | 外发目的地描述 |
| size | string | 格式化文件大小，如 2.4 MB，不是字节数 |
| note | string | 处置备注 |

### assets：数据资产

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 资产编号 |
| name | string | 文件名称 |
| type | string | 分类名称，对应规则名称语义 |
| level | string | high / medium / low |
| endpoint | string | 来源终端快照 |
| endpointUid | string(UUID)，可选 | 来源终端外键投影 |
| department | string | 部门快照 |
| owner | string | 资产所有人 |
| path | string | 终端上的路径描述，不表示服务器存在该文件 |
| matches | integer | 识别命中数 |
| size | string | 格式化文件大小 |
| time | string | 发现时间 |

### policies：防护策略

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 策略编号 |
| name | string | 策略名称 |
| rule | string | 分类规则名称，非规则 ID 外键 |
| channels | string | 中文通道列表，使用顿号分隔；当前不是 JSON 数组 |
| action | string | block / audit / approval / watermark |
| scope | string | 全体终端或部门名称 |
| enabled | boolean | 启用状态 |
| priority | integer | 优先级 |
| updated | string | 更新时间 |
| description | string | 策略说明 |

### rules：分类分级规则

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 分类规则编号 |
| name | string | 分类名称 |
| method | string | 正则表达式 / 关键词匹配 / 文件特征等配置标签 |
| level | string | high / medium / low |
| description | string | 说明 |
| enabled | boolean | 启用状态 |
| keywords | string | 逗号分隔关键词，当前不是数组 |
| updated | string，可选 | 通过保存接口创建或修改时写入，旧初始化记录可能没有 |

### approvals：外发审批

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 申请编号 |
| user | string | 申请人 |
| department | string | 部门 |
| file | string | 文件名 |
| channel | string | 中文外发通道名称 |
| recipient | string | 接收方 |
| reason | string | 申请理由 |
| status | string | pending / approved / rejected |
| time | string | 申请时间；当前审批接口不另存处理时间字段 |
| comment | string | 审批意见 |
| endpointUid | string(UUID)，可选 | 有明确终端来源时保存；已有未提供来源的记录保持未关联 |
| endpoint | string，可选 | 来源名称快照，可由导入提供 |

### scans：扫描任务

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 任务编号 |
| name | string | 任务名 |
| scope | string | 全体终端或部门名称 |
| status | string | running / completed |
| progress | integer | 0–100，完成百分比 |
| found | integer | 发现资产数 |
| started | string | 开始时间，北京时间字符串 |
| createdAt | number | Unix 秒，当前接口写整数，旧初始化可能是小数 |

### reports：运营报告

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | 报告编号 |
| name | string | 报告名称 |
| period | string | 最近7天 / 最近30天 / 全部数据 |
| time | string | 生成时间 |
| status | string | completed |
| events | integer | 周期内事件数 |
| blocked | integer | 周期内阻断数 |
| high | integer | 周期内高风险事件数 |
| pending | integer | 周期内待处理事件数 |
| endpoints | integer | 生成时终端总量，不受事件周期限制 |
| assets | integer | 生成时资产总量，不受事件周期限制 |

计数直接位于报告根对象，**不存在 snapshot 子对象**。报告保存的是生成时快照，之后事件处置不会改写旧报告。生成脚本中的报告只统计同一 JSON 批次；控制台“生成报告”统计当前数据库。

### watermarks：水印管理

| 字段 | 类型 | 含义 / 范围 |
| --- | --- | --- |
| id | string | WM- 开头策略编号 |
| name | string | 名称，1–80字符 |
| type | string | print / screen / screenshot |
| content | string | 水印模板，1–240字符，最多4行 |
| scope | string | 全体终端或部门名称 |
| condition | string | always / sensitive / apps |
| fontFamily | string | Microsoft YaHei / SimSun / Arial |
| fontSize | integer | 12–48 |
| color | string | #RRGGBB |
| opacity | integer | 5–80，百分比 |
| angle | integer | -90–90，角度 |
| spacing | integer | 100–360，平铺间距 |
| position | string | tile / center / top / bottom |
| priority | integer | 1–999 |
| enabled | boolean | 是否启用 |
| bold | boolean | 是否加粗 |
| apps | array<string> | Office 文档 / PDF 阅读器 / 浏览器 / 即时通讯 / 其他应用；condition=apps 时至少一个 |
| paperSize | string | A4 / A3，打印设置 |
| printers | string | 打印机范围，最多200字符 |
| bothSides | boolean | 双面打印水印设置 |
| screenTarget | string | all / primary，屏幕范围 |
| screenshotMethods | array<string> | system / tools / clipboard；截屏水印至少一个 |
| description | string | 策略说明，最多240字符 |
| updated | string | 最近更新时间 |

模板变量仅支持：`{企业名称}`、`{姓名}`、`{账号}`、`{部门}`、`{终端}`、`{终端IP}`、`{时间}`、`{文档名称}`。三类水印共用这些字段，具体场景只使用其中相关字段。

### watermarkImages：水印追踪

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| id | string | WIMG- 加12位大写十六进制编号 |
| title | string | 图片标题，最多100字符 |
| filename | string | 原始文件名，不含客户端目录 |
| type | string | print / screen / screenshot / unknown |
| status | string | pending（待核验）/ reviewed（已核验），独立于 OCR 状态 |
| code | string | 水印编码，最多128字符 |
| user | string | 核验后的使用人，最多80字符 |
| department | string | 核验后的部门，最多80字符 |
| endpoint | string | 核验后的终端名称快照，最多120字符 |
| endpointUid | string(UUID)，可选 | 核验后确认的来源终端外键，非候选匹配结果 |
| ip | string | IPv4 / IPv6，最多45字符 |
| time | string | 水印记录的时间；输入带时区时转为北京时间 |
| policyId | string | 关联 watermarks.id，可空，保存接口会检查存在性 |
| content | string | 核验后的水印正文，最多4000字符 |
| note | string | 备注 / 核验依据，最多1000字符 |
| size | integer | 原图字节数 |
| width | integer | EXIF方向修正后的宽度（像素） |
| height | integer | EXIF方向修正后的高度（像素） |
| format | string | PNG / JPEG / WEBP |
| mime | string | image/png / image/jpeg / image/webp |
| hash | string | 原图 SHA-256，64位十六进制 |
| camera | string | EXIF厂商和型号，缺失为空 |
| capturedAt | string | EXIF拍摄时间原文，缺失为空；不等于水印 time |
| actor | string | 导入人用户名快照；工具导入为 business_data.py |
| importedAt | string | 导入时间 |
| updated | string | 最近人工保存时间；OCR 用独立 ocrTime |
| ocrState | string | not_run / completed / empty；当前识别失败返回错误，不保存 failed 状态 |
| ocrText | string | OCR原文，最多16000字符 |
| ocrTime | string | 最近一次成功完成识别的时间；未运行为空 |
| ocrSuggestions | object | 最近一次提取的候选字段，新版本 OCR 自动入库；旧记录可能没有 |

`ocrSuggestions` 是候选对象，字段可缺失，不代表均已识别：

| JSON 路径 | 类型 | 来源 |
| --- | --- | --- |
| ocrSuggestions.code | string | WM- / WM_ 或 WIMG- 格式编码匹配 |
| ocrSuggestions.ip | string | OCR中合法IPv4；匹配到终端后可补充终端IP |
| ocrSuggestions.time | string | OCR中日期 / 时间格式匹配 |
| ocrSuggestions.endpoint | string | 名称 / IP 在数据库中唯一匹配的终端 |
| ocrSuggestions.endpointUid | string(UUID) | 唯一匹配终端的UUID；不直接写入正式外键 |
| ocrSuggestions.user | string | 唯一匹配终端的使用人 |
| ocrSuggestions.department | string | 唯一匹配终端的部门 |
| ocrSuggestions.policyId | string | 文本命中已存水印策略ID或名称时的策略ID |
| ocrSuggestions.type | string | 关联策略的 print / screen / screenshot |

识别原文和候选字段自动入库，人工确认后通过 `/api/watermark-images/save` 写入根对象字段及真实外键。仅做 OCR 不把 pending 自动变为 reviewed，也不会覆盖已核验信息。姓名 / 部门目前通过终端匹配补充，并非任意图片中姓名的通用语义识别。

## 3. 系统设置 JSON（dlp_settings.data）

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| company | string | 企业名称，必填，最多100字符 |
| email | string | 通知邮箱，可空 |
| retention | integer | 保存天数，7–3650 |
| offlineProtection | boolean | 离线防护开关 |
| autoUpdate | boolean | 自动更新开关 |
| notification | boolean | 事件通知开关 |
| watermark | string | 全局水印文案配置 |

## 4. 关系、索引及校验要点

- 真外键：user_tokens.user_id → users.id；dlp_records.endpoint_uid → endpoints.endpoint_uid。
- 逻辑关联：图片索引 id 与 watermarkImages.id；policyId 与 watermarks.id；策略 rule / 通道 / 部门名称。逻辑字段不是 SQL 外键。
- 主键 / 唯一索引：账号 username、Token token、终端 endpoint_code / seq、记录 (kind,id) / seq、图片 hash、字典 (category,key)。
- 检索索引：dlp_records 的 JSONB GIN、kind+seq、status、department、历史 endpointId、time、endpoint_uid+kind；endpoints 的 status、department、name、ip_address。
- 审计索引：created_at、action、operator_id；会话索引：token、expire_at。
- SQL 源码：`dlpcenter/sql/init.sql`、`dlpcenter/sql/endpoints.sql`。应用验证：`services/Validation.cc`、`controllers/DlpController.cc`、`services/Queries.cc`。
- 测试数据生成 / 导入说明见 [BUSINESS-DATA.md](BUSINESS-DATA.md)，模块到表映射见 [DATABASE.md](DATABASE.md)。

核对实际部署自定义 JSON 键：

```sql
SELECT table_name,column_name,data_type,is_nullable,column_default
FROM information_schema.columns WHERE table_schema='public'
ORDER BY table_name,ordinal_position;
SELECT kind,jsonb_object_keys(data) AS field
FROM dlp_records GROUP BY 1,2 ORDER BY 1,2;
SELECT jsonb_object_keys(data) AS field FROM dlp_settings;
SELECT category,key,config FROM dlp_catalogs ORDER BY category,position;
SELECT endpoint_code,extra FROM endpoints WHERE extra<>'{}'::jsonb;
SELECT DISTINCT jsonb_object_keys(data->'ocrSuggestions') AS candidate_field
FROM dlp_records WHERE kind='watermarkImages' AND jsonb_typeof(data->'ocrSuggestions')='object';
```
