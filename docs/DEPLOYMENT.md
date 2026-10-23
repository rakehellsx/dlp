# 部署与运维

服务端使用用户提供的 dlpcenter（C++17 / Drogon），数据库统一为 PostgreSQL；原有用户接口保留，原 Python 业务接口已迁入 C++。以下命令适用于 Ubuntu 24.04，以 root 执行。应用以 `sentinel-dlp` 用户运行，浏览器入口 `http://<服务器IP>:8090`，后端仅监听 `127.0.0.1:8091`。

## 1. 安装依赖和编译

```bash
apt-get update
apt-get install -y git build-essential cmake pkg-config nginx curl \
  postgresql postgresql-client postgresql-contrib \
  libdrogon-dev libjsoncpp-dev libpq-dev libssl-dev libcrypt-dev \
  uuid-dev zlib1g-dev libbrotli-dev libc-ares-dev libhiredis-dev \
  libsqlite3-dev libmariadb-dev libyaml-cpp-dev \
  python3 python3-psycopg2 python3-bcrypt python3-pil \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim fonts-noto-cjk
systemctl enable --now postgresql

git clone https://github.com/rakehellsx/dlp.git /opt/sentinel-dlp
cd /opt/sentinel-dlp
cmake -S dlpcenter -B dlpcenter/build -DCMAKE_BUILD_TYPE=Release
cmake --build dlpcenter/build -j2
```

验证环境为 Drogon 1.8.7、PostgreSQL 16。部分 Drogon 系统包的 CMake 配置会引用其已编译的 SQLite / MariaDB 等驱动，故安装相应开发库；本应用的业务、账号、审计及图片元数据使用 PostgreSQL，图片文件保存在磁盘，没有 SQLite 运行服务。Pillow / Tesseract 通过受限时长的本地子进程处理图片，不提供第二套 HTTP 后端。前端无需构建和 CDN。

## 2. 运行用户与数据库配置

```bash
id sentinel-dlp >/dev/null 2>&1 || useradd --system \
  --home-dir /var/lib/sentinel-dlp --shell /usr/sbin/nologin sentinel-dlp
install -d -o sentinel-dlp -g sentinel-dlp -m 0750 /var/lib/sentinel-dlp
install -d -o sentinel-dlp -g sentinel-dlp -m 0750 /var/lib/sentinel-dlp/files
chmod -R a+rX /opt/sentinel-dlp
cd /opt/sentinel-dlp
python3 scripts/configure_postgres.py
```

脚本通过本机 PostgreSQL 的 `postgres` 系统账号创建独立 `dlpcenter` 角色及同名数据库，自动生成随机数据库密码，写入权限 0600 的 `/etc/dlpcenter.env`。不会向终端输出密码；角色无超级用户、建库和建角色权限。已有角色、数据库或环境文件会拒绝覆盖。如使用现有 PostgreSQL，参照 `deploy/dlpcenter.env.example` 手工设置连接信息，由对应库属主执行初始化。远程数据库应按网络策略配置 TLS 与访问权限。

环境文件包含 `DLP_DB_HOST/PORT/NAME/USER/PASSWORD`，以及 `DLP_CONFIG`、`DLP_STATIC_ROOT`、`DLP_IMAGE_HELPER`、`DLP_FILE_ROOT` 和监听地址；systemd 负责读取。更换源代码目录时同步修改这些绝对路径。服务配置使用 `ProtectHome=read-only`，兼容 libpq 对运行账号主目录中证书路径的检查；源码保持只读，临时文件使用 systemd 私有 `/tmp`。数据库密码与控制台登录密码相互独立。

## 3. 新安装初始化

**已有 SQLite 原型请跳过本节，按第 8 节迁移。不要先写入默认演示数据。**

```bash
cd /opt/sentinel-dlp
set -a
. /etc/dlpcenter.env
set +a
read -r -s -p '设置 admin 初始密码：' DLP_ADMIN_PASSWORD
export DLP_ADMIN_PASSWORD
python3 scripts/init_postgres.py --with-demo
unset DLP_ADMIN_PASSWORD
```

管理员名为 `admin`。密码按 dlpcenter 的约定以 bcrypt(SHA-256(password)) 存储，不设固定默认密码。初始化为事务操作，首次必须设置密码，已有账号不会重置。`--with-demo` 只在空业务库中导入合成演示数据，迁移标记确保删除的样本不会在重启或再次初始化后生成。

## 4. 启动和访问

```bash
cd /opt/sentinel-dlp
install -m 0644 deploy/sentinel-dlp.service /etc/systemd/system/sentinel-dlp.service
install -m 0644 deploy/sentinel-dlp.conf /etc/nginx/conf.d/sentinel-dlp.conf
nginx -t
systemctl daemon-reload
systemctl enable --now sentinel-dlp nginx
systemctl reload nginx
systemctl is-active sentinel-dlp nginx postgresql
curl --fail http://127.0.0.1:8090/health
```

健康接口应返回 `code: 0`、`status: ok`、`backend: dlpcenter/Drogon`、`database: PostgreSQL`。浏览器打开 `http://<服务器IP>:8090`，使用原有账号或初始化的 `admin` 登录。

水印管理位于“数据安全 → 水印管理”；水印追踪位于“工作空间 → 水印追踪”，直达 `/#watermark-images`。普通账号可以查看、导出和规则检测，业务写操作要求管理员。登录、用户管理和业务 API 都沿用 dlpcenter 的 JSON `code` 协议；业务失败也可能是 HTTP 200，调用方须检查 `code`。

Nginx 独立监听 8090，不修改其他站点；普通请求体最大 256 KB，图片导入单独允许 15 MB，以容纳每张最多 10 MB 的 Base64 图片。原图和缩略图保存在 `DLP_FILE_ROOT` 磁盘目录，路径、哈希和核验信息保存于 PostgreSQL，读取受登录保护。仅向需要使用的网段放行 8090；公网或跨不可信网络访问应配置 HTTPS，密码摘要仍属于凭据。

## 5. 可选：导入水印追踪演示图

```bash
python3 scripts/seed_watermark_demo.py --base-url http://127.0.0.1:8090
```

脚本提示控制台密码，通过登录及图片接口生成并上传 12 张合成样本：屏幕 4、打印 4、截屏 3、未知 1；已核验和待核验各 6。包含三种图片格式、淡色水印和模拟打印照片，以及演示终端 / 策略关联。重复运行按样本标识跳过已有图片，不覆盖人工修改，启动时不会自动恢复已删除图片。生成文件在被 Git 忽略的 `artifacts/watermark-demo/`。

## 6. 验证与日志

```bash
cd /opt/sentinel-dlp
runuser -u postgres -- env DLP_DB_HOST=/var/run/postgresql DLP_DB_USER=postgres \
  DLP_DB_NAME=postgres DLP_BINARY="$PWD/dlpcenter/build/dlpcenter" /usr/bin/python3 verify.py
journalctl -u sentinel-dlp -n 100 --no-pager
tesseract --list-langs
```

测试在随机端口启动新进程，创建及清理 `dlp_verify_*` 临时数据库，不修改正式业务库。需使用有建库权限的测试角色，应用自身角色没有该权限。覆盖账号管理、认证权限、SQL 检索与分页、数据库直接变更后的统计 / 搜索、设置落表、业务操作与并发、磁盘图片 / OCR、数据库和文件配套恢复到独立临时库、重启及迁移一致性。数据库日志见 PostgreSQL 服务；识别依赖应包含 `eng` 和 `chi_sim`。

## 7. 数据库与文件配套备份、恢复

可在线备份。设置、账号、审计和业务数据位于 PostgreSQL，图片原图 / 缩略图在磁盘，不可只保存其中一项：

```bash
cd /opt/sentinel-dlp
set -a
. /etc/dlpcenter.env
set +a
python3 scripts/backup_db.py --output-dir /var/backups/sentinel-dlp
```

每次生成配对的 `dlpcenter-时间.dump` 和 `dlpcenter-时间.files.tar.gz`，均为 0600 权限。数据库先备份，文件为按哈希寻址的不可变内容，之后打包磁盘文件；临时写入文件会被排除。删除图片会事务删除索引及业务元数据，原图接口立即不可用；文件保留以支持已有备份的一致性。当前版本不自动清理无引用文件。

恢复工具只接受空数据库与空文件目录，并检查归档路径、文件类型及原图哈希，拒绝覆盖现有业务。先停止目标服务，创建一个独立恢复库与目录：

```bash
systemctl stop sentinel-dlp
cd /opt/sentinel-dlp
python3 scripts/configure_postgres.py --database dlpcenter_restore --user dlpcenter_restore \
  --env-file /etc/dlpcenter-restore.env
printf '%s\n' 'DLP_FILE_ROOT="/var/lib/sentinel-dlp-restored/files"' >> /etc/dlpcenter-restore.env
set -a
. /etc/dlpcenter-restore.env
set +a
python3 scripts/restore_backup.py --dump /path/to/dlpcenter-backup.dump
chown -R sentinel-dlp:sentinel-dlp /var/lib/sentinel-dlp-restored
# 确认恢复内容后，让服务使用恢复库；旧环境文件及旧库保留。
cp -a /etc/dlpcenter.env /etc/dlpcenter-before-restore.env
install -m 0600 /etc/dlpcenter-restore.env /etc/dlpcenter.env
systemctl start sentinel-dlp
curl --fail http://127.0.0.1:8090/health
```

将备份复制到安全位置，定期在独立数据库做恢复演练。配套文件归档必须与 `.dump` 同目录、同文件名前缀。SQL 结构或文件缺失时不要启动目标服务，保留原库及原文件定位问题。

## 8. 从旧 Python / SQLite 原型迁移

新后端不再读取 `DLP_DB` 或旧 SQLite 文件。迁移工具只读原库，事务写入 PostgreSQL，逐条比较 JSON、原图、缩略图和哈希；迁移用户、设置、审计及迁移标记，不迁移旧会话。原有 PostgreSQL 用户接口、账号及密码保持兼容；同名 PostgreSQL 账号优先保留。

1. 按第 1、2 节在独立目录构建新后端、创建空 PostgreSQL 数据库，先运行第 6 节测试。保留旧源码、旧 systemd 配置、旧环境文件和 SQLite 备份，便于回退。
2. 切换前停止旧服务，使用 SQLite backup API 创建一致性备份：

```bash
systemctl stop sentinel-dlp
install -d -m 0700 /var/backups/sentinel-dlp/sqlite-upgrade
python3 - <<'PY'
import os
import sqlite3
path='/var/backups/sentinel-dlp/sqlite-upgrade/sentinel-final.db'
if os.path.exists(path):raise SystemExit('备份已存在，请换一个路径')
with sqlite3.connect('/var/lib/sentinel-dlp/sentinel.db') as source:
    with sqlite3.connect(path) as target:source.backup(target)
os.chmod(path,0o600)
PY
```

3. 在新代码目录加载新数据库配置并迁移。旧 SQLite 密码使用不同摘要算法，需输入原密码验证后转换为 SHA-256 + bcrypt；没有同名 PostgreSQL 账号时才转换，不会设置新默认密码：

```bash
set -a
. /etc/dlpcenter.env
set +a
python3 scripts/migrate_sqlite_to_postgres.py \
  --sqlite /var/backups/sentinel-dlp/sqlite-upgrade/sentinel-final.db
python3 scripts/migrate_image_files.py
chown -R sentinel-dlp:sentinel-dlp "$DLP_FILE_ROOT"
```

迁移完成会显示业务记录和图片数量。目标业务库非空会取消；已完成相同迁移则跳过，避免覆盖 PostgreSQL 后续修改。首次迁移失败会回滚，先修复问题，不要删除原 SQLite。旧系统若有多个账号，脚本逐个询问旧密码。

4. 将新源码和已编译二进制部署到 `/opt/sentinel-dlp`，确认 `/etc/dlpcenter.env` 路径正确，按第 4 节安装新服务并启动。重新登录，检查水印追踪图片、策略和审计。
5. 保留旧目录、SQLite 和旧服务配置作为只读回退材料。若切换失败，停止新服务，恢复旧源码及旧 systemd 配置，使用切换前 SQLite 备份启动旧服务。切换后 PostgreSQL 新写入的数据不会自动反向同步到 SQLite，回退前须单独保存。

## 8.1 从上一版 PostgreSQL BYTEA 图片存储升级

先按旧版本脚本备份 PostgreSQL（其中包含旧 BYTEA），保留旧源码、二进制与环境文件。新代码独立编译并测试通过后，停止服务，加载正式环境文件，再执行：

```bash
systemctl stop sentinel-dlp
set -a
. /etc/dlpcenter.env
set +a
# 旧环境文件没有此项时补上；目标目录位于私有数据目录，不能放入 static。
export DLP_FILE_ROOT="${DLP_FILE_ROOT:-/var/lib/sentinel-dlp/files}"
python3 scripts/init_postgres.py
python3 scripts/migrate_image_files.py
chown -R sentinel-dlp:sentinel-dlp "$DLP_FILE_ROOT"
systemctl start sentinel-dlp
```

迁移会先以原子文件写入并核对所有原图 SHA-256 及缩略图字节，然后在数据库事务中写入路径、大小并将旧 BYTEA 字段置空。重复运行只验证既有文件，不重新生成业务数据。迁移前的 PostgreSQL 备份用于旧版回退；迁移后请生成第 7 节的配套备份。运行接口只读取磁盘图片与 PostgreSQL 元数据，不回退到旧 BYTEA。

## 9. 后续更新

```bash
cd /opt/sentinel-dlp
# 先按第 7 节备份，并记录回退版本。
git rev-parse HEAD
git pull --ff-only
cmake -S dlpcenter -B dlpcenter/build -DCMAKE_BUILD_TYPE=Release
cmake --build dlpcenter/build -j2
# 按第 6 节运行集成测试。
set -a
. /etc/dlpcenter.env
set +a
python3 scripts/init_postgres.py
install -m 0644 deploy/sentinel-dlp.service /etc/systemd/system/sentinel-dlp.service
nginx -t
systemctl daemon-reload
systemctl restart sentinel-dlp
curl --fail http://127.0.0.1:8090/health
```

保留环境文件和 PostgreSQL 数据；日常更新不再次导入 SQLite，也不自动重建演示图。无 Git 的部署目录先整体备份，再替换源代码及二进制。`init_postgres.py` 创建缺少的表，不重置已有用户或业务数据；未来破坏性结构变更应提供独立迁移脚本。

## 10. 排障与原型边界

- 编译找不到 UUID / Brotli / c-ares / Hiredis 等：安装第 1 节完整开发依赖，再重新运行 CMake。
- 数据库连接失败：检查 PostgreSQL、`/etc/dlpcenter.env`、库属主与 `pg_hba.conf`；日志不得公开数据库密码。
- 首次初始化提示 `DLP_ADMIN_PASSWORD`：通过交互输入设置；更改变量不会重置已有账号。
- 浏览器旧会话失效：迁移后重新登录；强制刷新以载入新的登录和响应适配代码。
- 图片返回 413：检查 Nginx 图片导入 location 的 15 MB 限制并重载。
- OCR 不可用：检查 Pillow、Tesseract 和中英文语言包；文字识别后需人工核验。
- 502：查看 `systemctl status sentinel-dlp` 与日志，确认 C++ 二进制已构建、8091 正常监听。
- 系统提供产品原型和演示数据；策略下发、终端隔离、扫描和水印配置为模拟操作，没有真实 Agent、驱动或暗水印解码器。
