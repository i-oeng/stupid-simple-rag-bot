# Supabase Schema

`schema.sql` is a production-oriented data model for moving the prototype from local JSON storage to Postgres.

It includes:

- clients and sites
- uploaded documents and document chunks
- vector embeddings for RAG search
- proposals and proposal versions
- audit events
- workflow events from n8n, Telegram, CRM, or other automations

The current app still runs fully locally with JSON/Chroma storage. This schema is included to show the intended migration path for a multi-user operations system.