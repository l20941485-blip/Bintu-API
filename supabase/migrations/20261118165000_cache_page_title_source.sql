ALTER TABLE public.scrape_cache
    ADD COLUMN IF NOT EXISTS page_title_source TEXT NOT NULL DEFAULT 'none';
