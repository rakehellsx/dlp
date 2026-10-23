# Sentinel DLP · 终端数据防泄漏产品原型

一套独立部署、中文界面的可交互产品原型。前端为原生 JavaScript/CSS/SVG；服务端基于提供的 `dlpcenter` 代码，使用 C++17 / Drogon，统一存储于 PostgreSQL。Python 仅负责图片处理、数据库初始化与运维脚本，可见文字识别使用本地 Tesseract，无需 Node.js 或外部 CDN。

## 快速开始

完整安装、Nginx / systemd 配置、演示数据导入、升级和备份恢复步骤见 [部署文档](docs/DEPLOYMENT.md)。

- 登录入口：`http://<服务器IP>:8090`
- 管理员账号：`admin`，首次密码通过 `DLP_ADMIN_PASSWORD` 设置。
- 水印追踪入口：`/#watermark-images`，位于“工作空间”下。
- 仓库不包含运行数据库、上传图片或部署凭据。

## 功能

1. 安全态势：统计周期、终端与事件指标、风险趋势、外发通道分布、部门排行和事件下钻。
2. 风险事件：关键词、风险、通道及部门筛选；分页、多选批量处置、备注、演示数据流转溯源。
3. 终端管理：终端检索与筛选、详情、关联事件和模拟隔离/解除隔离。
4. 防护策略：新建、编辑、删除、启停；识别规则、通道、动作、优先级与范围配置。
5. 数据发现：创建模拟扫描任务、自动进度、资产清单与详情、资产导出。
6. 分类分级：规则配置、启停、关键词识别与内置手机号码/身份证格式识别测试。
7. 通道管控：六类通道的关联策略、风险事件与阻断统计，可跳转配置。
8. 外发审批：申请详情、通过/驳回、意见保存、状态筛选。
9. 报表中心：按周期生成统计快照、预览、下载可打印 HTML；业务数据可导出 CSV。
10. 审计日志：记录登录、配置修改、事件处置、审批及数据导出。
11. 系统设置：企业名称、邮箱、水印管理入口、日志保留、离线防护和通知配置。
12. 水印管理（数据安全）：打印、屏幕、截屏三类水印策略，新建/编辑/删除/启停，按类型、名称、范围和状态筛选；支持身份动态字段、字体字号、颜色、不透明度、角度、平铺间距与布局、优先级、生效条件及适用应用。打印水印可设置打印机范围与双面水印，屏幕水印可选择显示器，截屏水印可选择截屏方式。支持实时预览与 SVG 预览下载、CSV 配置导出，操作写入审计日志。原“系统设置”中的通用水印入口改为跳转水印管理，升级时原模板自动保留到打印水印策略。
13. 水印追踪（工作空间）：批量或拖拽导入带水印的截图 / 照片；PNG、JPEG、WEBP，每张最多10 MB、一次最多5张，最多保存200张 / 300 MB。以卡片查看缩略图，支持原图放大、旋转、下载和 SHA-256 去重；核验水印文字、编号、用户、部门、终端、IP、时间和关联策略，查看匹配的纳管终端与风险事件；支持可见文字辅助识别（中文 / 英文）、按已知终端与策略提供填充建议，须人工核验保存。提供核验状态和文本筛选、信息 CSV 导出、删除和审计。原图及缩略图保存于服务器磁盘，图片元数据、存储路径和核验信息保存于 PostgreSQL，需登录访问，刷新或重启后保留。

## 原型边界

终端、事件、资产均为明确标注的演示数据，首次运行初始化。策略下发、终端隔离、扫描过程和水印设置属于模拟配置，不含真实终端代理、驱动、系统级数据拦截、文件加密或邮件发送。正则识别测试仅检查手机号和身份证号格式，不进行身份真实性校验；自定义规则的检测实现为关键词匹配。真实产品需接入 Agent、检测引擎、审批执行和身份系统。图片模块实际导入并保存用户上传的图片，可识别清晰的可见文字；不实现暗水印或厂商专有编码解码。识别建议及 EXIF 信息不作为身份真实性证明。

## 数据访问约定

所有业务数据、设置、部门 / 通道字典、图片元数据均从 PostgreSQL 读取并写回。列表使用 SQL WHERE / ORDER BY / LIMIT / OFFSET，统计使用 COUNT / SUM / GROUP BY，详情关联及全局搜索也由数据库完成。前端只持有当前页结果和展示状态，不下载全量数据做检索或统计。`/api/bootstrap` 仅返回账号、设置与下拉选项；`/api/query`、`/api/statistics`、`/api/search`、`/api/detail` 分别提供分页、统计、搜索和详情。CSV 导出沿用当前筛选条件。

图片原图及缩略图保存在 `DLP_FILE_ROOT`（默认 `/var/lib/sentinel-dlp/files`），通过登录鉴权接口读取；路径和哈希由数据库管理，不暴露静态文件目录。备份包含 PostgreSQL `.dump` 与配套 `.files.tar.gz`，恢复时两者必须配对。

## 架构与部署

- `dlpcenter/`：C++ 后端，包括原有用户管理、登录、角色与 Token 接口，以及迁入的业务接口。
- `dlpcenter/services/`：PostgreSQL 参数化查询、SQL 筛选与分页、统计聚合、关联检索、文件存储、业务校验和工作线程池。
- `dlpcenter/tools/image_processor.py`：图片解析 / 缩略图 / OCR 子进程，不提供 HTTP 接口、不访问数据库。
- `dlpcenter/sql/init.sql`：用户、Token、操作日志、JSONB 业务记录、图片文件索引、业务字典及迁移标记。
- `static/`：前端；登录适配 `password_hash`，兼容内网 HTTP 下的 SHA-256 计算。
- `scripts/`：初始化、SQLite 单次迁移、PostgreSQL 备份与演示图导入。

安装、编译、首次初始化、既有 SQLite 升级、备份恢复见 [部署文档](docs/DEPLOYMENT.md)，接口见 [dlpcenter/API.md](dlpcenter/API.md)。

默认部署源码位于 `/opt/sentinel-dlp`，配置为 `/etc/dlpcenter.env`，后端监听 `127.0.0.1:8091`，Nginx 监听 `8090`。数据库名和角色默认为 `dlpcenter`，数据库凭据由环境文件提供。`server.py` 仅为兼容旧启动命令的 C++ 启动器，不再运行 Python HTTP 服务或 SQLite。

```bash
cmake -S dlpcenter -B dlpcenter/build -DCMAKE_BUILD_TYPE=Release
cmake --build dlpcenter/build -j2
# 先按部署文档创建 PostgreSQL 角色、数据库和管理员，再启动服务。
```

登录沿用 dlpcenter 的 `SHA-256 → bcrypt` 与 Bearer Token 约定；浏览器使用 HttpOnly / SameSite Cookie，写请求附带 `X-DLP-Request: 1`。普通账号可查看和导出，配置修改、图片导入 / OCR、审批等写操作要求管理员。业务 JSON 响应沿用 `code: 0/1` 约定，图片与 CSV 成功时直接返回文件内容。

## 验证

```bash
# 测试需要能创建临时数据库的 PostgreSQL 角色；不会使用正式业务库。
sudo -u postgres env DLP_DB_HOST=/var/run/postgresql DLP_DB_USER=postgres \
  DLP_DB_NAME=postgres DLP_BINARY="$PWD/dlpcenter/build/dlpcenter" /usr/bin/python3 verify.py
```

测试覆盖原有用户管理、Cookie / Bearer 认证和权限、业务配置、并发审批、扫描限制、三类水印校验、PNG / JPEG / WEBP、原图完整性、去重、OCR 保留人工信息、备份、重启持久化，以及 SQLite 到 PostgreSQL 的事务迁移与重复执行保护。测试角色需能访问源码目录。已执行 Ubuntu 24.04 / Drogon 1.8.7 / PostgreSQL 16 集成验证。新增验证包括直接 SQL 写入后查询 / 统计 / 搜索即时可见、服务器分页与筛选、设置落表和重启回读、旧 BYTEA 转磁盘、数据库与文件配套恢复。

2026-10-23 已完成正式环境切换：427 条原业务记录、系统设置、历史审计及 12 张水印原图 / 缩略图核对一致；Firefox 验证全部 13 个页面、HTTP 登录、水印预览及 Cookie 保护。验证了 Nginx 下超过 256 KB 的图片导入、去重、OCR、原图下载，以及 PostgreSQL 备份恢复到独立测试库。临时验证图片已清理，旧版源码和 SQLite 备份保留用于回退。

## 参考资料

参考公开产品能力进行信息架构设计，界面与源码为独立实现：

- 深信服办公数据泄密分析：https://www.sangfor.com.cn/sangfor-security/office-dlp
- 亿赛通电子文档安全管理：https://www.esafenet.com/html/2025/11_0810/22.html
- 上邦终端数据防泄漏：https://www.shangbon.com/zdsjfxl/259.html

## 水印追踪演示数据

已导入12张带“[演示]”标题和合成样本标识的图片：屏幕4张、打印4张、截屏3张、来源未知1张；已核验和待核验各6张。包括淡色水印、模拟打印照片、PNG / JPEG / WEBP 格式，以及用户、部门、终端、IP、时间和水印策略关联。可测试分页、筛选、预览、文字识别和终端 / 风险事件下钻。所有业务内容和核验结论均为演示数据。

需要补充或恢复样本时可手动执行（本机需 Pillow 和中文字体 `fonts-noto-cjk`，命令会提示输入控制台密码）：

```bash
python3 scripts/seed_watermark_demo.py --base-url http://127.0.0.1:8090
```

脚本通过现有登录与图片导入接口写入，按演示标识和文件名跳过已有样本，重复运行不会覆盖用户修改。图片生成至 `artifacts/watermark-demo/`。启动服务时不自动创建或恢复这些样本，在控制台删除后保持删除状态。
