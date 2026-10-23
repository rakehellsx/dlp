# 业务 JSON 生成及 PostgreSQL 导入

工具：`scripts/business_data.py`，支持 Windows / Linux 的 Python **3.9+**。JSON生成只用标准库；生成图片需要 Pillow；导入需要 psycopg2。统一安装现有依赖：

```bash
python -m pip install -r scripts/requirements.txt
```

该工具面向批量联调、测试及已有JSON导入，不会启动 Python HTTP 服务，不使用 SQLite，不初始化数据库、不重置账号。先按部署文档初始化 PostgreSQL 及终端 UUID 表。数据库字段清单见 [DATA-DICTIONARY.md](DATA-DICTIONARY.md)。

## 1. 生成 JSON

在代码根目录执行：

```bash
python scripts/business_data.py generate --output artifacts/business.json --prefix IMPORT01 --endpoints 10 --events 30 --assets 20 --approvals 5 --images 3
```

生成结果包括终端、事件、资产、外发审批、6条分类规则、8条防护策略、3条水印策略、1条完成的扫描任务、1条批次报告，以及可选图片；同时带系统设置和部门 / 通道字典。`--images 0` 不生成图片；未指定各数量时终端10、事件30、资产20、审批5、图片0。

每台终端有独立随机UUID，事件 / 资产 / 审批引用同批次终端UUID，名称和IP只作为快照。报告计数是本次生成数据的快照，不是数据库全库计数。资产 path 仅为文件路径描述，不会生成对应业务文档。图片为可见水印的合成测试图片，生成在 JSON 旁边的 `business-files` 目录。

输出 JSON 已存在时拒绝覆盖；同批次重复导入应使用同一 JSON，重新生成会产生新 UUID。`--seed` 控制样本选择，不保证随机 UUID / 当前时间 / 图片编号一致。prefix 为1–24位大写字母、数字、连字符，用于区分批次。

## 2. 配置数据库连接

工具读取 `DLP_DB_HOST`、`DLP_DB_PORT`、`DLP_DB_NAME`、`DLP_DB_USER`、`DLP_DB_PASSWORD`；图片目录读取 `DLP_FILE_ROOT`。默认库名及角色为 dlpcenter；主机127.0.0.1、端口5432。不要把密码写进JSON或代码仓库。

Linux 已部署服务器，加载现有环境：

```bash
cd /opt/sentinel-dlp
set -a
. /etc/dlpcenter.env
set +a
# 请以运行服务的账号执行图片写入，或在导入后校正目录权限。
```

Windows PowerShell：

```powershell
$env:DLP_DB_HOST = '127.0.0.1'
$env:DLP_DB_PORT = '5432'
$env:DLP_DB_NAME = 'dlpcenter'
$env:DLP_DB_USER = 'dlpcenter'
$secret = Read-Host 'PostgreSQL password' -AsSecureString
$env:DLP_DB_PASSWORD = [System.Net.NetworkCredential]::new('', $secret).Password
$env:DLP_FILE_ROOT = "$pwd/data/files"
```

生产使用前按部署文档备份数据库及图片。导入账号必须对相应表、序列有写权限。

## 3. 试运行及正式导入

```bash
# 连接目标库，执行全部校验与SQL后回滚；不写磁盘图片。
python scripts/business_data.py import --input artifacts/business.json --dry-run

# 正式提交；默认遇到已有(kind,id)、终端编号或图片哈希即回滚。
python scripts/business_data.py import --input artifacts/business.json

# 重复执行时跳过同编号记录，不覆盖已有内容。
python scripts/business_data.py import --input artifacts/business.json --on-conflict skip

# 生成后直接写库。
python scripts/business_data.py generate --output artifacts/batch02.json --prefix IMPORT02 --write
```

试运行会建立并回滚真实事务，自增序列值可能产生间隙，但没有业务记录或审计记录被提交。skip 也不会允许相同终端编号换成不同UUID；此类冲突始终失败。所有数据库写入（含导入审计）在单个事务内；任一SQL / 引用 / 校验失败整批回滚。不会覆盖已有业务记录，也不提供清空库操作。

图片校验包括实际格式、体积、尺寸、单帧和SHA-256去重。图片索引及业务元数据写入 PostgreSQL；原图和缩略图写到 `DLP_FILE_ROOT/<hash>/`。数据库和文件系统不构成分布式事务：若写文件后出现数据库错误，可能留下无索引的不可变文件，不会出现已提交的半批业务记录；这些文件可以保留供核对，勿自动删除可能被并发请求使用的哈希目录。

Linux 图片文件权限跟随导入账号；建议以 `sentinel-dlp` 服务账号运行。若由 root 导入，提交后执行 `chown -R sentinel-dlp:sentinel-dlp "$DLP_FILE_ROOT"`，确保服务可以读取0600文件。不要把目录放入 static。

## 4. 系统设置与字典

默认只导入 records，**不会使用生成JSON覆盖当前企业名和通知配置**。

```bash
# 显式覆盖全部7个系统设置字段。
python scripts/business_data.py import --input artifacts/business.json --on-conflict skip --apply-settings

# 仅补充不存在的部门/通道字典，不改既有字典。
python scripts/business_data.py import --input artifacts/business.json --on-conflict skip --apply-catalogs
```

工具不生成用户密码、登录Token、历史审计或迁移状态。账号请通过“用户管理”或已有用户管理接口创建；会话、迁移标记和审计由相应流程维护。每次成功导入会另写一条真实的“导入业务JSON”审计，记录计数，不记录密码。

## 5. 图片解析及水印字段

```bash
# 需要部署Tesseract和chi_sim / eng语言包；图片识别失败整批回滚。
python scripts/business_data.py import --input artifacts/business.json --ocr
```

启用 --ocr 会解析可见文字、提取编码 / IPv4 / 时间，再按数据库中唯一匹配的终端补充使用人、部门、终端UUID；匹配策略ID或名称时补充水印类型和策略ID。保存 `ocrText`、`ocrState`、`ocrTime`、`ocrSuggestions`，不会把候选值直接写入已核验字段 / 终端外键，也不会自动标记 reviewed。之后在水印追踪中核验并保存。未启用 --ocr 时依旧解析图片格式、EXIF、尺寸、哈希、缩略图，ocrState=not_run。

HTTP图片导入同样先保存图片及传入的metadata；不会自动OCR。控制台“识别文字”调用 `/api/watermark-images/ocr` 才启动识别。当前支持的是**可见文字OCR**，不包含隐形 / 暗水印解码、任意旋转透视校正、可信源签名验证，不能保证对模糊照片和复杂背景正确识别。

## 6. JSON 格式及自定义数据

```json
{
  "schemaVersion": 1,
  "generatedAt": "2026-10-23 16:00:00",
  "records": [
    {
      "kind": "watermarkImages",
      "sourceFile": "business-files/photo.png",
      "data": {
        "id": "WIMG-012345ABCDEF",
        "title": "待核验照片",
        "type": "unknown",
        "status": "pending",
        "endpointUid": "",
        "note": "来源待确认"
      }
    }
  ]
}
```

`records[].kind` 支持 endpoints、events、assets、policies、rules、approvals、scans、reports、watermarks、watermarkImages。各类必填及类型可直接参考生成结果；完整字段解释见字段字典。可删除不需要的记录，空 records 也可用于仅导入 settings / catalogs。

终端 data 使用接口字段名（如 id、user、ip、version、lastSeen、endpointUid），工具映射到独立表；额外键写入 endpoints.extra。其余业务写入 dlp_records。会先插入终端、再插入普通业务、最后插入图片，所以数组顺序不影响终端关联。未知UUID、不一致的既有终端UUID、缺失必填字段、错误类型、重复编号、无效水印参数会拒绝。

图片 `sourceFile` 是JSON所在目录内的相对路径，不能越出目录，也不能指向外部符号链接。JSON中不携带Base64；字段解析后自动补充格式、大小、哈希、原文件名、导入人、时间和OCR状态。已有实际照片可以放进同目录的子目录并调整sourceFile。可在图片data中填写已确认的metadata及真实 endpointUid / policyId，导入会检查关联存在性。

系统设置置于顶层 settings；字典置于顶层 catalogs，格式为 `{category,key,label,position,config}` 数组。无需包含 dlp_records.seq、endpoints.seq 或 SQL created_at，它们由数据库维护。
