-- RedDream P0 Evidence Base Migration
-- Add evidence metadata columns to chunks and kg_triples tables.
-- Run as reddream_app against reddream database.

SET client_encoding TO 'UTF8';

BEGIN;

-- ============================================
--  chunks: evidence metadata columns
-- ============================================

ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS page_no INTEGER;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS paragraph_no INTEGER;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS content_hash VARCHAR(64);
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS source_url TEXT;
ALTER TABLE public.chunks ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending';

CREATE INDEX IF NOT EXISTS idx_chunks_review_status ON public.chunks(review_status);
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON public.chunks(content_hash);


-- ============================================
--  kg_triples: evidence + review columns
-- ============================================

ALTER TABLE public.kg_triples ADD COLUMN IF NOT EXISTS confidence REAL DEFAULT 0.0;
ALTER TABLE public.kg_triples ADD COLUMN IF NOT EXISTS source_chunk_id TEXT;
ALTER TABLE public.kg_triples ADD COLUMN IF NOT EXISTS review_status VARCHAR(20) DEFAULT 'pending';
ALTER TABLE public.kg_triples ADD COLUMN IF NOT EXISTS extract_method VARCHAR(20) DEFAULT 'llm';

CREATE INDEX IF NOT EXISTS idx_kg_review_status ON public.kg_triples(review_status);
CREATE INDEX IF NOT EXISTS idx_kg_source_chunk ON public.kg_triples(source_chunk_id);


-- ============================================
--  review_log: audit trail for review actions
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

CREATE INDEX IF NOT EXISTS idx_review_target ON public.review_log(target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_review_time   ON public.review_log(created_at);

COMMIT;

\echo '=== P0 Migration Complete ==='
\echo 'chunks new columns: page_no, paragraph_no, content_hash, source_url, review_status'
\echo 'kg_triples new columns: confidence, source_chunk_id, review_status, extract_method'
\echo 'new table: review_log'
