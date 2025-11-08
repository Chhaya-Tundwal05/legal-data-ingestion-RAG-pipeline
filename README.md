# Legal Docket Pipeline - Part 1: Data Ingestion & Modeling

This project implements Part 1 of the technical assessment: building a data ingestion pipeline for legal docket data with a normalized PostgreSQL schema.

## Overview

The pipeline ingests messy, inconsistent legal docket data from JSON files, normalizes it, and loads it into a well-structured PostgreSQL database designed for scalability.

## Schema Design

### Database Structure

The schema uses a normalized relational design with the following tables:

#### Core Tables

1. **`courts`** - Normalized court names
   - Handles variations like "S.D.N.Y" vs "S.D.N.Y."
   - Uses `normalized_name` for matching and deduplication

2. **`judges`** - Normalized judge names
   - Handles title variations ("Hon. Maria Rodriguez" vs "Judge Sarah Chen")
   - Uses `normalized_name` to match judges across different title formats

3. **`case_types`** - Case type lookup table
   - Normalizes case types (civil, criminal, employment, etc.)

4. **`cases`** - Main docket table
   - Stores core case information
   - Foreign keys to courts, judges, and case_types
   - Includes `docket_text` for full-text search (with GIN index)

5. **`parties`** - Normalized party names
   - One row per unique party name
   - Uses `normalized_name` for matching variations

6. **`case_parties`** - Junction table (many-to-many)
   - Links cases to parties with roles (plaintiff, defendant, etc.)
   - Supports multiple parties per case and multiple roles per party

### Design Decisions & Trade-offs

#### 1. Normalization Strategy

**Why normalize?**
- **Data Quality**: Handles inconsistent input (e.g., "S.D.N.Y" vs "S.D.N.Y.")
- **Storage Efficiency**: Avoids duplicate data (millions of cases share courts/judges)
- **Query Performance**: Smaller tables = faster joins
- **Maintainability**: Update court name once, affects all related cases

**Trade-off**: More joins required, but indexes make this fast

#### 2. Normalized Name Fields

Each entity table (`courts`, `judges`, `parties`) includes both:
- `name`: Original/display name
- `normalized_name`: Cleaned version for matching

**Why?**
- Preserves original data for display
- Enables fuzzy matching of variations
- Supports future deduplication logic

#### 3. Indexing Strategy

**Primary Indexes:**
- `case_number`: Unique constraint + index (most common lookup)
- `filed_date`: For date range queries ("all cases in 2023")
- Foreign keys: All FK columns indexed for join performance

**Composite Indexes:**
- `(judge_id, filed_date)`: Optimizes "cases for Judge X in year Y"
- `(court_id, case_type_id)`: Optimizes "civil cases in S.D.N.Y."
- `(party_id, role)`: Optimizes "cases where Acme Corp is defendant"

**Full-Text Search:**
- GIN index on `docket_text` for future text search capabilities

**Trade-off**: More indexes = slower writes, but essential for read-heavy workloads

#### 4. Party Normalization

**Decision**: Separate `parties` table with junction table `case_parties`

**Why?**
- Supports queries like "all cases involving Acme Corp"
- Handles many-to-many relationships (party can be in multiple cases)
- Supports role-based queries ("all cases where X is defendant")

**Alternative considered**: Store parties as JSONB array
- **Rejected** because: Harder to query, no referential integrity, harder to normalize

#### 5. NULL Handling

- `judge_id` is nullable (some cases have no assigned judge)
- All other required fields have NOT NULL constraints
- Missing dates default to 1900-01-01 (logged as warning)

**Trade-off**: Strict constraints improve data quality but require robust cleaning logic

### Scalability Considerations

1. **Serial IDs**: Using SERIAL (auto-increment) for primary keys
   - Simple and fast
   - Consider UUIDs if distributed writes needed

2. **Indexes**: Comprehensive indexing strategy
   - All foreign keys indexed
   - Composite indexes for common query patterns
   - GIN index for full-text search

3. **Partitioning Ready**: Schema supports future partitioning by:
   - `filed_date` (time-based partitioning)
   - `court_id` (geographic partitioning)

4. **Connection Pooling**: Application should use connection pooling
   - Reduces connection overhead
   - Handles concurrent requests efficiently

## Data Ingestion Script

### Features

The `ingest.py` script handles:

1. **Date Parsing**: Multiple formats
   - ISO: "2023-03-15"
   - US: "03/15/2023"
   - Written: "March 15, 2023"

2. **Party Parsing**: Handles various separators
   - Semicolons: "John (plaintiff); Acme (defendant)"
   - Commas: "John (plaintiff), Acme (defendant)"
   - Slashes: "John (plaintiff) / Acme (defendant)"

3. **Name Normalization**:
   - Removes titles ("Hon.", "Judge")
   - Normalizes whitespace
   - Case-insensitive matching

4. **Duplicate Detection**:
   - Checks `case_number` uniqueness
   - Skips duplicates with warning

5. **Error Handling**:
   - Logs all warnings and errors
   - Continues processing on individual record failures
   - Generates summary statistics

6. **Transaction Management**:
   - Commits every 100 records for performance
   - Rolls back on critical errors

### Usage

```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment variables (create .env file)
DB_HOST=localhost
DB_PORT=5432
DB_NAME=legal_dockets
DB_USER=postgres
DB_PASSWORD=postgres
JSON_FILE=raw_dockets.json

# Run ingestion
python ingest.py
```

### Output

- Logs to `ingestion.log` and console
- Summary statistics:
  - Total records processed
  - Successful insertions
  - Duplicates skipped
  - Errors and warnings

## Setup Instructions

### Prerequisites

- PostgreSQL 12+ (with pgvector extension optional for Part 2)
- Python 3.8+
- pip

### Database Setup

```sql
-- Create database
CREATE DATABASE legal_dockets;

-- Run schema
psql -d legal_dockets -f schema.sql
```

### Python Setup

```bash
# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your database credentials

# Run ingestion
python ingest.py
```

## What Would I Improve with More Time?

1. **Deduplication Logic**: 
   - Fuzzy matching for similar party names ("Acme Corp" vs "Acme Corporation")
   - Handle case number variations

2. **Data Quality Dashboard**:
   - Generate reports on data completeness
   - Identify common anomalies
   - Track data quality metrics over time

3. **Incremental Updates**:
   - Track last ingestion timestamp
   - Support delta updates instead of full re-ingestion
   - Handle updates to existing records

4. **Validation Rules**:
   - Validate case number format
   - Validate court names against known list
   - Validate date ranges (no future dates, reasonable past dates)

5. **Performance Optimizations**:
   - Batch inserts for better performance
   - Parallel processing for large files
   - Connection pooling in script

6. **Testing**:
   - Unit tests for parsing functions
   - Integration tests with test database
   - Test edge cases (malformed JSON, encoding issues)

## Architecture Decisions Summary

| Decision | Rationale | Trade-off |
|----------|-----------|-----------|
| Normalized schema | Data quality, storage efficiency | More joins, but faster with indexes |
| Normalized name fields | Handle variations, preserve originals | Extra storage, but enables matching |
| Comprehensive indexing | Fast queries at scale | Slower writes, more storage |
| Junction table for parties | Many-to-many, role support | Extra table, but flexible |
| Strict constraints | Data quality | Requires robust cleaning |

## Next Steps (Part 2 & 3)

- Part 2: Add RAG/semantic search with embeddings
- Part 3: Build REST API layer
- Consider pgvector extension for vector storage in PostgreSQL

