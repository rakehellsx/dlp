# 部署与运维

适用于 Ubuntu 24.04 / Debian，使用 Python 3.10+、SQLite、Nginx 和 systemd。以下服务器安装命令以 root 执行；应用本身使用 `sentinel-dlp` 用户运行。浏览器入口为 `http://<服务器IP>:8090`，Python 后端仅监听 `127.0.0.1:8091`。

## 1. 安装依赖并取得源码

```bash
apt-get update
apt-get install -y git python3 python3-pil nginx curl \
  tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim fonts-noto-cjk

git clone https://github.com/rakehellsx/dlp.git /opt/sentinel-dlp
cd /opt/sentinel-dlp
python3 verify.py
```

项目无需 Node.js、前端构建或 CDN。Pillow 用于图片校验、缩略图和演示图生成；Tesseract 用于中英文可见文字识别。仓库只包含源码与合成演示数据生成脚本，数据库及用户上传图片不在 Git 中。

## 2. 创建运行用户和数据目录

```bash
id sentinel-dlp >/dev/null 2>&1 || useradd --system \
  --home-dir /var/lib/sentinel-dlp --shell /usr/sbin/nologin sentinel-dlp
install -d -o sentinel-dlp -g sentinel-dlp -m 0750 /var/lib/sentinel-dlp
chmod -R a+rX /opt/sentinel-dlp
```

源代码保持 root 所有。数据库固定在 `/var/lib/sentinel-dlp/sentinel.db`，不要放入源码目录，便于升级时保留数据。上传原图与缩略图也存储在这个 SQLite 数据库中。

## 3. 设置首次管理员密码

新数据库首次启动必须提供 `DLP_ADMIN_PASSWORD`。下面交互式输入密码并创建仅 root 可读的环境文件，不回显密码；文件已存在时不会覆盖。

```bash
python3 - <<'PY'
import getpass
import json
import os
from pathlib import Path

path = Path('/etc/sentinel-dlp.env')
if path.exists():
    raise SystemExit('环境文件已存在，请保留现有配置')
password = getpass.getpass('设置 admin 初始密码：')
confirm = getpass.getpass('再次输入密码：')
if not password or password != confirm or '\n' in password or '\r' in password:
    raise SystemExit('密码为空、两次不一致或包含换行，请重新设置')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as output:
    output.write('DLP_ADMIN_PASSWORD=' + json.dumps(password, ensure_ascii=False) + '\n')
print('初始密码配置已保存')
PY
```

账号为 `admin`。初始密码只在创建管理员时使用；已有数据库启动时不会重置密码，修改环境文件也不会修改已有账号密码。现有安装可继续使用已有数据库与登录密码。

## 4. 安装并启动服务

```bash
cd /opt/sentinel-dlp
install -m 0644 deploy/sentinel-dlp.service /etc/systemd/system/sentinel-dlp.service
install -m 0644 deploy/sentinel-dlp.conf /etc/nginx/conf.d/sentinel-dlp.conf
nginx -t
systemctl daemon-reload
systemctl enable --now sentinel-dlp
systemctl enable --now nginx
systemctl reload nginx
```

Nginx 配置独立监听 8090，不修改默认站点。普通请求最大 256 KB，图片导入接口单独允许 15 MB 请求体，以容纳最大 10 MB 图片的 Base64 数据。原图 PNG / JPEG / WEBP，单次批量上传最多 5 张，每张通过独立请求上传；最多保存 200 张 / 300 MB。

如果服务器有防火墙或云安全组，将 TCP 8090 对使用者所在网段放行。需要域名、HTTPS 或公网访问时，应在现有反向代理上配置 TLS 与访问范围。

## 5. 检查并访问

```bash
systemctl is-active sentinel-dlp nginx
curl --fail http://127.0.0.1:8091/health
curl --fail http://127.0.0.1:8090/health
tesseract --list-langs
journalctl -u sentinel-dlp -n 50 --no-pager
```

`/health` 返回 `status: ok`。浏览器打开 `http://<服务器IP>:8090`，使用 `admin` 和第 3 步设置的密码登录。

水印追踪在“工作空间 → 水印追踪”，直达路径 `/#watermark-images`。水印管理在“数据安全 → 水印管理”。

## 6. 导入 12 组水印演示数据

在已安装 Pillow 和中文字体的机器上执行，脚本会提示输入控制台密码：

```bash
cd /opt/sentinel-dlp
python3 scripts/seed_watermark_demo.py --base-url http://127.0.0.1:8090
```

也可以在自己的工作机上指定 `--base-url http://<服务器IP>:8090`。脚本生成并上传明确标注为演示的合成图片：屏幕 4 张、打印 4 张、截屏 3 张、来源未知 1 张；待核验和已核验各 6 张。包含模拟打印照片、淡色水印、三种图片格式和现有演示终端 / 策略关联。

脚本通过已有 API 登录和导入，重复执行跳过已有样本；启动服务时不会自动补回删除的样本。生成的图片位于 `artifacts/watermark-demo/`，该目录被 Git 忽略。演示图及核验状态均为合成测试内容，文字识别建议仍需人工核验。

## 7. 备份数据库

应用可保持运行，使用 SQLite backup API 同时保存原图、缩略图、账号和业务记录：

```bash
cd /opt/sentinel-dlp
python3 scripts/backup_db.py \
  --database /var/lib/sentinel-dlp/sentinel.db \
  --output-dir /var/backups/sentinel-dlp
```

命令输出备份路径，备份文件权限为 0600。备份包含图片、账号密码摘要和会话，请按业务数据管理。不要只复制运行中的 `.db` 文件，WAL 中可能仍有未合并数据。

## 8. 更新代码

```bash
cd /opt/sentinel-dlp
python3 scripts/backup_db.py --database /var/lib/sentinel-dlp/sentinel.db \
  --output-dir /var/backups/sentinel-dlp
git rev-parse HEAD
git fetch origin
git merge --ff-only origin/main
python3 verify.py
install -m 0644 deploy/sentinel-dlp.service /etc/systemd/system/sentinel-dlp.service
install -m 0644 deploy/sentinel-dlp.conf /etc/nginx/conf.d/sentinel-dlp.conf
nginx -t
systemctl daemon-reload
systemctl restart sentinel-dlp
systemctl reload nginx
curl --fail http://127.0.0.1:8090/health
```

保留更新前的提交号和数据库备份路径。数据库升级在启动时执行，旧水印模板会迁移，已删除的配置不会自动重新生成。升级保留 `/var/lib/sentinel-dlp` 和 `/etc/sentinel-dlp.env`。

如果现有 `/opt/sentinel-dlp` 是直接复制的源码而非 Git 仓库，先备份该目录与数据库，再将旧目录改名保留，随后按第 1 步克隆到 `/opt/sentinel-dlp`，跳过初始化密码步骤并安装服务配置。已有数据库位于独立数据目录，继续使用原登录信息。

## 9. 恢复数据库或回退

先停止应用，避免恢复过程中继续写入。将示例备份路径替换为真实文件路径：

```bash
systemctl stop sentinel-dlp
export DLP_RESTORE_BACKUP=/var/backups/sentinel-dlp/sentinel-YYYYMMDD-HHMMSS-ffffff.db
python3 - <<'PY'
import os
import sqlite3
from pathlib import Path

backup = Path(os.environ['DLP_RESTORE_BACKUP']).resolve(strict=True)
with sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True) as source:
    if source.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
        raise SystemExit('备份校验失败')
    with sqlite3.connect('/var/lib/sentinel-dlp/sentinel.db') as target:
        source.backup(target)
print('数据库已恢复')
PY
chown sentinel-dlp:sentinel-dlp /var/lib/sentinel-dlp/sentinel.db*
chmod 0640 /var/lib/sentinel-dlp/sentinel.db*
systemctl start sentinel-dlp
curl --fail http://127.0.0.1:8090/health
```

若需要回退源码，可在停止应用后执行 `git switch --detach <更新前提交号>`，然后安装该版本的 systemd / Nginx 配置、执行 `nginx -t` 与 `systemctl daemon-reload`，再启动应用。涉及数据库结构变化时配合恢复对应版本的备份。

## 10. 常见问题

- 启动提示缺少 `DLP_ADMIN_PASSWORD`：新数据库未设置初始密码，检查 `/etc/sentinel-dlp.env` 和服务配置。
- 登录密码没有随环境变量改变：已有管理员不会被自动重置，请使用原账号密码。
- 图片导入返回 413：确认使用仓库的 Nginx 配置并成功重载，图片接口应允许 15 MB 请求体。
- 文字识别按钮不可用或识别失败：检查 `python3 -c 'from PIL import Image'`、`command -v tesseract`、`tesseract --list-langs`，应有 `chi_sim` 与 `eng`。
- 示例图中文字显示方框：安装 `fonts-noto-cjk` 后重新生成样本。
- 数据库无法写入：检查 `/var/lib/sentinel-dlp` 属主为 `sentinel-dlp`，且服务的 `DLP_DB` 路径正确。
- 502：查看 `systemctl status sentinel-dlp` 与 `journalctl -u sentinel-dlp -n 100 --no-pager`，确认 8091 监听正常。
- 终端隔离、策略下发或暗水印解码未执行：这些属于原型边界；当前系统没有真实终端 Agent，也没有厂商暗水印解码器。
