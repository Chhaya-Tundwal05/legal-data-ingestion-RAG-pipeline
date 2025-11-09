# Legal Docket Ingestion Pipeline

## Project Summary

This pipeline ingests messy, inconsistent legal docket data from JSON files, normalizes entities (courts, judges, parties, case types), and loads it into a relational PostgreSQL schema optimized for fast legal queries. The system tracks all ingestion runs and failures reliably, storing failed records in JSONL quarantine files and structured error logs for triage and reprocessing.

## Setup & Run Instructions (Docker / Docker Compose)

### Prerequisites

- Docker and Docker Compose installed
- No need to install PostgreSQL, Python, or dependencies locally

### How to Start the Full Stack

Start all services with a single command:

```bash
docker compose up -d
```

This brings up:
- **PostgreSQL** (with pgvector extension) on port 5432
- **Adminer** (database admin UI) on port 8080
- **App container** (Python environment) with port 8000 exposed for the API

Wait ~10 seconds for the database to initialize and apply the schema automatically.

### How to Run Ingestion

Ingestion is executed inside the app container, not on the host machine:

```bash
docker compose exec app python ingest.py --file raw_dockets.json
```

Or using the Makefile:

```bash
make ingest FILE=raw_dockets.json
```

### How to Run RAG Embedding Backfill

Generate embeddings for semantic search:

```bash
docker compose exec app python rag.py backfill
```

This processes all cases and creates chunk embeddings for the semantic search functionality.

### How to Run the API

The API server is available at `http://localhost:8000` once started.

Start the API server:

```bash
docker compose exec app uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

Access interactive API documentation:
- **Swagger UI:** http://localhost:8000/docs
- **ReDoc:** http://localhost:8000/redoc

### How to Run the Semantic Search Example

Test semantic search with a curl request:

```bash
curl -X POST http://localhost:8000/cases/search \
  -H "Content-Type: application/json" \
  -d '{"query":"employment discrimination in New York","limit":5}'
```

Or use the included `test.http` file with REST client extensions (VS Code REST Client, JetBrains HTTP Client).

### How to Stop / Reset the Stack

**Stop containers:**

```bash
docker compose down
```

**Reset database (WARNING: deletes all data):**

```bash
docker compose down -v
docker compose up -d
```

Or using the Makefile:

```bash
make reset-db
```

### Note for Non-Docker Users

The project can be run locally in a virtualenv with PostgreSQL installed separately, but Docker is the default recommended path for consistency and ease of setup. For local development, ensure PostgreSQL with pgvector extension is available and update `DATABASE_URL` accordingly.

## Schema Overview

The schema uses a normalized relational design with a clear separation between fact and reference data.

### Core Tables

**`cases`** is the fact table, storing one row per docket entry with foreign keys to reference entities. It includes the case number (unique), title, filed date, docket text, status, and relationships to court, judge, and case type.

**Reference tables** (`courts`, `judges`, `case_types`, `parties`) store normalized entities. Each includes both a display name and a `normalized_name` field used for matching variations. Uniqueness constraints on `normalized_name` ensure one canonical row per normalized entity, preventing duplicates while allowing multiple raw name variations to map to the same entity.

**`case_parties`** is a junction table linking cases to parties with roles (plaintiff, defendant, third_party, intervenor, other). This supports many-to-many relationships: a case can have multiple parties, and a party can appear in multiple cases with different roles.

**Name variations tables** (`court_name_variations`, `judge_name_variations`, `party_name_variations`) track all raw name forms encountered during ingestion. Each variation record includes the raw name, first seen timestamp, last seen timestamp, and seen count, enabling analysis of data quality and common variations.

**Ingestion tracking tables** (`ingest_runs`, `ingest_errors`) provide audit trails. Each run records totals (read, inserted, updated, failed) and timestamps. Failed records are logged in `ingest_errors` with error codes, messages, and full details, while raw records are preserved in JSONL quarantine files.

### Indexing Strategy

Indexes are designed to support common query patterns:

- **Case lookups**: `case_number` (unique index) for direct case retrieval
- **Date range queries**: `filed_date` for filtering by year or date ranges
- **Judge queries**: `judge_id` and composite `(judge_id, filed_date)` for "cases for Judge X in 2023"
- **Court queries**: `court_id` and composite `(court_id, case_type_id)` for "civil cases in S.D.N.Y"
- **Party queries**: `party_id` and composite `(party_id, role)` in `case_parties` for "cases where Acme Corp is defendant"
- **Full-text search**: GIN index on `docket_text` for future text search capabilities
- **Normalized name lookups**: Indexes on `normalized_name` columns for efficient entity matching

## Ingestion Pipeline

The ingestion process follows these steps:

1. **Load JSON file**: Reads the input JSON file containing docket records
2. **Start ingest run**: Creates a record in `ingest_runs` with source name and URI
3. **Process each record**:
   - Normalize and upsert reference entities (courts, judges, case types, parties) using `normalized_name` for matching
   - Record name variations for each entity encountered
   - Parse and validate the case record (case number, date, status)
   - Upsert the case using `ON CONFLICT (case_number) DO UPDATE` to detect inserts vs updates
   - Parse and link parties via `case_parties` junction table
4. **Error handling**: On validation errors (bad dates, missing fields, etc.):
   - Write raw record to JSONL quarantine file (`quarantine/ingest_run_{run_id}.jsonl`)
   - Record error in `ingest_errors` table with error code, message, and details
   - Increment failed counter and continue processing
5. **End run**: Updates `ingest_runs` with final totals and completion timestamp

### Data Quality Features

**Date parsing** supports multiple formats:
- ISO: `YYYY-MM-DD` (2024-10-03)
- US numeric: `M-D-YYYY`, `M/D/YYYY`, `MM-DD-YYYY`, `MM/DD/YYYY` (single-digit month/day allowed)
- Month names: `Oct 3, 2024`, `October 3, 2024`

Invalid dates raise `ValueError` and are quarantined rather than using sentinel values.

**Duplicate prevention**:
- Reference entities: Lookup by `normalized_name` ensures one canonical row per normalized entity
- Cases: `ON CONFLICT (case_number) DO UPDATE` prevents duplicate cases and updates existing records
- Name variations: Tracked separately to preserve all raw forms while maintaining entity normalization

**Error tracking**: Each failed record is:
- Hashed (SHA256 of canonical JSON) for deduplication
- Logged in `ingest_errors` with error code, message, and full details
- Written to JSONL quarantine file for manual review and reprocessing

## Key Trade-offs

**Raw failed records in JSONL vs staging table**: Failed records are stored in JSONL files rather than a staging database table. This keeps the MVP lightweight, allows easy file-based reprocessing, and avoids schema changes for new error types. The trade-off is that querying failed records requires file parsing rather than SQL.

**No date dimension table**: Date filtering is handled via indexed `filed_date` column rather than a separate `dim_date` table. This simplifies the schema for the current scale but may require refactoring if complex date-based analytics are needed later.

**No alias tables yet**: The schema normalizes entities but doesn't yet include dedicated alias tables for raw spellings. The `name_variations` tables serve this purpose for now, and alias tables can be added later if needed for more sophisticated matching.

**Dual error logging**: Errors are logged both structurally (in `ingest_errors` table for SQL queries) and as raw JSON copies (in quarantine files for reprocessing). This provides flexibility but requires maintaining two sources of truth.

- We intentionally did NOT store the full raw JSON in a staging table. Raw records are kept as line-delimited JSON files instead, because it keeps PostgreSQL lean, avoids premature schema decisions, and makes reprocessing easier during early iterations.

- We deferred adding a date dimension table because analytics queries are not part of the MVP. If we later need fast OLAP-style reporting, the model supports adding `dim_date` and foreign keys without breaking existing ingestion.

## How to Run

### Prerequisites

- Docker and Docker Compose installed
- Project files in a directory

### Start the Stack

```bash
# Start PostgreSQL, Adminer, and app containers
make up

# Wait ~10 seconds for database initialization
```

### Run Ingestion

```bash
# Ingest data file
make ingest FILE=data/raw_dockets.json
```

### Access Database

**Via psql:**
```bash
make psql
```

**Via Adminer (Web UI):**
1. Open http://localhost:8080 in your browser
2. Login:
   - System: PostgreSQL
   - Server: db
   - Username: postgres
   - Password: postgres
   - Database: dockets

### Other Useful Commands

```bash
# View database logs
make logs

# Shell into app container
make sh

# Stop everything
make down

# Reset database (re-apply schema)
make down -v && make up
```

## Example SQL Queries

### Find all cases for Judge X in 2023

```sql
SELECT c.case_number, c.title, c.filed_date, j.full_name as judge
FROM cases c
JOIN judges j ON c.judge_id = j.id
WHERE j.normalized_name = 'maria rodriguez'  -- Works even if judge name has variations
  AND EXTRACT(YEAR FROM c.filed_date) = 2023
ORDER BY c.filed_date DESC;
```

### Find all civil cases filed in S.D.N.Y. involving Acme Corp

```sql
SELECT DISTINCT c.case_number, c.title, c.filed_date, co.name as court
FROM cases c
JOIN courts co ON c.court_id = co.id
JOIN case_types ct ON c.case_type_id = ct.id
JOIN case_parties cp ON c.id = cp.case_id
JOIN parties p ON cp.party_id = p.id
WHERE co.normalized_name = 'SDNY'  -- Handles "S.D.N.Y" vs "S.D.N.Y." variations
  AND ct.name = 'civil'
  AND p.normalized_name = 'acme corp'  -- Handles "Acme Corp" vs "Acme Corporation"
ORDER BY c.filed_date DESC;
```

## Future Extensions

- Alias tables for raw spellings to support fuzzy matching
- `raw_dockets` staging table for reprocessing failed records
- Optional date dimension table for BI and analytics
- Partitioning by year if dataset grows to millions of records
- Incremental update support for daily docket feeds
- Data quality dashboard with anomaly detection
- Add optional SQL filters (year, court, case type) to semantic search for hybrid ranking
- Add pagination and ordering to `GET /cases` once dataset grows
- Partition `cases` and `case_chunk_embeddings` by year if ingestion volume reaches tens of millions of rows
- Streaming ingestion (event-driven): evolve from batch JSON imports to a streaming pipeline (Kafka/SQS/Kinesis) with idempotent upserts and backpressure handling.
- Async embedding pipeline: move embedding/backfill into a background task queue (Celery/RQ/Dramatiq) so new/updated dockets are embedded continuously without blocking ingestion.
- Relevance evaluation & tuning: add an evaluation harness (precision@k, recall@k) with labeled queries; experiment with score fusion weights and chunk sizes to improve retrieval quality.
- API hardening: introduce authentication (API keys/JWT/OAuth), basic rate limiting, and API versioning (e.g., /v1) before external exposure.
- Hybrid lexical + semantic ranking: combine PostgreSQL full-text search (GIN/tsvector) with pgvector cosine similarity using score fusion for higher precision on keyword-sensitive queries.

## Part 2 – Semantic Retrieval (RAG over docket_text)

### Overview

The system now supports semantic search over docket text using open-source embeddings, pgvector, and chunked approximate nearest neighbor (ANN) search. Users can query docket content using natural language and receive top-K matching cases ranked by similarity scores, enabling discovery of relevant cases based on semantic meaning rather than exact keyword matches.

### Design Choices & Rationale

| Area | Final Choice | Why |
|------|--------------|-----|
| Embedding model | sentence-transformers/all-MiniLM-L6-v2 (open-source, 384-dim) | No API cost, reproducible, private data |
| Vector store | pgvector inside PostgreSQL | Same DB as Part 1, keeps SQL filtering + ANN in one place |
| Chunking strategy | Fixed character chunks (default 1200 chars, 200 overlap) | More accurate retrieval than single-vector case embedding. We embed per-chunk instead of a single vector per case because long docket text loses semantic meaning when collapsed into one embedding. Chunking keeps relevance high while still allowing case-level aggregation in the search results. |
| Similarity metric | Cosine | Standard + directly supported in pgvector |
| Index type | IVFFLAT w/ cosine ops | Fast ANN search, tunable via lists + probes |
| Aggregation | Chunk similarity → best chunk per case → ranked cases | Lets us return case-level results while using finer chunk vectors |

### How it works (architecture summary)

- `rag.py` bootstraps `case_chunk_embeddings` table if missing
- `backfill_chunk_embeddings()` → chunks → embeds → upserts
- `search_dockets(query)` → embed query → ANN search → return top K cases
- Results include: case_number, title, filed_date, judge, court, best_similarity, best_chunk_snippet

### Example CLI Usage

```bash
# Backfill embeddings for all cases
python rag.py backfill

# Run a semantic query
python rag.py search --q "employment discrimination in New York" --k 5
```

### Why embeddings are stored in PostgreSQL instead of FAISS/Qdrant

- pgvector keeps both structured filtering (SQL) and ANN search in one place, which makes hybrid filters (year, court, judge) possible without multiple systems.
- This avoids external infra for now (no separate vector DB, no sync jobs).
- If embedding volume grows into tens of millions of chunks, the system can migrate to Qdrant/Milvus with no upstream changes in the ingestion layer.

### Trade-offs & Future Extensions

- Open-source embeddings keep cost = $0, but lower recall vs OpenAI models
- pgvector keeps compute + filtering in one DB, but for 50M+ chunks we may move to Qdrant/Milvus
- Fixed chunking works for MVP, but token-based or semantic chunking can improve precision later
- One-model / one-dimension today — if embedding model changes, table must be rebuilt
- Future optimizations: HNSW index, hybrid BM25 + vector ranking, date/court filters built into query API, model swap env flag, async batch embedding, etc.

### Folder / File responsibilities

| File | Purpose |
|------|---------|
| schema.sql | Core relational model (no vectors) |
| rag.py | Chunking, embedding, vector storage, semantic search |
| ingest.py | Structured ingestion + anomaly logging |
| case_chunk_embeddings (table) | One row per chunk per case |

## Part 3 – REST API

### Overview

The REST API provides programmatic access to case data and semantic search capabilities. The API is built with FastAPI and exposes three endpoints: filtered case listing by judge and year, semantic search over docket content, and detailed case retrieval with party information.

- FastAPI was chosen over Flask or Express because it provides automatic OpenAPI docs (`/docs`), async DB support out of the box, and type-validated request/response models.
- Authentication and rate-limiting are intentionally omitted for this MVP, since the API is internal and used only for evaluation. Both can be added via FastAPI dependencies later.

## Time Spent
I spent roughly 5–6 hours in total. Most of that time went into the initial schema + ingestion design, then layering in the RAG pipeline and API. I focused on building a clean MVP with production-minded patterns rather than polishing every edge case.

