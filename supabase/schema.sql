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

create table if not exists sites (
    id uuid primary key default gen_random_uuid(),
    client_id uuid not null references clients(id) on delete cascade,
    address text,
    country text,
    usable_roof_area_m2 numeric,
    created_at timestamptz not null default now()
);

create table if not exists documents (
    id uuid primary key default gen_random_uuid(),
    client_id uuid references clients(id) on delete set null,
    site_id uuid references sites(id) on delete set null,
    filename text not null,
    document_type text not null default 'unknown',
    storage_path text,
    extraction_confidence numeric,
    qr_payload jsonb not null default '[]'::jsonb,
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

create table if not exists proposals (
    id uuid primary key default gen_random_uuid(),
    document_id uuid references documents(id) on delete set null,
    client_id uuid references clients(id) on delete set null,
    site_id uuid references sites(id) on delete set null,
    status text not null default 'New' check (status in ('New', 'Parsed', 'Needs Review', 'Approved', 'Sent')),
    risk_level text not null default 'unknown',
    extracted_fields jsonb not null default '{}'::jsonb,
    monthly_consumption jsonb not null default '[]'::jsonb,
    assumptions jsonb not null default '{}'::jsonb,
    calculation jsonb not null default '{}'::jsonb,
    proposal_draft text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists proposal_versions (
    id uuid primary key default gen_random_uuid(),
    proposal_id uuid not null references proposals(id) on delete cascade,
    version_label text not null,
    assumptions jsonb not null default '{}'::jsonb,
    calculation jsonb not null default '{}'::jsonb,
    created_by text,
    created_at timestamptz not null default now()
);

create table if not exists audit_events (
    id uuid primary key default gen_random_uuid(),
    proposal_id uuid references proposals(id) on delete cascade,
    actor text not null default 'system',
    action text not null,
    details jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create table if not exists workflow_events (
    id uuid primary key default gen_random_uuid(),
    proposal_id uuid references proposals(id) on delete cascade,
    source text not null,
    event_type text not null,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_documents_client on documents(client_id);
create index if not exists idx_documents_type on documents(document_type);
create index if not exists idx_chunks_document on document_chunks(document_id);
create index if not exists idx_proposals_status on proposals(status);
create index if not exists idx_proposals_client on proposals(client_id);
create index if not exists idx_audit_proposal_created on audit_events(proposal_id, created_at desc);

-- Run this after enough vectors exist and tune lists for dataset size.
-- create index idx_chunks_embedding on document_chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

alter table clients enable row level security;
alter table sites enable row level security;
alter table documents enable row level security;
alter table document_chunks enable row level security;
alter table proposals enable row level security;
alter table proposal_versions enable row level security;
alter table audit_events enable row level security;
alter table workflow_events enable row level security;

-- Prototype policy: authenticated users can read/write everything.
-- Replace with role-based policies before production.
create policy "authenticated full access clients" on clients for all to authenticated using (true) with check (true);
create policy "authenticated full access sites" on sites for all to authenticated using (true) with check (true);
create policy "authenticated full access documents" on documents for all to authenticated using (true) with check (true);
create policy "authenticated full access chunks" on document_chunks for all to authenticated using (true) with check (true);
create policy "authenticated full access proposals" on proposals for all to authenticated using (true) with check (true);
create policy "authenticated full access proposal versions" on proposal_versions for all to authenticated using (true) with check (true);
create policy "authenticated full access audit" on audit_events for all to authenticated using (true) with check (true);
create policy "authenticated full access workflow events" on workflow_events for all to authenticated using (true) with check (true);