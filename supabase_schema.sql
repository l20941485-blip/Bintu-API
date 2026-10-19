create table if not exists public.scrape_cache (
    url text not null,
    render_js boolean not null default false,
    include_nav boolean not null default false,
    include_header boolean not null default false,
    include_footer boolean not null default false,
    markdown text not null,
    truncated boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (url, render_js, include_nav, include_header, include_footer)
);

create table if not exists public.developer_usage (
    rapidapi_user text primary key,
    total_scrapes_counted bigint not null default 0,
    total_tokens_counted bigint not null default 0,
    last_mode text not null default 'scrape',
    updated_at timestamptz not null default now()
);

alter table public.scrape_cache enable row level security;
alter table public.developer_usage enable row level security;
revoke all on public.scrape_cache, public.developer_usage from anon, authenticated;
grant all on public.scrape_cache, public.developer_usage to service_role;

-- Token Tax metering: extend usage counts with per-execution token volume.
-- Existing rows gain the new columns via ALTER; fresh installs get them inline.
alter table public.developer_usage
    add column if not exists total_tokens_counted bigint not null default 0;
alter table public.developer_usage
    add column if not exists last_mode text not null default 'scrape';

create or replace function public.increment_developer_usage(
    p_rapidapi_user text,
    p_tokens bigint default 1,
    p_mode text default 'scrape'
)
returns void
language sql
security invoker
set search_path = ''
as $$
    insert into public.developer_usage (
        rapidapi_user, total_scrapes_counted, total_tokens_counted, last_mode, updated_at
    )
    values (p_rapidapi_user, 1, greatest(p_tokens, 0), p_mode, pg_catalog.now())
    on conflict (rapidapi_user) do update
    set total_scrapes_counted = public.developer_usage.total_scrapes_counted + 1,
        total_tokens_counted = public.developer_usage.total_tokens_counted + greatest(p_tokens, 0),
        last_mode = excluded.last_mode,
        updated_at = pg_catalog.now();
$$;

grant execute on function public.increment_developer_usage(text, bigint, text) to service_role;
-- Backwards compatibility: the old 1-arg call shape keeps working.
create or replace function public.increment_developer_usage(p_rapidapi_user text)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.increment_developer_usage(p_rapidapi_user, 1, 'scrape');
$$;

grant execute on function public.increment_developer_usage(text) to service_role;
