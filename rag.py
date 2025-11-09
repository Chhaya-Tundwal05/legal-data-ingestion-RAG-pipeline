#!/usr/bin/env python3
"""
Part 2: RAG over docket_text with pgvector + sentence-transformers

Scaling Notes:
- Model swap: set HF_EMBED_MODEL + VECTOR_DIM; recreate case_chunk_embeddings with new dim.
- Index tuning: increase ivfflat lists; set SET LOCAL ivfflat.probes on queries; consider HNSW when available.
- Chunking: adjust CHUNK_SIZE/CHUNK_OVERLAP; move to token-based chunking if long docs.
- Data volume: partition or shard case_chunk_embeddings; keep PK (case_number, chunk_id).
- External store: swap to Qdrant/Milvus, keep search_dockets API stable.
- Hybrid: combine FTS (to_tsvector) with vector similarity for precision.
"""

from __future__ import annotations

import os
import math
from typing import List, Dict, Tuple
from datetime import datetime
import psycopg2
from psycopg2.rows import dict_row
from sentence_transformers import SentenceTransformer

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@db:5432/dockets")
HF_EMBED_MODEL = os.environ.get("HF_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
VECTOR_DIM = int(os.environ.get("VECTOR_DIM", "384"))  # MiniLM-L6-v2
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "1200"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "200"))
TOP_SNIPPET_CHARS = int(os.environ.get("TOP_SNIPPET_CHARS", "280"))

_model = None

def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(HF_EMBED_MODEL)
    return _model

def embed_texts(texts: List[str]) -> List[List[float]]:
    """Generate unit-normalized embeddings"""
    return get_model().encode(texts, normalize_embeddings=True).tolist()

def chunk_text(s: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[Tuple[int, str]]:
    """
    Split text into overlapping character chunks.
    
    Returns:
        List of (chunk_id, chunk_text) tuples
    """
    if not s:
        return []
    
    size = max(1, size)
    overlap = max(0, min(overlap, size - 1))
    chunks, i, cid = [], 0, 0
    n = len(s)
    
    while i < n:
        end = min(n, i + size)
        chunk_text = s[i:end].strip()
        if chunk_text:  # Skip empty chunks
            chunks.append((cid, chunk_text))
            cid += 1
        if end == n:
            break
        i = end - overlap
    
    return chunks

DDL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS case_chunk_embeddings (
  case_number   TEXT REFERENCES cases(case_number) ON DELETE CASCADE,
  chunk_id      INT,
  chunk_text    TEXT,
  embedding     vector({dim}),
  updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (case_number, chunk_id)
);

CREATE INDEX IF NOT EXISTS idx_case_chunk_embeddings_cosine
  ON case_chunk_embeddings USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
"""

def ensure_schema(conn: psycopg.Connection, dim: int = VECTOR_DIM) -> None:
    """Ensure pgvector extension and embedding table exist"""
    with conn.cursor() as cur:
        cur.execute(DDL.format(dim=dim))
    conn.commit()

def _cases_missing_any_chunks(conn: psycopg.Connection, limit: int = 1000) -> List[Dict]:
    """Find cases that don't have any chunks yet"""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("""
        SELECT c.case_number, COALESCE(c.docket_text, '') AS docket_text
        FROM cases c
        LEFT JOIN case_chunk_embeddings e
          ON e.case_number = c.case_number
        WHERE e.case_number IS NULL
        LIMIT %s
        """, (limit,))
        return list(cur.fetchall())

def _upsert_case_chunks(conn: psycopg.Connection, case_number: str, chunks: List[Tuple[int, str]], embeds: List[List[float]]) -> None:
    """Upsert chunks and embeddings for a case"""
    with conn.cursor() as cur:
        for (cid, text), vec in zip(chunks, embeds):
            cur.execute("""
            INSERT INTO case_chunk_embeddings (case_number, chunk_id, chunk_text, embedding, updated_at)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            ON CONFLICT (case_number, chunk_id) DO UPDATE
            SET chunk_text = EXCLUDED.chunk_text,
                embedding  = EXCLUDED.embedding,
                updated_at = EXCLUDED.updated_at
            """, (case_number, cid, text, vec))
        conn.commit()

def backfill_chunk_embeddings(batch_size: int = 128) -> int:
    """
    Backfill embeddings for all cases missing chunks.
    
    Args:
        batch_size: Number of cases to process per batch
        
    Returns:
        Total number of chunks embedded
    """
    total_chunks = 0
    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn, VECTOR_DIM)
        
        while True:
            rows = _cases_missing_any_chunks(conn, limit=batch_size)
            if not rows:
                break
            
            for r in rows:
                text = r["docket_text"] or ""
                chunks = chunk_text(text, CHUNK_SIZE, CHUNK_OVERLAP)
                
                if not chunks:
                    # Insert a single empty chunk so we don't repeatedly select it
                    chunks = [(0, "")]
                
                embeds = embed_texts([c[1] for c in chunks])
                _upsert_case_chunks(conn, r["case_number"], chunks, embeds)
                total_chunks += len(chunks)
    
    return total_chunks

def search_dockets(query: str, top_k: int = 5) -> List[Dict]:
    """
    Semantic search over docket_text using cosine similarity.
    
    Args:
        query: Natural language search query
        top_k: Number of cases to return
        
    Returns:
        List of dicts with case metadata and best matching chunk
    """
    assert query and isinstance(query, str)
    
    qvec = embed_texts([query])[0]  # unit-normalized
    
    with psycopg.connect(DATABASE_URL) as conn:
        ensure_schema(conn, VECTOR_DIM)
        
        # Retrieve top N chunks, then aggregate to top-k cases by best chunk similarity
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("""
            WITH q AS (SELECT %s::vector AS v)
            SELECT
              e.case_number,
              e.chunk_id,
              LEFT(e.chunk_text, %s) AS snippet,
              1 - (e.embedding <=> q.v) AS similarity,
              c.title,
              c.filed_date,
              j.full_name AS judge,
              co.name AS court
            FROM case_chunk_embeddings e
            JOIN cases c        ON c.case_number = e.case_number
            LEFT JOIN judges j  ON j.id = c.judge_id
            LEFT JOIN courts co ON co.id = c.court_id, q
            ORDER BY e.embedding <=> q.v
            LIMIT %s
            """, (qvec, TOP_SNIPPET_CHARS, max(top_k * 10, 50)))
            
            chunk_rows = list(cur.fetchall())
    
    # Aggregate by case: take best chunk per case_number
    best_by_case: Dict[str, Dict] = {}
    for r in chunk_rows:
        key = r["case_number"]
        sim = float(r["similarity"])
        
        if key not in best_by_case or sim > best_by_case[key]["best_similarity"]:
            best_by_case[key] = {
                "case_number": key,
                "title": r["title"],
                "filed_date": str(r["filed_date"]) if r["filed_date"] else None,
                "judge": r["judge"],
                "court": r["court"],
                "best_similarity": round(sim, 4),
                "best_chunk_id": r["chunk_id"],
                "best_chunk_snippet": r["snippet"],
            }
    
    # Sort by best_similarity desc and take top_k
    results = sorted(best_by_case.values(), key=lambda x: x["best_similarity"], reverse=True)[:top_k]
    return results

if __name__ == "__main__":
    import argparse
    import json
    
    ap = argparse.ArgumentParser(description="RAG over docket_text (pgvector + MiniLM L6 v2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    
    p1 = sub.add_parser("backfill", help="Backfill embeddings for cases lacking chunks")
    p1.add_argument("--batch-size", type=int, default=128)
    
    p2 = sub.add_parser("search", help="Semantic search over docket_text")
    p2.add_argument("--q", required=True, help="Search query")
    p2.add_argument("--k", type=int, default=5, help="Number of results")
    
    args = ap.parse_args()
    
    if args.cmd == "backfill":
        n = backfill_chunk_embeddings(batch_size=args.batch_size)
        print(json.dumps({"backfilled_chunks": n, "ts": datetime.utcnow().isoformat() + "Z"}, indent=2))
    elif args.cmd == "search":
        out = search_dockets(args.q, args.k)
        print(json.dumps(out, indent=2, default=str))
    else:
        ap.print_help()

