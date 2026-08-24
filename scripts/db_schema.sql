-- RedDream P2 数据库结构：知识块 + 知识图谱 + 审核记录
-- 以 postgres 超级账号连到 reddream 库执行本文件。

SET client_encoding TO 'UTF8';

-- 让专用小号成为 public 模式的主人
ALTER SCHEMA public OWNER TO reddream_app;

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
    review_status VARCHAR(20) DEFAULT 'pending'
);

ALTER TABLE public.chunks OWNER TO reddream_app;
CREATE INDEX IF NOT EXISTS idx_chunks_review_status ON public.chunks(review_status);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON public.chunks(content_hash);

-- ============================================
--  知识图谱三元组表
-- ============================================
CREATE TABLE IF NOT EXISTS public.kg_triples (
    id        SERIAL PRIMARY KEY,
    subject   TEXT NOT NULL,
    relation  TEXT NOT NULL,
    object    TEXT NOT NULL,
    source    VARCHAR(50),
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

\echo '=== Schema Ready ==='
\d public.chunks
\d public.kg_triples
\d public.review_log
\d public.wiki_pages
