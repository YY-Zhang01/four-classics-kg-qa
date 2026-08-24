-- RedDream 数据库结构（单一入口，完整 schema）
-- 以 postgres 超级账号连到 reddream 库执行本文件：
--   psql -U postgres -d reddream -f scripts/db_schema.sql

SET client_encoding TO 'UTF8';

-- 让专用小号成为 public 模式的主人
ALTER SCHEMA public OWNER TO reddream_app;

-- ============================================
--  用户表（认证：注册/登录/JWT）
-- ============================================
CREATE TABLE IF NOT EXISTS public.users (
    id            SERIAL PRIMARY KEY,
    username      VARCHAR(50)  NOT NULL UNIQUE,
    password_hash TEXT         NOT NULL,
    display_name  VARCHAR(100),
    role          VARCHAR(20)  NOT NULL DEFAULT 'user',
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE public.users OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_users_role ON public.users(role);

-- ============================================
--  知识块表
-- ============================================
CREATE TABLE IF NOT EXISTS public.chunks (
    id            text PRIMARY KEY,
    source        text NOT NULL,
    chapter       text,
    body          text NOT NULL,
    embedding     real[],
    -- P0 evidence columns
    page_no       INTEGER,
    paragraph_no  INTEGER,
    content_hash  VARCHAR(64),
    source_url    TEXT,
    review_status VARCHAR(20) DEFAULT 'pending',
    -- P5 软删除标记
    is_active     BOOLEAN DEFAULT TRUE
);

ALTER TABLE public.chunks OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_chunks_review_status ON public.chunks(review_status);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON public.chunks(content_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_active ON public.chunks(is_active);

-- ============================================
--  知识图谱三元组表
-- ============================================
CREATE TABLE IF NOT EXISTS public.kg_triples (
    id        SERIAL PRIMARY KEY,
    subject   TEXT NOT NULL,
    relation  TEXT NOT NULL,
    object    TEXT NOT NULL,
    source    VARCHAR(50),
    domain    VARCHAR(50),
    -- P0 evidence columns
    confidence      REAL DEFAULT 0.0,
    source_chunk_id TEXT,
    review_status   VARCHAR(20) DEFAULT 'pending',
    extract_method  VARCHAR(20) DEFAULT 'llm',
    UNIQUE(subject, relation, object)
);

ALTER TABLE public.kg_triples OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_kg_review_status ON public.kg_triples(review_status);
CREATE INDEX IF NOT EXISTS idx_kg_source_chunk ON public.kg_triples(source_chunk_id);
CREATE INDEX IF NOT EXISTS idx_kg_domain ON public.kg_triples(domain);

-- ============================================
--  审核记录表
-- ============================================
CREATE TABLE IF NOT EXISTS public.review_log (
    id          SERIAL PRIMARY KEY,
    target_type VARCHAR(20)  NOT NULL,
    target_id   TEXT         NOT NULL,
    action      VARCHAR(20)  NOT NULL,
    reviewer    VARCHAR(50),
    reason      TEXT,
    old_value   JSONB,
    new_value   JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.review_log OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_review_target ON public.review_log(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_review_time   ON public.review_log(created_at);

-- ============================================
--  Wiki 百科页面表（P1）
-- ============================================
CREATE TABLE IF NOT EXISTS public.wiki_pages (
    id          SERIAL PRIMARY KEY,
    page_type   VARCHAR(30)  NOT NULL,
    title       TEXT         NOT NULL,
    domain      VARCHAR(50)  NOT NULL,
    content     JSONB        NOT NULL,
    entities    TEXT[]       DEFAULT '{}',
    confidence  REAL         DEFAULT 0.0,
    review_status VARCHAR(20) DEFAULT 'pending',
    version     INTEGER      DEFAULT 1,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    UNIQUE(domain, page_type, title)
);

ALTER TABLE public.wiki_pages OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_wiki_domain ON public.wiki_pages(domain);
CREATE INDEX IF NOT EXISTS idx_wiki_type   ON public.wiki_pages(page_type);
CREATE INDEX IF NOT EXISTS idx_wiki_entities ON public.wiki_pages USING GIN(entities);
CREATE INDEX IF NOT EXISTS idx_wiki_review ON public.wiki_pages(review_status);

-- ============================================
--  数据源注册表（P5 增量更新）
-- ============================================
CREATE TABLE IF NOT EXISTS public.data_sources (
    id          SERIAL PRIMARY KEY,
    name        TEXT         NOT NULL,
    source_type VARCHAR(20)  NOT NULL DEFAULT 'file',   -- file / url / directory
    path        TEXT         NOT NULL,
    domain      VARCHAR(50)  NOT NULL,
    file_hash   VARCHAR(64),                             -- 上次处理时的文件 SHA256
    file_size   BIGINT,                                  -- 上次处理时的文件大小(字节)
    chunk_count INTEGER      DEFAULT 0,
    enabled     BOOLEAN      DEFAULT TRUE,
    last_scan   TIMESTAMPTZ,
    last_update TIMESTAMPTZ,
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
--  增量更新日志表（P5）
-- ============================================
CREATE TABLE IF NOT EXISTS public.update_log (
    id          SERIAL PRIMARY KEY,
    source_id   INTEGER      REFERENCES data_sources(id),
    domain      VARCHAR(50)  NOT NULL,
    action      VARCHAR(20)  NOT NULL,  -- scan / new_file / changed / unchanged / error
    detail      JSONB,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

ALTER TABLE public.update_log OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_updatelog_domain ON public.update_log(domain);
CREATE INDEX IF NOT EXISTS idx_updatelog_time   ON public.update_log(created_at);

\echo '=== Schema Ready ==='
\d public.users
\d public.chunks
\d public.kg_triples
\d public.review_log
\d public.wiki_pages
\d public.data_sources
\d public.update_log
