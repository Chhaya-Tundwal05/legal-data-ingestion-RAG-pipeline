#!/usr/bin/env python3
"""
Part 3: REST API for Legal Docket System

Endpoints:
- GET /cases?judge=<name>&year=<yyyy> - Filter cases by judge and/or year
- POST /cases/search - Semantic search over docket text (delegates to rag.search_dockets)
- GET /cases/{case_number} - Get full case details with parties

Validation: Pydantic models for request/response validation
Error handling: FastAPI exception handlers return {"error": "..."} JSON
Connection pooling: Global AsyncConnectionPool (psycopg 3) created on startup, closed on shutdown

Run: uvicorn api:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import os
import asyncio
from typing import List, Dict, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from psycopg_pool import AsyncConnectionPool
from psycopg.rows import dict_row
from psycopg import AsyncConnection

from rag import search_dockets

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@db:5432/dockets")

# Global connection pool
pool: Optional[AsyncConnectionPool] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle"""
    global pool
    # Startup: create connection pool
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        min_size=2,
        max_size=10,
        open=False,
    )
    await pool.open()
    yield
    # Shutdown: close connection pool
    await pool.close()


app = FastAPI(
    title="Legal Docket API",
    description="REST API for querying legal dockets with semantic search",
    lifespan=lifespan,
)


# Pydantic models
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Search query (min 2 characters)")
    limit: int = Field(5, ge=1, le=50, description="Number of results (1-50)")

    @field_validator("query")
    @classmethod
    def validate_query(cls, v: str) -> str:
        if len(v.strip()) < 2:
            raise ValueError("query must be at least 2 characters")
        return v.strip()


class CaseSummary(BaseModel):
    case_number: str
    title: str
    filed_date: Optional[str]
    judge: Optional[str]
    court: Optional[str]


class PartyInfo(BaseModel):
    name: str
    normalized_name: str
    role: str


class CaseDetail(BaseModel):
    case_number: str
    title: str
    filed_date: Optional[str]
    docket_text: Optional[str]
    status: Optional[str]
    judge: Optional[str]
    court: Optional[str]
    case_type: Optional[str]
    parties: List[PartyInfo]


class SearchResult(BaseModel):
    case_number: str
    title: str
    filed_date: Optional[str]
    judge: Optional[str]
    court: Optional[str]
    best_similarity: float
    best_chunk_id: int
    best_chunk_snippet: Optional[str]


# Helper functions
async def fetch_all(query: str, params: tuple = ()) -> List[Dict]:
    """Execute query and return all rows as dicts"""
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            rows = await cur.fetchall()
            return [dict(row) for row in rows]


async def fetch_one(query: str, params: tuple = ()) -> Optional[Dict]:
    """Execute query and return one row as dict, or None"""
    if not pool:
        raise HTTPException(status_code=500, detail="Database pool not initialized")
    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(query, params)
            row = await cur.fetchone()
            return dict(row) if row else None


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail}
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": f"Internal server error: {str(exc)}"}
    )


# Endpoints
@app.get("/cases", response_model=List[CaseSummary])
async def list_cases(
    judge: Optional[str] = Query(None, description="Judge normalized name (exact match)"),
    year: Optional[int] = Query(None, ge=1900, le=2100, description="Year (YYYY)")
):
    """
    List cases filtered by judge and/or year.
    
    Returns up to 200 cases ordered by filed_date DESC.
    """
    if not judge and not year:
        raise HTTPException(
            status_code=400,
            detail="At least one of 'judge' or 'year' must be provided"
        )
    
    conditions = []
    params = []
    
    if judge:
        conditions.append("j.normalized_name = LOWER(%s)")
        params.append(judge.lower())
    
    if year:
        conditions.append("EXTRACT(YEAR FROM c.filed_date) = %s")
        params.append(year)
    
    where_clause = " AND ".join(conditions)
    
    query = f"""
        SELECT 
            c.case_number,
            c.title,
            c.filed_date::text as filed_date,
            j.full_name as judge,
            co.name as court
        FROM cases c
        LEFT JOIN judges j ON c.judge_id = j.id
        LEFT JOIN courts co ON c.court_id = co.id
        WHERE {where_clause}
        ORDER BY c.filed_date DESC
        LIMIT 200
    """
    
    rows = await fetch_all(query, tuple(params))
    return [CaseSummary(**row) for row in rows]


@app.post("/cases/search", response_model=List[SearchResult])
async def search_cases(request: SearchRequest):
    """
    Semantic search over docket text.
    
    Delegates to rag.search_dockets() for vector similarity search.
    """
    # Run synchronous search_dockets in thread pool to avoid blocking
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        search_dockets,
        request.query,
        request.limit
    )
    
    return [SearchResult(**result) for result in results]


@app.get("/cases/{case_number}", response_model=CaseDetail)
async def get_case(case_number: str):
    """
    Get full case details including all parties.
    
    Returns 404 if case not found.
    """
    # Get case details
    case_query = """
        SELECT 
            c.case_number,
            c.title,
            c.filed_date::text as filed_date,
            c.docket_text,
            c.status,
            j.full_name as judge,
            co.name as court,
            ct.name as case_type
        FROM cases c
        LEFT JOIN judges j ON c.judge_id = j.id
        LEFT JOIN courts co ON c.court_id = co.id
        LEFT JOIN case_types ct ON c.case_type_id = ct.id
        WHERE c.case_number = %s
    """
    
    case = await fetch_one(case_query, (case_number,))
    
    if not case:
        raise HTTPException(status_code=404, detail=f"Case {case_number} not found")
    
    # Get parties
    parties_query = """
        SELECT 
            p.name,
            p.normalized_name,
            cp.role
        FROM case_parties cp
        JOIN parties p ON cp.party_id = p.id
        JOIN cases c ON cp.case_id = c.id
        WHERE c.case_number = %s
        ORDER BY cp.role, p.name
    """
    
    parties_rows = await fetch_all(parties_query, (case_number,))
    parties = [PartyInfo(**dict(row)) for row in parties_rows]
    
    case_dict = dict(case)
    case_dict["parties"] = parties
    
    return CaseDetail(**case_dict)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "ok", "pool": "open" if pool and pool.get_stats() else "closed"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)

