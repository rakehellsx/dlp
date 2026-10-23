# dlpcenter

基于用户提供的 `dlpcenter.zip` 扩展，统一承载 Sentinel DLP 的服务端接口。

- C++17 / Drogon：登录、用户管理、业务接口、图片访问和静态前端。
- PostgreSQL：`users`、`user_tokens`、`operation_logs` 沿用原项目结构；`dlp_records` / `dlp_settings` 使用 JSONB；`dlp_watermark_images` 保存图片路径、哈希和元数据，原图及缩略图保存于私有磁盘目录。
- 原用户管理接口路径、SHA-256 + bcrypt 密码方案、Bearer Token、HTTP 200 + `code` 响应约定保留。
- 浏览器登录额外设置 HttpOnly / SameSite Cookie，图片访问无需将 Token 写入 URL；Cookie 写操作需要 `X-DLP-Request: 1`。
- C++ 控制器直接执行业务逻辑及 PostgreSQL 事务。Python 仅用作 Pillow / Tesseract 图片处理子进程、初始化、演示数据生成和一次性 SQLite 迁移，不运行 HTTP 服务。

完整安装、构建、迁移及回退见 [部署文档](../docs/DEPLOYMENT.md)，业务接口见 [API.md](API.md)。

构建：

```bash
cmake -S dlpcenter -B dlpcenter/build -DCMAKE_BUILD_TYPE=Release
cmake --build dlpcenter/build -j2
```

启动前配置 PostgreSQL 环境变量并执行 `python3 scripts/init_postgres.py --with-demo`，然后从仓库根目录运行 `./dlpcenter/build/dlpcenter`。账号初始化不包含固定密码，使用 `DLP_ADMIN_PASSWORD` 设置首次密码。

适配说明：修正原项目在 Drogon 1.8.7 上的异常类型、强类型 SQL 回调、缺失头文件与定时器类型；使用系统 libxcrypt 的 bcrypt 实现兼容 `BCrypt` API；创建用户使用 PostgreSQL `RETURNING id`；Token 使用 OpenSSL 随机数。管理员角色、用户禁用和 Token 失效检查继续共用原过滤器。

列表、检索、统计与关联详情见 `services/Queries.cc`，均通过 PostgreSQL SQL 执行。`bootstrap` 不再返回全量业务记录；前端通过分页接口获取当前页。图片迁移使用 `scripts/migrate_image_files.py`，设置及水印配置继续事务写入数据库。
