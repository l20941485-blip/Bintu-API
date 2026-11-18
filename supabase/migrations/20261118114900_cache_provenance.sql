-- Preserve page provenance across persistent-cache hits.
alter table public.scrape_cache
    add column if not exists page_title text,
    add column if not exists content_fingerprint text;
