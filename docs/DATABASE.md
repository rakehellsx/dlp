# PostgreSQL 模块与表对应

完整表字段及 JSON 键见 [DATA-DICTIONARY.md](DATA-DICTIONARY.md)；批量生成 / 导入工具见 [BUSINESS-DATA.md](BUSINESS-DATA.md)。

所有业务查询、检索、分页、统计、配置保存均使用 PostgreSQL。终端采用独立的结构化 `endpoints` 表，其他业务实体使用 `dlp_records` 的 JSONB 模型，由 `(kind,id)` 唯一标识。`dlp_records.endpoint_uid` 是指向终端主键的真实 UUID 外键，关联记录中的 JSON `endpointUid` 与该列同步。

| 导航分组 | 子模块 | 业务表 / 标识 | 其他读取与写入 |
| --- | --- | --- | --- |
| 工作空间 | 安全态势 | `dlp_records`：events / assets / policies / approvals；`endpoints` | 终端数量与状态读取 `endpoints`；SQL 聚合、`dlp_catalogs` 通道字典 |
| 工作空间 | 风险事件 | `dlp_records WHERE kind='events'` | 处置状态、备注写回 `data`；操作写 `operation_logs` |
| 工作空间 | 终端管理 | `endpoints` | `endpoint_uid` 为不可变 UUID 主键，`endpoint_code` 为原 EP 编码；隔离、策略、状态等写入独立字段；通过 UUID 外键关联 events / assets / watermarkImages |
| 工作空间 | 水印追踪 | `dlp_records WHERE kind='watermarkImages'` | `dlp_watermark_images` 保存路径 / 哈希 / MIME / 大小；关联 endpoints / events / watermarks |
| 数据安全 | 防护策略 | `dlp_records WHERE kind='policies'` | 创建、修改、启停、删除均写库；规则选项读取 rules |
| 数据安全 | 数据发现 | `dlp_records WHERE kind IN ('assets','scans')` | 资产查询及统计、扫描任务配置 / 状态 / 进度均来自数据库 |
| 数据安全 | 分类分级 | `dlp_records WHERE kind='rules'` | 规则配置 / 启停持久化；分类资产数量从 assets 聚合 |
| 数据安全 | 通道管控 | `dlp_catalogs WHERE category='channel'` | 通道策略读取 policies，事件与阻断数量从 events 聚合；通道页“配置策略”进入防护策略保存，无独立通道配置表 |
| 数据安全 | 水印管理 | `dlp_records WHERE kind='watermarks'` | type=print / screen / screenshot；内容、样式、生效范围、启停状态等均写 `data` |
| 数据安全 | 外发审批 | `dlp_records WHERE kind='approvals'` | 审批状态、审批意见写回；当前没有独立审批处理时间字段 |
| 运营管理 | 报表中心 | `dlp_records WHERE kind='reports'` | 生成时 SQL 聚合 events / endpoints / assets 并持久化快照，后续预览 / 下载读取快照 |
| 运营管理 | 审计日志 | `operation_logs` | 查询 / 分页 / 筛选 / 导出直接访问该表 |
| 运营管理 | 用户管理 | `users` | 用户查询 / 搜索 / 角色与状态筛选 / 分页 / 统计均使用 SQL；新增 / 删除 / 启停写库，禁用与删除清理 `user_tokens`，操作写 `operation_logs` |
| 运营管理 | 系统设置 | `dlp_settings WHERE id=1` | `data` 保存 company、email、retention、offlineProtection、autoUpdate、notification 等 |

公共表：`users`（账号 / bcrypt 密码 / 角色 / 禁用）、`user_tokens`（登录会话）、`dlp_catalogs`（部门和通道字典）、`dlp_migrations`（初始化及迁移标记）。所有业务写操作在事务中写入并审计。图片二进制是磁盘文件，通过鉴权接口读取；数据库保存图片检索与关联信息，不在浏览器持久化业务副本。

静态界面文字、枚举标签、表单默认值与临时预览状态属于程序；点击保存才写入数据库。系统仍为产品原型，策略下发、扫描进度和终端隔离为模拟行为，配置及模拟结果均持久化，并不表示已经接入实际终端代理或操作系统防护。

## 核对 SQL

```sql
SELECT kind, count(*) FROM dlp_record_view GROUP BY kind ORDER BY kind;
SELECT endpoint_uid, endpoint_code, name, ip_address, username, status, isolated FROM endpoints ORDER BY seq;
SELECT id, data FROM dlp_records WHERE kind='watermarks' ORDER BY seq;
SELECT data FROM dlp_settings WHERE id=1;
SELECT category, key, label, config FROM dlp_catalogs ORDER BY category, position;
SELECT id, hash, mime, original_path, thumbnail_path, size FROM dlp_watermark_images;
SELECT id, operator_name, action, target, created_at FROM operation_logs ORDER BY id DESC LIMIT 20;
```

列表和统计实现：`dlpcenter/services/Queries.cc`；配置与业务写入：`dlpcenter/controllers/DlpController.cc`；表结构和索引：`dlpcenter/sql/init.sql`。数据库通过初始化脚本导入演示数据，运行时不会用 `demo.json` 替代数据库查询。


## 终端唯一标识与关联

- `endpoints.endpoint_uid UUID PRIMARY KEY DEFAULT gen_random_uuid()`：数据库生成，终端改名、换 IP、修改使用人均不会改变。更新主键被数据库触发器拒绝。
- `endpoint_code UNIQUE NOT NULL`：保留 `EP-0001` 等现有编号，作为显示与兼容编号，不作为新业务关联键；名称 / IP 不唯一，不用来维持关联。
- 独立字段：`name`、`username`、`department`、`ip_address`、`os`、`status`、`risk`、`agent_version`、`policy`、`last_seen`、`isolated`、`created_at`、`updated_at`。`extra` 仅保存兼容的扩展属性，不保存上述字段副本。
- `dlp_records.endpoint_uid UUID REFERENCES endpoints(endpoint_uid) ON UPDATE RESTRICT ON DELETE RESTRICT`：风险事件、数据资产、水印追踪以及有明确来源终端的外发申请通过此列关联。已关联终端不能被直接删除。未知来源允许 NULL，不能以 IP / 用户 / 部门猜测。
- 历史 `endpoint`、`ip`、`endpointId` 是发生时的展示快照 / 兼容编码；`endpointUid` 是接口里的 UUID 字段，数据库触发器将它与外键列同步。业务关联只比较 UUID。
- 现有审批记录没有终端来源，保留未关联；全局规则、部门范围策略、报告汇总、用户账号等没有单台终端语义，不强制绑定终端。
- `endpoint_records` 为结构化终端投影，`dlp_record_view` 是只读兼容查询视图（通用业务记录 UNION ALL 终端投影），支持原列表 / 搜索 / 统计接口，不复制终端记录回 JSONB 表。

```sql
SELECT e.endpoint_uid,e.endpoint_code,e.name,r.kind,r.id
FROM endpoints e JOIN dlp_records r ON r.endpoint_uid=e.endpoint_uid
WHERE e.endpoint_code='EP-0001';

SELECT kind,count(*) AS total,count(endpoint_uid) AS linked
FROM dlp_records WHERE kind IN ('events','assets','approvals','watermarkImages') GROUP BY kind;

SELECT kind,id,data->>'endpoint' AS recorded_name,data->>'ip' AS recorded_ip
FROM dlp_records WHERE endpoint_uid IS NULL AND kind IN ('events','assets','approvals','watermarkImages');
```

首次初始化和 SQLite 导入包含终端迁移。已有 PostgreSQL 部署须停服执行 `python scripts/migrate_endpoints.py`，迁移与校验步骤见部署文档。不要再向 `dlp_records` 插入 kind=endpoints；数据库触发器会拒绝。
