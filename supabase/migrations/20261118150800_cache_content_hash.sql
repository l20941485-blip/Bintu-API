-- Preserve the source content hash across persistent-cache hits.
alter table public.scrape_cache
    add column if not exists content_hash text;
