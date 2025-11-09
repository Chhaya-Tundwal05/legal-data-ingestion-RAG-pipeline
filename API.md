# Legal Docket REST API

## Overview

The Legal Docket REST API provides programmatic access to case data and semantic search capabilities over docket text. The API exposes three endpoints: filtered case listing by judge and year, semantic search over docket content using RAG (Retrieval-Augmented Generation), and detailed case retrieval with party information.

The stack consists of FastAPI for the web framework, psycopg3 with async connection pooling for database access, PostgreSQL with pgvector extension for vector similarity search, and SentenceTransformers for generating embeddings. Semantic search is implemented via the RAG layer (`rag.py`) which uses chunked embeddings stored in `case_chunk_embeddings` and queried using approximate nearest neighbor (ANN) search.

## Base URL & Running the API

**Base URL:** `http://localhost:8000`

**Run the API server:**

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --reload
```

The API reads the database connection string from the `DATABASE_URL` environment variable, defaulting to `postgresql://postgres:postgres@db:5432/dockets` if not set.

**Interactive API Documentation:**

- **Swagger UI:** `GET /docs` - Interactive API explorer with request/response examples
- **OpenAPI Schema:** `GET /openapi.json` - Machine-readable API specification

## Prerequisites

1. **Database Schema:** The ingest schema (`schema.sql`) must be applied. In Docker Compose, this runs automatically on first database initialization.

2. **Case Data:** Cases must be loaded via `ingest.py` before querying:
   ```bash
   python ingest.py --file raw_dockets.json
   ```

3. **Embeddings:** For semantic search (`POST /cases/search`) to work, embeddings must be generated:
   ```bash
   python rag.py backfill
   ```

4. **pgvector Extension:** The PostgreSQL database must have the `vector` extension enabled. This is handled automatically by the `pgvector/pgvector:pg15` Docker image or can be enabled manually with `CREATE EXTENSION vector;`.

## Authentication

**No authentication is implemented in this MVP.** All endpoints are publicly accessible. Authentication and authorization should be added for production deployments.

## Error Model

All error responses follow a consistent JSON structure:

```json
{
  "error": "Error message describing what went wrong"
}
```

**Common HTTP status codes:**

- **400 Bad Request:** Invalid input (e.g., search query too short, invalid year range, missing required parameters)
- **404 Not Found:** Case not found (e.g., invalid `case_number` in `GET /cases/{case_number}`)
- **500 Internal Server Error:** Database errors, search failures, or unexpected exceptions

## Endpoints

### 6.1 GET /cases

**Description:** Returns cases filtered by judge (exact match on `judges.normalized_name`) and/or by filed year. Results are ordered by `filed_date` descending and limited to 200 records.

**Query Parameters:**

- `judge` (string, optional) - Matched against `judges.normalized_name` (lowercased during ingest). Exact match required.
- `year` (integer, optional, range: 1900-2100) - Filters by `EXTRACT(YEAR FROM filed_date)`

**Request:** At least one of `judge` or `year` must be provided.

**Response 200 (application/json):**

Array of case summary objects:

```json
[
  {
    "case_number": "CASE-000123",
    "title": "Smith v. Acme Corporation",
    "filed_date": "2023-05-15",
    "judge": "Maria Rodriguez",
    "court": "Southern District of New York"
  }
]
```

**Example Requests:**

```bash
# Filter by judge and year
curl "http://localhost:8000/cases?judge=maria%20rodriguez&year=2023"

# Filter by year only
curl "http://localhost:8000/cases?year=2024"
```

**Errors:**

- **400:** Neither `judge` nor `year` provided
- **500:** Database connection or query failure

---

### 6.2 POST /cases/search

**Description:** Semantic search over `docket_text` using the RAG layer (pgvector + chunk embeddings). Delegates to `rag.search_dockets()` for vector similarity search. Returns top-K cases ranked by best chunk similarity score.

**Request Body (application/json):**

```json
{
  "query": "employment discrimination in New York",
  "limit": 5
}
```

**Body Parameters:**

- `query` (string, required, minimum length: 2) - Natural language search query
- `limit` (integer, optional, range: 1-50, default: 5) - Number of results to return

**Response 200 (application/json):**

Array of search result objects:

```json
[
  {
    "case_number": "CASE-000123",
    "title": "Smith v. Acme Corporation",
    "filed_date": "2023-05-15",
    "judge": "Maria Rodriguez",
    "court": "Southern District of New York",
    "best_similarity": 0.9123,
    "best_chunk_id": 3,
    "best_chunk_snippet": "... first ~280 characters of the matching chunk ..."
  }
]
```

**Example Request:**

```bash
curl -X POST http://localhost:8000/cases/search \
  -H "Content-Type: application/json" \
  -d '{"query":"Summary judgment motions denied in 2023","limit":5}'
```

**Notes:**

- Requires prior execution of `python rag.py backfill` to generate embeddings
- Search uses cosine similarity over chunked embeddings (default: 1200 chars per chunk, 200 char overlap)
- Results are aggregated by case, returning the best matching chunk per case

**Errors:**

- **400:** Invalid request body (query too short, limit out of range)
- **500:** Search execution failure, embedding generation error, or database error

---

### 6.3 GET /cases/{case_number}

**Description:** Returns full case details including all parties with their roles. Provides complete case metadata from the `cases` table joined with related entities (judge, court, case type) and all associated parties.

**Path Parameters:**

- `case_number` (string, required) - Unique case identifier

**Response 200 (application/json):**

```json
{
  "case_number": "CASE-000123",
  "title": "Smith v. Acme Corporation",
  "filed_date": "2023-05-15",
  "docket_text": "Full docket text content...",
  "status": "open",
  "judge": "Maria Rodriguez",
  "court": "Southern District of New York",
  "case_type": "civil",
  "parties": [
    {
      "name": "Acme Corp",
      "normalized_name": "acme corp",
      "role": "plaintiff"
    },
    {
      "name": "John Doe",
      "normalized_name": "john doe",
      "role": "defendant"
    }
  ]
}
```

**Example Request:**

```bash
curl "http://localhost:8000/cases/CASE-000123"
```

**Errors:**

- **404:** Case not found
- **500:** Database query failure

---

## Validation Rules

**POST /cases/search:**
- `query` must be at least 2 characters (after trimming)
- `limit` must be between 1 and 50 (inclusive)

**GET /cases:**
- `year` must be between 1900 and 2100 (inclusive)
- `judge` is matched against `judges.normalized_name` (lowercased during ingest, exact match)
- At least one of `judge` or `year` must be provided

**Error Responses:**
- All errors return JSON body: `{"error": "message"}`
- HTTP status codes indicate error category (400, 404, 500)

---

## Performance Notes

**Connection Pooling:**
- Database access uses psycopg3 `AsyncConnectionPool` for efficient connection management
- Pool configuration: minimum 2 connections, maximum 10 connections (configurable via environment variables)
- Connections are created on application startup and closed on shutdown

**Vector Search Performance:**
- ANN search uses pgvector `IVFFLAT` index with cosine distance operator (`<=>`)
- Index tuning parameters:
  - `lists`: Number of clusters (default: 100, set during index creation)
  - `ivfflat.probes`: Number of clusters to search per query (default: 10, configurable via `IVFFLAT_PROBES` environment variable)
- Higher `probes` values improve recall at the cost of query latency

**Future Optimizations:**
- Add optional SQL filters to `/cases/search` (e.g., `year`, `court`, `case_type`) for hybrid ranking
- Implement pagination for list endpoints
- Consider HNSW index type when available in pgvector for better query performance

---

## Example Requests File

The repository includes `test.http` for quick local testing with REST client extensions (VS Code REST Client, JetBrains HTTP Client).

**To execute:**

1. Install REST Client extension in VS Code or use JetBrains built-in HTTP client
2. Open `test.http`
3. Click "Send Request" above each request block

**Example requests included:**
- List cases by judge and year
- List cases by year only
- Get case details by case number
- Three semantic search examples with different queries

---

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | `postgresql://postgres:postgres@db:5432/dockets` | PostgreSQL connection string |
| `DB_POOL_MIN` | 2 | Minimum connection pool size |
| `DB_POOL_MAX` | 10 | Maximum connection pool size |
| `DB_POOL_TIMEOUT` | 10 | Pool wait timeout (seconds) |
| `VECTOR_DIM` | 384 | Embedding dimension (MiniLM-L6-v2) |
| `CHUNK_SIZE` | 1200 | Character chunk size for embeddings |
| `CHUNK_OVERLAP` | 200 | Character overlap between chunks |
| `IVFFLAT_PROBES` | 10 | Number of clusters to search per query |

**Note:** The API currently uses hardcoded pool defaults. Environment variable support for pool configuration can be added in future versions.

---

## Change Log / Future Work

**Future Enhancements:**

- **Authentication & Authorization:** Add API key or OAuth2 authentication
- **Rate Limiting:** Implement request rate limits per client/IP
- **Enhanced Search Filters:** Add optional SQL filters to `/cases/search` (year, court, case_type) for hybrid ranking
- **Hybrid Search:** Combine keyword search (BM25/FTS) with vector similarity for improved precision
- **Pagination:** Add pagination support to list endpoints (`GET /cases`)
- **Caching:** Implement response caching for frequently accessed cases
- **Async Embedding:** Optimize embedding generation with async batch processing
- **Model Swapping:** Support dynamic embedding model selection via environment variables

