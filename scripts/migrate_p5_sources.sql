-- P5 数据源管理：data_sources 表 + chunks 软删除字段
-- 在 reddream 库中以 superuser 执行

-- ============================================
--  数据源注册表
-- ============================================
CREATE TABLE IF NOT EXISTS public.data_sources (
    id          SERIAL PRIMARY KEY,
    name        TEXT         NOT NULL,
    source_type VARCHAR(20)  NOT NULL DEFAULT 'file',   -- file / url / directory
    path        TEXT         NOT NULL,                   -- 文件路径或 URL
    domain      VARCHAR(50)  NOT NULL,
    file_hash   VARCHAR(64),                             -- 上次处理时的文件 SHA256
    file_size   BIGINT,                                  -- 上次处理时的文件大小(字节)
    chunk_count INTEGER      DEFAULT 0,                  -- 上次产生的 chunk 数
    enabled     BOOLEAN      DEFAULT TRUE,
    last_scan   TIMESTAMPTZ,                             -- 最后扫描时间
    last_update TIMESTAMPTZ,                             -- 最后有变更的时间
    status      VARCHAR(20)  DEFAULT 'active',           -- active / changed / error / archived
    error_msg   TEXT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE(domain, name)
);

ALTER TABLE public.data_sources OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_sources_domain ON public.data_sources(domain);
CREATE INDEX IF NOT EXISTS idx_sources_status ON public.data_sources(status);

-- ============================================
--  更新日志表
-- ============================================
CREATE TABLE IF NOT EXISTS public.update_log (
    id          SERIAL PRIMARY KEY,
    source_id   INTEGER      REFERENCES data_sources(id),
    domain      VARCHAR(50)  NOT NULL,
    action      VARCHAR(20)  NOT NULL,  -- scan / new_file / changed / unchanged / error
    detail      JSONB,                  -- {new_chunks, updated_chunks, removed_chunks, ...}
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE public.update_log OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_updatelog_domain ON public.update_log(domain);
CREATE INDEX IF NOT EXISTS idx_updatelog_time   ON public.update_log(created_at);

-- ============================================
--  chunks 表：新增 is_active 软删除标记
-- ============================================
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;
CREATE INDEX IF NOT EXISTS idx_chunks_active ON public.chunks(is_active);

\echo '=== P5 Schema Ready ==='
\d public.data_sources
\d public.update_log
