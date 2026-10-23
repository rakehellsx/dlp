# 接口文档（API Reference）

dlpcenter · 基于 Drogon + PostgreSQL 的用户认证与管理系统

## 通用约定

### 基础信息

| 项 | 值 |
|---|---|
| Base URL | `http://<host>:8090`（Nginx）或 `http://127.0.0.1:8091`（后端） |
| 请求/响应格式 | JSON（`Content-Type: application/json`） |
| 编码 | UTF-8 |

### 响应格式

**所有接口一律返回 HTTP 200**，通过 body 的 `code` 字段判断结果：

```json
// 成功
{"code": 0, ...业务数据}

// 失败
{"code": 1, "error": "失败原因描述"}
```

### 响应头

| 头 | 说明 |
|---|---|
| `X-Err-Code` | `0`=成功，`1`=失败（所有响应都带，供基础设施/网关直接判断，无需解析 body） |
| `X-Err-Msg` | 失败原因描述（仅失败时带；UTF-8 中文，个别严格代理可能拒绝非 ASCII 头，以 body 为准） |

### 鉴权方式

登录成功后获得 Token，受保护接口通过请求头携带：

```
Authorization: Bearer <token>
```

### 通用错误码（code=1 时 error 字段取值）

| error | 触发场景 |
|---|---|
| 未登录或Token已过期 | 受保护接口未带有效 Bearer 或登录 Cookie |
| 未登录或Token已过期 | Token 无效、过期，或所属用户已被禁用 |
| 需要管理员权限 | 普通用户调用管理员接口 |
| username/password_hash required | 登录/创建缺少必填字段 |
| password_hash 必须是 64 位十六进制 SHA-256 值 | 哈希格式不对 |
| internal error | 数据库异常 |

### 密码哈希约定

客户端在本地计算 `SHA-256(原始密码)`，提交 64 位十六进制小写哈希（字段 `password_hash`），网络上不传输明文密码。服务端对该哈希做 `bcrypt(cost=10)` 二次加盐存储。

前端 JS 参考：

```js
async function sha256Hex(text) {
    const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}
```

---

## 1. 认证接口

### 1.1 登录

- **POST** `/api/login`
- 权限：公开

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 用户名（1-64字符） |
| password_hash | string | 是 | 客户端本地计算的 SHA-256 哈希，64 位十六进制 |

请求示例：

```json
{
  "username": "admin",
  "password_hash": "240be518fabd2724ddb6f04eeb1da5967448d7e831c08c8fa822809f74c720a9"
}
```

成功响应：

```json
{
  "code": 0,
  "token": "a1b2c3d4e5f6...",
  "expire_in": 86400
}
```

| 字段 | 说明 |
|---|---|
| token | 访问令牌，24 小时有效 |
| expire_in | 有效期（秒） |

失败响应：

```json
{"code": 1, "error": "用户名或密码错误"}
```
> 用户不存在与密码错误返回相同提示，防止用户名枚举。被禁用的用户登录同样返回此提示。

---

### 1.2 登出

- **POST** `/api/logout`
- 权限：登录

请求头：`Authorization: Bearer <token>`

请求体：无

成功响应：

```json
{"code": 0, "msg": "已退出登录"}
```

效果：当前 Token 立即从数据库删除并失效。

---

## 2. 个人信息接口（登录权限）

### 2.1 当前用户信息

- **GET** `/api/user/profile`

成功响应：

```json
{
  "code": 0,
  "id": 1,
  "username": "admin",
  "role": "admin",
  "disabled": false,
  "created_at": "2026-10-23 09:00:00"
}
```

| 字段 | 说明 |
|---|---|
| role | `admin` / `user` |
| disabled | 是否被禁用 |

---

### 2.2 当前账号有效 Token 列表

- **GET** `/api/user/tokens`

成功响应：

```json
{
  "code": 0,
  "count": 2,
  "tokens": [
    {
      "token": "a1b2c3d4...",
      "expire_at": "2026-10-24 09:00:00",
      "created_at": "2026-10-23 08:00:00"
    }
  ]
}
```

---

### 2.3 修改密码

- **POST** `/api/user/change_password`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| old_password_hash | string | 是 | 旧密码的 SHA-256 哈希 |
| new_password_hash | string | 是 | 新密码的 SHA-256 哈希 |

成功响应：

```json
{"code": 0, "msg": "密码修改成功，请重新登录"}
```

失败响应示例：

```json
{"code": 1, "error": "旧密码错误"}
{"code": 1, "error": "新密码不能与旧密码相同"}
```

> 改密后已有 Token 仍然有效（提示语建议前端引导重新登录）。

---

## 3. 用户管理接口（管理员权限）

> 以下接口要求调用者 role=`admin`，且不能对自己执行删除/禁用操作。

### 3.1 新增用户

- **POST** `/api/user/create`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 用户名（1-64字符） |
| password_hash | string | 是 | SHA-256 哈希，64 位十六进制 |
| role | string | 否 | `user`（默认）或 `admin` |

请求示例：

```json
{
  "username": "testuser",
  "password_hash": "e606e38b0d8c19b24cf0ee3808183162...",
  "role": "user"
}
```

成功响应：

```json
{"code": 0, "id": 3, "msg": "用户创建成功"}
```

失败响应：

```json
{"code": 1, "error": "用户名已存在"}
{"code": 1, "error": "role 必须是 user 或 admin"}
```

---

### 3.2 删除用户

- **POST** `/api/user/delete`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 要删除的用户名 |

成功响应：

```json
{"code": 0, "msg": "用户已删除"}
```

失败响应：

```json
{"code": 1, "error": "用户不存在"}
{"code": 1, "error": "不能删除当前登录账号"}
```

> 删除后该用户的所有 Token 级联删除，立即全部失效。

---

### 3.3 禁用 / 启用用户

- **POST** `/api/user/disable`

请求体：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| username | string | 是 | 目标用户名 |
| disabled | bool | 是 | `true`=禁用，`false`=启用 |

成功响应（禁用）：

```json
{"code": 0, "msg": "用户已禁用，其登录态已全部清除"}
```

成功响应（启用）：

```json
{"code": 0, "msg": "用户已启用"}
```

失败响应：

```json
{"code": 1, "error": "用户不存在"}
{"code": 1, "error": "不能禁用/启用当前登录账号"}
```

> 禁用效果：该用户**无法登录**（登录提示"用户名或密码错误"），**已有 Token 立即失效**（服务端主动清除 + Filter 双重校验）。

---

## 附录 A：完整错误场景对照表

| 场景 | HTTP | body | X-Err-Code |
|---|---|---|---|
| 登录成功 | 200 | `{"code":0,"token":...}` | 0 |
| 密码错误/用户不存在/用户已禁用 | 200 | `{"code":1,"error":"用户名或密码错误"}` | 1 |
| 未带有效 Bearer 或登录 Cookie | 200 | `{"code":1,"error":"未登录或Token已过期"}` | 1 |
| Token 过期/失效 | 200 | `{"code":1,"error":"未登录或Token已过期"}` | 1 |
| 普通用户调管理员接口 | 200 | `{"code":1,"error":"需要管理员权限"}` | 1 |
| 参数缺失/格式错误 | 200 | `{"code":1,"error":"..."}` | 1 |
| 用户名已存在 | 200 | `{"code":1,"error":"用户名已存在"}` | 1 |
| 删除/禁用自己 | 200 | `{"code":1,"error":"不能删除/禁用当前登录账号"}` | 1 |
| 目标用户不存在 | 200 | `{"code":1,"error":"用户不存在"}` | 1 |
| 数据库异常 | 200 | `{"code":1,"error":"internal error"}` | 1 |

## 附录 B：接口汇总速查

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | /api/login | 公开 | 登录获取 Token |
| POST | /api/logout | 登录 | 登出，销毁当前 Token |
| GET | /api/user/profile | 登录 | 当前用户信息 |
| GET | /api/user/tokens | 登录 | 当前账号有效 Token 列表 |
| POST | /api/user/change_password | 登录 | 修改自己的密码 |
| POST | /api/user/create | 管理员 | 新增用户（可选 role） |
| POST | /api/user/delete | 管理员 | 删除用户（级联清 Token） |
| POST | /api/user/disable | 管理员 | 禁用/启用用户（禁用即踢下线） |

## 4. 业务接口（从原型迁入）

这些接口统一返回 HTTP 200，JSON 成功 `code=0`，失败 `code=1,error=...`；原型前端已适配。CSV 与图片成功返回二进制内容并设置 `X-Err-Code: 0`，鉴权失败仍返回 JSON。

| 方法 | 路径 | 权限 | 用途 |
|---|---|---|---|
| GET | /health | 公开 | 检查 PostgreSQL 连接，标识 C++ / PostgreSQL 后端 |
| GET | /api/bootstrap | 登录 | 当前用户、设置、业务字典、下拉选项、图片能力；不返回全量业务记录 |
| GET | /api/export?kind=events | 登录 | 沿用 query 的筛选条件， events/endpoints/policies/rules/assets/approvals/scans/reports/watermarks/watermarkImages/audit CSV |
| POST | /api/save | 管理员 | `{kind,item}`，保存 policies/rules/watermarks |
| POST | /api/update | 管理员 | `{kind,ids,changes}`，事件处置、终端隔离、审批、策略启停 |
| POST | /api/delete | 管理员 | `{kind,id}`，删除 policies/rules/watermarks |
| POST | /api/scan | 管理员 | `{name,scope}`，创建20秒演示扫描，事务锁避免并发重复 |
| POST | /api/detect | 登录 | `{content}`，关键词 / 内置个人信息格式检测 |
| POST | /api/settings | 管理员 | 更新系统设置字段 |
| POST | /api/report | 管理员 | `{name,period}`，生成统计快照 |
| POST | /api/watermark-images/import | 管理员 | `{filename,data,title?,note?,metadata?}`，Base64图片导入 |
| POST | /api/watermark-images/save | 管理员 | `{id,metadata}`，保存人工核验信息 |
| POST | /api/watermark-images/ocr | 管理员 | `{id}`，返回 `item` 和待核验 `suggestions` |
| POST | /api/watermark-images/delete | 管理员 | `{id}`，同事务删除文件索引与元数据；接口立即停止提供该图片 |
| GET | /api/watermark-image/{id} | 登录 | 原图；`?thumb=1` 缩略图；`?download=1` 下载 |

浏览器可以使用登录返回的 HttpOnly `dlp_token` Cookie，同源写请求带 `X-DLP-Request: 1`；外部客户端继续使用 `Authorization: Bearer <token>`。图片不支持查询参数 Token。

新增环境变量见 `deploy/dlpcenter.env.example`。新服务端只连接 PostgreSQL，不访问旧 SQLite 数据库。原登录会话不会迁移，切换后请重新登录。

普通用户可以读取业务数据和执行内容识别；业务配置、审批及图片修改要求管理员。改密后的已有 Token 行为沿用原项目：不会自动清除，前端应引导重新登录。


## 5. PostgreSQL 查询接口

- `GET /api/query?kind=events&page=1&pageSize=10`：返回 `{code,items,total,page,pageSize}`。`kind` 支持 events / endpoints / policies / rules / assets / approvals / scans / reports / watermarks / watermarkImages / audit。
- 筛选参数：`q`（字面文本，`%` / `_` 不作为通配符）、status / severity / channel / department / action / risk / scope / type / endpointId / endpoint / owner / policyId / rule / os；`enabledState=enabled|disabled`；`from` / `to` 为包含边界日期的 `YYYY-MM-DD`。
- 排序参数：`sort=time|name|priority|importedAt|id`，`direction=asc|desc`；分页大小 1–100。所有条件由 SQL 执行，使用参数绑定。
- `GET /api/statistics?period=7&chartPeriod=7`：返回总量、导航待办、终端 / 资产 / 策略 / 水印摘要、趋势、部门排行、通道分布和重点事件。period 支持 1（服务器时区今天）/ 7 / 30，chartPeriod 为 7 / 30。结果来自 SQL 聚合及数据库一致性快照。
- `GET /api/search?q=关键词`：返回 events / endpoints / policies 的搜索结果，每类最多 4 条，数据库检索。
- `GET /api/detail?kind=endpoints&id=...`：返回 `{item,related}`；终端和图片详情包含数据库关联查询返回的 events / eventCount，图片另含 endpoint / policy。
- `GET /api/export` 接受同一组查询筛选及排序参数，导出全部匹配结果。

部门和通道选项保存在 `dlp_catalogs`；系统设置保存在 `dlp_settings`；所有策略及水印配置保存在 `dlp_records`。图片二进制由磁盘读取，`dlp_watermark_images` 保存相对路径、大小、MIME 和哈希。原 BYTEA 字段仅作为升级入口，迁移后置空，运行接口不会从中读取图片。删除后不再提供图片；不可变文件保留供一致性备份使用，备份包含文件归档。


## 控制台用户管理（管理员）

运营管理 → 用户管理使用已有账号表 `users`，不另建演示账号副本。

- `GET /api/user/list?q=&role=&status=&page=1&pageSize=10`：按用户名文字检索（`%`、`_` 为普通字符），支持 role=`admin|user`、status=`enabled|disabled`，pageSize 为 1–100。返回 `items`、`total`、`page`、`pageSize` 和全库 `stats`（total / enabled / disabled / admins）。页码超出结果时回落到最后一页。检索、分页、统计均在 PostgreSQL 同一只读快照执行；只返回 id、username、role、disabled、created_at，创建时间为北京时间，不返回密码或 Token。
- `POST /api/user/create`：`{username,password_hash,role}`。前端校验初始密码至少 8 个字符、两次输入一致，并提交 SHA-256；后端继续使用 bcrypt 存储。
- `POST /api/user/disable`：`{username,disabled:true|false}`，禁用后撤销会话，重新启用后可使用原密码登录。
- `POST /api/user/delete`：`{username}`，级联清理会话，保留历史审计。

上述接口均通过 AdminFilter；普通用户不能列出或管理账号。不能删除或禁用当前登录账号。删除、禁用、启用在界面上均需确认。


## 修改本人密码

右上角账号菜单 → 修改密码，管理员和普通用户均可使用。

`POST /api/user/change_password`（AuthFilter），请求 `{old_password_hash,new_password_hash}`，均为原密码的 SHA-256 十六进制值。前端要求新密码 8–128 个字符、与当前密码不同、两次输入一致。服务端在同一 PostgreSQL 事务中锁定当前账号、校验原密码、保存新的 bcrypt 哈希、清理该账号全部 `user_tokens` 并写成功审计；失败回滚，成功同时清除登录 Cookie。旧会话和旧密码失效，须使用新密码重新登录。当前密码错误会记录失败审计，不修改密码或登录状态。

界面文案统一使用产品名称；`/health` 中运行模式为 `standalone`。旧部署可运行 `python scripts/update_product_copy.py` 清理内置水印记录标题和备注，脚本幂等，不修改上传图片、识别原文、关联信息或历史审计。

历史系统初始化日志仅在界面上统一展示措辞，数据库审计原文及日志导出保持原样，便于追溯。用户上传图片、识别原文和用户输入内容不作全局字符串替换。
