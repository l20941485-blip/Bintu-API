create table if not exists public.developer_usage (
    rapidapi_user text primary key,
    total_scrapes_counted bigint not null default 0,
    total_tokens_counted bigint not null default 0,
    gateway text not null default 'unknown',
    last_mode text not null default 'scrape',
    updated_at timestamptz not null default now()
);

alter table public.developer_usage
    add column if not exists total_scrapes_counted bigint not null default 0,
    add column if not exists total_tokens_counted bigint not null default 0,
    add column if not exists gateway text,
    add column if not exists last_mode text not null default 'scrape',
    add column if not exists updated_at timestamptz not null default now();

update public.developer_usage
set gateway = 'unknown'
where gateway is null;

update public.developer_usage
set last_mode = 'unspecified'
where last_mode is null;

alter table public.developer_usage
    alter column gateway set default 'unknown',
    alter column gateway set not null,
    alter column last_mode set default 'scrape',
    alter column last_mode set not null;

alter table public.developer_usage enable row level security;
revoke all on public.developer_usage from anon, authenticated;
grant all on public.developer_usage to service_role;

create or replace function public.increment_developer_usage(
    p_rapidapi_user text,
    p_gateway text,
    p_scrapes bigint,
    p_tokens bigint,
    p_mode text
)
returns void
language sql
security invoker
set search_path = ''
as $$
    insert into public.developer_usage (
        rapidapi_user, total_scrapes_counted, total_tokens_counted, gateway, last_mode, updated_at
    )
    values (
        p_rapidapi_user,
        greatest(coalesce(p_scrapes, 1), 0),
        greatest(coalesce(p_tokens, 0), 0),
        coalesce(p_gateway, 'unknown'),
        coalesce(p_mode, 'unspecified'),
        pg_catalog.now()
    )
    on conflict (rapidapi_user) do update
    set total_scrapes_counted = public.developer_usage.total_scrapes_counted + excluded.total_scrapes_counted,
        total_tokens_counted = public.developer_usage.total_tokens_counted + excluded.total_tokens_counted,
        gateway = public.developer_usage.gateway,
        last_mode = excluded.last_mode,
        updated_at = pg_catalog.now();
$$;

grant execute on function public.increment_developer_usage(text, text, bigint, bigint, text) to service_role;

-- Keep the existing database.py RPC call shapes working while callers migrate.
create or replace function public.increment_developer_usage(
    p_rapidapi_user text,
    p_tokens bigint,
    p_mode text
)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.increment_developer_usage(
        p_rapidapi_user, 'unknown', 1, p_tokens, p_mode
    );
$$;

grant execute on function public.increment_developer_usage(text, bigint, text) to service_role;

create or replace function public.increment_developer_usage(p_rapidapi_user text)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.increment_developer_usage(
        p_rapidapi_user, 'unknown', 1, 1, 'scrape'
    );
$$;

grant execute on function public.increment_developer_usage(text) to service_role;
