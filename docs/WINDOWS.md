# Windows / Linux 编译与运行

dlpcenter 使用同一套 C++17 / Drogon / PostgreSQL 源码。Windows 使用 Windows 10 / Server 2019 或更新版本、Visual Studio 2022 C++ x64 工具链；Linux 使用 GCC 9+ 或 Clang 10+。Linux systemd / Nginx 安装见 [DEPLOYMENT.md](DEPLOYMENT.md)。下列 Windows 步骤使用 PowerShell，从仓库根目录执行。

## Windows 依赖与编译

安装 Visual Studio 2022 的“使用 C++ 的桌面开发”（含 Windows SDK / CMake）、Git、Python 3.10+、PostgreSQL 16+（含命令行工具）。数据库可以部署在本机或远程。Python 依赖可安装到虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r scripts/requirements.txt
$env:PYTHONUTF8 = '1'
$env:DLP_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
```

按 [Drogon 官方 Windows 安装说明](https://github.com/drogonframework/drogon/wiki/ENG-02-Installation) 使用 vcpkg。仓库的 `dlpcenter/vcpkg.json` 固定基线版本，启用 Drogon PostgreSQL / ORM 特性；bcrypt 源码随仓库提供，不依赖 Linux libcrypt 或 Windows BCrypt.dll 的同名库。

```powershell
git clone https://github.com/microsoft/vcpkg.git C:/tools/vcpkg
& C:/tools/vcpkg/bootstrap-vcpkg.bat
$env:VCPKG_ROOT = 'C:/tools/vcpkg'
$baseline = (Get-Content dlpcenter/vcpkg.json | ConvertFrom-Json).'builtin-baseline'
git -C $env:VCPKG_ROOT fetch origin $baseline --depth 1
git -C $env:VCPKG_ROOT checkout --detach $baseline
& "$env:VCPKG_ROOT/bootstrap-vcpkg.bat" -disableMetrics
cmake -S dlpcenter -B dlpcenter/build -A x64 `
  "-DCMAKE_TOOLCHAIN_FILE=$env:VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" `
  -DVCPKG_TARGET_TRIPLET=x64-windows -DBUILD_TESTING=ON
cmake --build dlpcenter/build --config Release --parallel 2
ctest --test-dir dlpcenter/build -C Release --output-on-failure
```

生成 `dlpcenter/build/Release/dlpcenter.exe`。vcpkg 自动拷贝依赖 DLL 至可执行文件目录；发布时须同时携带该目录里的 DLL。若工具未自动拷贝，可将 `dlpcenter/build/vcpkg_installed/x64-windows/bin` 加入 PATH。CMake 将 Windows SDK 目标设为 Windows 10（含 Drogon ORM 所需 htonll），为 MSVC 开启 UTF-8 源码 / 执行字符集，Windows API 使用 UTF-16 路径，支持包含空格和中文的图片处理路径。

## PostgreSQL 初始化与启动

将 PostgreSQL 的 `bin` 目录加入 PATH，以便调用 psql、pg_dump、pg_restore。首次安装可使用数据库管理员创建应用角色与库；角色和库已存在时直接配置现有凭据，不要重建：

```powershell
$env:PATH = 'C:/Program Files/PostgreSQL/16/bin;' + $env:PATH
psql -h 127.0.0.1 -U postgres -d postgres
```

在 psql 中执行（`\password` 会交互询问应用数据库密码）：

```sql
CREATE ROLE dlpcenter LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
\password dlpcenter
CREATE DATABASE dlpcenter OWNER dlpcenter ENCODING 'UTF8' TEMPLATE template0;
\q
```

设置当前进程的连接与路径。密码只通过交互读取，不写入源码；服务账户须具有数据目录写权限。不要将图片目录放进 static 或 Web 根目录。

```powershell
$root = (Get-Location).Path
$env:DLP_DB_HOST = '127.0.0.1'
$env:DLP_DB_PORT = '5432'
$env:DLP_DB_NAME = 'dlpcenter'
$env:DLP_DB_USER = 'dlpcenter'
$secure = Read-Host '应用数据库密码' -AsSecureString
$env:DLP_DB_PASSWORD = [Net.NetworkCredential]::new('', $secure).Password
$env:DLP_CONFIG = Join-Path $root 'dlpcenter/config.json'
$env:DLP_STATIC_ROOT = Join-Path $root 'static'
$env:DLP_IMAGE_HELPER = Join-Path $root 'dlpcenter/tools/image_processor.py'
$env:DLP_FILE_ROOT = Join-Path $root 'data/files'
$env:DLP_HTTP_HOST = '127.0.0.1'
$env:DLP_HTTP_PORT = '8091'
$secure = Read-Host '首次 admin 登录密码' -AsSecureString
$env:DLP_ADMIN_PASSWORD = [Net.NetworkCredential]::new('', $secure).Password
& $env:DLP_PYTHON scripts/init_postgres.py --with-demo
Remove-Item Env:DLP_ADMIN_PASSWORD
& ./dlpcenter/build/Release/dlpcenter.exe
```

另开终端访问 `http://127.0.0.1:8091` 与 `/health`。允许其他主机访问时设置 `DLP_HTTP_HOST=0.0.0.0`，按需要配置 Windows 防火墙与反向代理。`configure_postgres.py` 是 Linux root / systemd 辅助工具，Windows 使用上述 SQL 和环境变量；不执行 Linux service 文件。普通运行不需要 PostgreSQL 管理员或建库权限。`DLP_PYTHON` 可指定虚拟环境解释器，未设置时 Windows 查找 python.exe，Linux 默认 /usr/bin/python3。

已有 PostgreSQL 版本升级时，在停止目标服务并备份后运行 `scripts/init_postgres.py`（不加 --with-demo）；旧 BYTEA 图片还需执行 `scripts/migrate_image_files.py`。不要对已有数据目录执行全量演示初始化或覆盖恢复。

## 图片、OCR、备份和测试

PNG / JPEG / WEBP 导入只需 Pillow。可见文字识别另需安装 [Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html) 并将 tesseract.exe 所在目录加入运行账户的 PATH，同时安装 eng 和 chi_sim 语言数据。未安装时接口会报告 OCR 不可用，图片导入与人工核验仍可使用。C++ 使用 CreateProcessW（不经过命令解释器）运行 Python；超时终止整个子进程树。Linux 使用 posix_spawnp。

```powershell
& $env:DLP_PYTHON scripts/backup_db.py --output-dir ./backups
```

配套 `.dump` 和 `.files.tar.gz` 一起保存。恢复工具及 SQLite 迁移脚本也使用同一套 Python 源码，需配好目标库和 DLP_FILE_ROOT；恢复只接受空库及空文件目录，详见 [DEPLOYMENT.md](DEPLOYMENT.md)。Linux 文件权限使用 0600；Windows 新证据文件和临时文件使用仅所有者 / SYSTEM 可访问的 ACL，备份目录请限制为运行账户和备份管理员可访问，Python 的 chmod 不等同于 Windows ACL。

跨平台单元测试包括既有 Python bcrypt 哈希兼容、随机盐、固定 Asia/Shanghai 时间、IPv6、UTC 转换、无效日期、图片原子写入、中文 / 空格路径子进程和临时文件清理。完整集成测试仅使用随机名临时库，需要有建库权限的独立测试账号，切勿将生产账号提升权限：

```powershell
# 先将 DLP_DB_* 指向可建库的测试账号 / 维护库，使用与服务相同的 Python。
$env:DLP_BINARY = (Resolve-Path dlpcenter/build/Release/dlpcenter.exe).Path
& $env:DLP_PYTHON verify.py
```

CI 使用 `x64-windows-release` triplet 只编译 Release 依赖，并缓存已编译的依赖；本地上述 `x64-windows` 同时支持 Debug / Release。GitHub Actions 的 `Windows and Linux` 工作流在 windows-2022 和 ubuntu-24.04 分别构建，创建独立 PostgreSQL 集群并执行 CTest / 完整接口集成测试；Windows 无 Tesseract 时按能力跳过 OCR，其他图片及用户管理接口仍进行测试。
