Technical Assessment

Legal Document Pipeline & RAG System

*Mid-Level Software Engineer --- Data Systems & AI Integration*

Overview

**Time Estimate:** 3-4 hours

**Goal:** Build a mini version of our core data pipeline---ingest messy
legal documents, structure them, and make them queryable via RAG.

The Challenge

You\'ve been given a small dataset of simulated court dockets and case
summaries. Your task is to build a basic but production-quality pipeline
that:

-   **Ingests & normalizes** messy legal data

-   **Structures it** in a relational database

-   **Makes it semantically searchable** via embeddings/RAG

-   **Exposes it** through a simple API

What We\'re Evaluating

-   **Data modeling** -- schema design, normalization, indexing strategy

-   **Data quality** -- handling messy/inconsistent input gracefully

-   **SQL proficiency** -- complex queries, performance considerations

-   **RAG implementation** -- embeddings + retrieval logic

-   **Code quality** -- structure, error handling, documentation

-   **Practical trade-offs** -- what you\'d build now vs. later at scale

Part 1: Data Ingestion & Modeling (40%)

Input Data

You\'ll receive a JSON file (raw_dockets.json) containing \~100 court
docket entries with:

> { \"case_number\": \"1:23-cv-12345\", \"court\": \"S.D.N.Y\",
> \"title\": \"Smith v. Acme Corp et al\", \"filed_date\":
> \"2023-03-15\", \"parties\": \"John Smith (plaintiff); Acme Corp, Jane
> Doe (defendants)\", \"case_type\": \"civil\", \"judge\": \"Hon. Maria
> Rodriguez\", \"docket_text\": \"Motion for summary judgment filed by
> defendant\...\", \"status\": \"active\" }

Issues in the data (intentional):

-   Inconsistent date formats (\"03/15/2023\", \"2023-03-15\", \"March
    15, 2023\")

-   Mixed party formatting (semicolons, commas, roles in parentheses vs.
    labels)

-   Typos and encoding issues (\"Hon.\" vs \"Judge\", UTF-8 issues)

-   Missing/null fields

-   Duplicate entries with slight variations

Your Task

**1. Design a PostgreSQL schema** that:

-   Normalizes parties into a separate table (with roles:
    plaintiff/defendant/etc.)

-   Handles judges, courts, and case types efficiently

-   Supports fast queries like: \"Find all cases for Judge X in 2023\"
    or \"Find all civil cases filed in S.D.N.Y. involving Acme Corp\"

-   Supports future scale (millions of dockets)

**2. Write a Python ingestion script** that:

-   Parses and cleans the messy JSON data

-   Extracts structured entities (parties, dates, judges)

-   Loads data into your schema

-   Handles duplicates and data quality issues

-   Logs anomalies/warnings

**[Deliverable:]{.underline}**

-   schema.sql (CREATE TABLE statements with indexes)

-   ingest.py (data cleaning + loading script)

-   Brief README explaining your schema choices

Part 2: Semantic Search / RAG (35%)

Your Task

**Implement a basic RAG retrieval system:**

-   Generate embeddings for docket_text field (use
    OpenAI/Anthropic/open-source model)

-   Store embeddings in a vector store of your choice: In-memory
    (FAISS/Qdrant) is fine for this exercise OR use pgvector extension
    in PostgreSQL

-   Implement semantic search: Input (natural language query) → Output
    (top 5 most relevant dockets with similarity scores)

**Example queries to handle:**

-   \"Cases involving employment discrimination in New York\"

-   \"Summary judgment motions denied in 2023\"

-   \"Disputes between corporations and individual plaintiffs\"

**[Deliverable:]{.underline}**

-   rag.py (embedding generation + retrieval logic)

-   Function: search_dockets(query: str, top_k: int = 5) -\>
    List\[Dict\]

Part 3: API Layer (25%)

Your Task

Build a **simple REST API** (Node.js/Express or Python/FastAPI) with
these endpoints:

> GET /cases?judge=\<name\>&year=\<yyyy\> → Returns cases matching
> filters (SQL query) POST /cases/search Body: {\"query\": \"employment
> discrimination\", \"limit\": 5} → Returns semantic search results
> (calls your RAG layer) GET /cases/:case_number → Returns full case
> details + all parties

**Requirements:**

-   Proper error handling (400/404/500)

-   Input validation

-   Connection pooling for database

-   Basic tests for at least one endpoint

**[Deliverable:]{.underline}**

-   API code (api.js or api.py)

-   test.http or Postman collection with example requests

-   Brief API documentation

Bonus (Optional)

Pick **ONE** to showcase depth:

**A) Query Optimization**

-   Include EXPLAIN ANALYZE output for your most complex query

-   Show indexing strategy for sub-second performance at scale

**B) Data Quality Dashboard**

-   Script that generates a report: % records with issues, common
    anomalies, missing fields

**C) Hybrid Search**

-   Combine keyword (SQL LIKE/full-text search) + semantic search with
    score fusion

**D) Incremental Updates**

-   Design approach for handling 1000s of new dockets daily without full
    re-ingestion

Submission

**IMPORTANT:** All deliverables must be submitted via a **public GitHub
repository**.

**What to send:**

-   **Public GitHub repository URL** sent to careers@ourfirm.ai

-   README.md with: Setup instructions (we should be able to run it with
    Docker/docker-compose), Architecture decisions and trade-offs, What
    you\'d improve with more time, Approximately how long you spent

-   Short Loom video (5 min) demoing your API and walking through one
    interesting technical decision

**We\'ll be looking for:**

-   Clean, production-ready code (not a hacky prototype)

-   Thoughtful data modeling

-   Practical trade-offs documented

-   Evidence you\'ve built real systems at scale

Provided Materials

We\'ll send you:

-   raw_dockets.json (sample data)

-   .env.example (API keys for embeddings if needed)

-   Docker setup template (optional)

**Questions?** Email us---we\'re happy to clarify scope.

Evaluation Rubric

  ------------------------------------------------------------------------
  **Area**                **Weight**   **What We\'re Looking For**
  ----------------------- ------------ -----------------------------------
  **Schema Design**       20%          Normalization, indexes, scalability
                                       thinking

  **Data Quality**        15%          Cleaning logic, edge case handling,
                                       validation

  **RAG Implementation**  20%          Embedding strategy, retrieval
                                       relevance, efficiency

  **SQL/Query Skills**    15%          Complex joins, optimization
                                       awareness

  **API Design**          15%          REST conventions, error handling,
                                       validation

  **Code Quality**        10%          Structure, readability, error
                                       handling

  **Communication**       5%           README clarity, design
                                       justification
  ------------------------------------------------------------------------

**Timeline:** Please submit within 5 business days. If you need more
time, just let us know.

Good luck! We\'re excited to see how you approach this. 🚀
