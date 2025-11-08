# Legal Docket Ingestion Pipeline

## Project Summary

This pipeline ingests messy, inconsistent legal docket data from JSON files, normalizes entities (courts, judges, parties, case types), and loads it into a relational PostgreSQL schema optimized for fast legal queries. The system tracks all ingestion runs and failures reliably, storing failed records in JSONL quarantine files and structured error logs for triage and reprocessing.

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
