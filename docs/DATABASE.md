# PostgreSQL 模块与表对应

所有业务查询、检索、分页、统计、配置保存均使用 PostgreSQL。当前为原型的通用 JSONB 模型：业务实体共用 `dlp_records`，由 `(kind,id)` 唯一标识，具体字段在 `data` 中；并非每个模块各建一张表。

| 导航分组 | 子模块 | 业务表 / 标识 | 其他读取与写入 |
| --- | --- | --- | --- |
| 工作空间 | 安全态势 | `dlp_records`：events / endpoints / assets / policies / approvals | SQL 聚合、`dlp_catalogs` 通道字典 |
| 工作空间 | 风险事件 | `dlp_records WHERE kind='events'` | 处置状态、备注写回 `data`；操作写 `operation_logs` |
| 工作空间 | 终端管理 | `dlp_records WHERE kind='endpoints'` | 隔离状态写回；关联风险事件查询 events |
| 工作空间 | 水印追踪 | `dlp_records WHERE kind='watermarkImages'` | `dlp_watermark_images` 保存路径 / 哈希 / MIME / 大小；关联 endpoints / events / watermarks |
| 数据安全 | 防护策略 | `dlp_records WHERE kind='policies'` | 创建、修改、启停、删除均写库；规则选项读取 rules |
| 数据安全 | 数据发现 | `dlp_records WHERE kind IN ('assets','scans')` | 资产查询及统计、扫描任务配置 / 状态 / 进度均来自数据库 |
| 数据安全 | 分类分级 | `dlp_records WHERE kind='rules'` | 规则配置 / 启停持久化；分类资产数量从 assets 聚合 |
| 数据安全 | 通道管控 | `dlp_catalogs WHERE category='channel'` | 通道策略读取 policies，事件与阻断数量从 events 聚合；通道页“配置策略”进入防护策略保存，无独立通道配置表 |
| 数据安全 | 水印管理 | `dlp_records WHERE kind='watermarks'` | type=print / screen / screenshot；内容、样式、生效范围、启停状态等均写 `data` |
| 数据安全 | 外发审批 | `dlp_records WHERE kind='approvals'` | 审批状态、驳回原因、操作时间写回 |
| 运营管理 | 报表中心 | `dlp_records WHERE kind='reports'` | 生成时 SQL 聚合 events / endpoints / assets 并持久化快照，后续预览 / 下载读取快照 |
| 运营管理 | 审计日志 | `operation_logs` | 查询 / 分页 / 筛选 / 导出直接访问该表 |
| 运营管理 | 系统设置 | `dlp_settings WHERE id=1` | `data` 保存 company、email、retention、offlineProtection、autoUpdate、notification 等 |

公共表：`users`（账号 / bcrypt 密码 / 角色 / 禁用）、`user_tokens`（登录会话）、`dlp_catalogs`（部门和通道字典）、`dlp_migrations`（初始化及迁移标记）。所有业务写操作在事务中写入并审计。图片二进制是磁盘文件，通过鉴权接口读取；数据库保存图片检索与关联信息，不在浏览器持久化业务副本。

静态界面文字、枚举标签、表单默认值与临时预览状态属于程序；点击保存才写入数据库。系统仍为产品原型，策略下发、扫描进度和终端隔离为模拟行为，配置及模拟结果均持久化，并不表示已经接入实际终端代理或操作系统防护。

## 核对 SQL

```sql
SELECT kind, count(*) FROM dlp_records GROUP BY kind ORDER BY kind;
SELECT id, data FROM dlp_records WHERE kind='watermarks' ORDER BY seq;
SELECT data FROM dlp_settings WHERE id=1;
SELECT category, key, label, config FROM dlp_catalogs ORDER BY category, position;
SELECT id, hash, mime, original_path, thumbnail_path, size FROM dlp_watermark_images;
SELECT id, operator_name, action, target, created_at FROM operation_logs ORDER BY id DESC LIMIT 20;
```

列表和统计实现：`dlpcenter/services/Queries.cc`；配置与业务写入：`dlpcenter/controllers/DlpController.cc`；表结构和索引：`dlpcenter/sql/init.sql`。数据库通过初始化脚本导入演示数据，运行时不会用 `demo.json` 替代数据库查询。
