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
    updated_at timestamptz not null default now()
);

alter table public.scrape_cache enable row level security;
alter table public.developer_usage enable row level security;
revoke all on public.scrape_cache, public.developer_usage from anon, authenticated;
grant all on public.scrape_cache, public.developer_usage to service_role;

create or replace function public.increment_developer_usage(p_rapidapi_user text)
returns void
language sql
security invoker
set search_path = ''
as $$
    insert into public.developer_usage (rapidapi_user, total_scrapes_counted, updated_at)
    values (p_rapidapi_user, 1, pg_catalog.now())
    on conflict (rapidapi_user) do update
    set total_scrapes_counted = public.developer_usage.total_scrapes_counted + 1,
        updated_at = pg_catalog.now();
$$;

grant execute on function public.increment_developer_usage(text) to service_role;
