-- P5 优化：kg_triples 加 domain 列，解除 source_name == domain 耦合
-- 在 reddream 库中以 superuser 执行

ALTER TABLE public.kg_triples ADD COLUMN IF NOT EXISTS domain VARCHAR(50);

-- 回填：现有数据 source 就是 domain（红楼梦/三国演义等）
UPDATE public.kg_triples SET domain = source WHERE domain IS NULL;

CREATE INDEX IF NOT EXISTS idx_kg_domain ON public.kg_triples(domain);

\echo '=== kg_triples.domain 列就绪 ==='
\d public.kg_triples
