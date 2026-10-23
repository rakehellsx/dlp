CREATE TABLE IF NOT EXISTS users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(64) UNIQUE NOT NULL,
    password_hash VARCHAR(128) NOT NULL,   -- 存储格式：bcrypt( sha256hex(客户端原始密码) )
    role          VARCHAR(16) NOT NULL DEFAULT 'user',      -- 'admin' 或 'user'
    disabled      BOOLEAN NOT NULL DEFAULT false,           -- true=禁用（不能登录，Token立即失效）
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- 兼容旧库：已有表补字段
ALTER TABLE users ADD COLUMN IF NOT EXISTS role    VARCHAR(16) NOT NULL DEFAULT 'user';
ALTER TABLE users ADD COLUMN IF NOT EXISTS disabled BOOLEAN NOT NULL DEFAULT false;

CREATE TABLE IF NOT EXISTS user_tokens (
    id         SERIAL PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token      VARCHAR(64) UNIQUE NOT NULL,
    expire_at  TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_user_tokens_token  ON user_tokens(token);
CREATE INDEX IF NOT EXISTS idx_user_tokens_expire ON user_tokens(expire_at);

-- 管理员通过 scripts/init_postgres.py 初始化，不预置固定密码。

-- ================= 操作审计日志 =================
CREATE TABLE IF NOT EXISTS operation_logs (
    id            SERIAL PRIMARY KEY,
    operator_id   INTEGER,                    -- 操作人ID，未登录为 0
    operator_name VARCHAR(64),                -- 操作人用户名（写入时按 users 表快照）
    action        TEXT NOT NULL,       -- login/logout/create/delete/disable/enable/change_password
    target        TEXT,                -- 操作目标（如被操作用户名）
    detail        TEXT,                       -- 补充说明（JSON 字符串）
    ip            VARCHAR(64),                -- 客户端 IP
    success       BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operation_logs_created ON operation_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_operation_logs_action  ON operation_logs(action);
CREATE INDEX IF NOT EXISTS idx_operation_logs_operator ON operation_logs(operator_id);

-- 原型业务数据保持 API JSON 结构，数据在 PostgreSQL JSONB 中持久化。
CREATE TABLE IF NOT EXISTS dlp_records (
    seq BIGSERIAL UNIQUE NOT NULL,
    kind TEXT NOT NULL,
    id TEXT NOT NULL,
    data JSONB NOT NULL,
    PRIMARY KEY(kind,id)
);
CREATE INDEX IF NOT EXISTS idx_dlp_records_kind_seq ON dlp_records(kind,seq);
CREATE TABLE IF NOT EXISTS dlp_settings (id INTEGER PRIMARY KEY CHECK(id=1), data JSONB NOT NULL);
CREATE TABLE IF NOT EXISTS dlp_watermark_images (
    id TEXT PRIMARY KEY,
    original BYTEA NOT NULL,
    thumbnail BYTEA NOT NULL,
    hash TEXT UNIQUE NOT NULL,
    mime TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS dlp_migrations (name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now());

-- Business option catalogs are queried from PostgreSQL, not maintained by browser arrays.
CREATE TABLE IF NOT EXISTS dlp_catalogs (
 category TEXT NOT NULL, key TEXT NOT NULL, label TEXT NOT NULL,
 position INTEGER NOT NULL DEFAULT 0, config JSONB NOT NULL DEFAULT '{}',
 PRIMARY KEY(category,key)
);
INSERT INTO dlp_catalogs(category,key,label,position) VALUES
 ('department','rd','研发中心',1),('department','marketing','市场营销部',2),
 ('department','finance','财务部',3),('department','hr','人力资源部',4),
 ('department','design','产品设计部',5),('department','admin','行政管理部',6)
 ON CONFLICT DO NOTHING;
INSERT INTO dlp_catalogs(category,key,label,position,config) VALUES
 ('channel','im','即时通讯',1,'{"icon":"message"}'),('channel','usb','USB 外设',2,'{"icon":"usb"}'),
 ('channel','web','浏览器上传',3,'{"icon":"globe"}'),('channel','mail','电子邮件',4,'{"icon":"mail"}'),
 ('channel','print','打印输出',5,'{"icon":"printer"}'),('channel','clipboard','剪贴板',6,'{"icon":"clipboard"}')
 ON CONFLICT DO NOTHING;
CREATE INDEX IF NOT EXISTS idx_records_search ON dlp_records USING gin(data jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_records_status ON dlp_records(kind,(data->>'status'));
CREATE INDEX IF NOT EXISTS idx_records_department ON dlp_records(kind,(data->>'department'));
CREATE INDEX IF NOT EXISTS idx_records_endpoint ON dlp_records(kind,(data->>'endpointId'));
CREATE INDEX IF NOT EXISTS idx_records_time ON dlp_records(kind,(data->>'time'));

-- File bytes live on disk. Keep nullable legacy columns only for an explicit upgrade.
ALTER TABLE dlp_watermark_images ALTER COLUMN original DROP NOT NULL;
ALTER TABLE dlp_watermark_images ALTER COLUMN thumbnail DROP NOT NULL;
ALTER TABLE dlp_watermark_images ADD COLUMN IF NOT EXISTS original_path TEXT;
ALTER TABLE dlp_watermark_images ADD COLUMN IF NOT EXISTS thumbnail_path TEXT;
ALTER TABLE dlp_watermark_images ADD COLUMN IF NOT EXISTS size BIGINT NOT NULL DEFAULT 0;
