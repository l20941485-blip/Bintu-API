alter table public.scrape_cache
  add column if not exists content_cleaning jsonb;
