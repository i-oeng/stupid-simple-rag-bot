create extension if not exists pgcrypto;
create extension if not exists vector;

create table if not exists clients (
    id uuid primary key default gen_random_uuid(),
    company_name text not null,
    contact_name text,
    contact_email text,
    phone text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    client_id uuid references clients(id) on delete set null,
    filename text not null,
    document_type text not null default 'unknown',
    storage_path text,
    file_hash text,
    extraction_confidence numeric,
    qr_payload jsonb not null default '[]'::jsonb,
    visual_markers jsonb not null default '[]'::jsonb,
    validation jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists document_chunks (
    id uuid primary key default gen_random_uuid(),
    document_id uuid not null references documents(id) on delete cascade,
    page_number integer,
    chunk_index integer not null,
    content text not null,
    embedding vector(384),
    metadata jsonb not null default '{}'::jsonb
);

create table if not exists document_cases (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references documents(id) on delete set null,
    client_id uuid references clients(id) on delete set null,
    status text not null default 'New' check (status in ('New', 'Parsed', 'Needs Review', 'Approved', 'Sent')),
    risk_level text not null default 'unknown',
    metadata jsonb not null default '{}'::jsonb,
    extracted_fields jsonb not null default '{}'::jsonb,
    period_metrics jsonb not null default '[]'::jsonb,
    review_settings jsonb not null default '{}'::jsonb,
    case_summary jsonb not null default '{}'::jsonb,
    generated_report text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists case_versions (
    id uuid primary key default gen_random_uuid(),
    case_id uuid not null references document_cases(id) on delete cascade,
    version_label text not null,
    review_settings jsonb not null default '{}'::jsonb,
    case_summary jsonb not null default '{}'::jsonb,
    created_by text,
    created_at timestamptz not null default now()
);

create table if not exists audit_events (
    id uuid primary key default gen_random_uuid(),
    case_id uuid references document_cases(id) on delete cascade,
    actor text not null default 'system',
    action text not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists workflow_events (
    id uuid primary key default gen_random_uuid(),
    case_id uuid references document_cases(id) on delete cascade,
    source text not null,
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_documents_client on documents(client_id);
create index if not exists idx_documents_type on documents(document_type);
create index if not exists idx_chunks_document on document_chunks(document_id);
create index if not exists idx_document_cases_status on document_cases(status);
create index if not exists idx_document_cases_client on document_cases(client_id);
create index if not exists idx_audit_case_created on audit_events(case_id, created_at desc);

-- Run this after enough vectors exist and tune lists for dataset size.
-- create index idx_chunks_embedding on document_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

alter table clients enable row level security;
alter table documents enable row level security;
alter table document_chunks enable row level security;
alter table document_cases enable row level security;
alter table case_versions enable row level security;
alter table audit_events enable row level security;
alter table workflow_events enable row level security;

-- Prototype policy: authenticated users can read/write everything.
-- Replace with role-based policies before production.
create policy "authenticated full access clients" on clients for all to authenticated using (true) with check (true);
create policy "authenticated full access documents" on documents for all to authenticated using (true) with check (true);
create policy "authenticated full access chunks" on document_chunks for all to authenticated using (true) with check (true);
create policy "authenticated full access document cases" on document_cases for all to authenticated using (true) with check (true);
create policy "authenticated full access case versions" on case_versions for all to authenticated using (true) with check (true);
create policy "authenticated full access audit" on audit_events for all to authenticated using (true) with check (true);
create policy "authenticated full access workflow events" on workflow_events for all to authenticated using (true) with check (true);