-- Legal Docket Database Schema
-- Designed for scalability (millions of dockets)

-- Enable pgvector extension for embeddings (Part 2)
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable UUID extension for primary keys (optional, using serial for simplicity)
-- CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Courts table (normalized to handle variations like "S.D.N.Y" vs "S.D.N.Y.")
CREATE TABLE courts (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    normalized_name VARCHAR(100) NOT NULL, -- Normalized version for matching
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Judges table (normalized to handle "Hon. Maria Rodriguez" vs "Judge Sarah Chen")
CREATE TABLE judges (
    id SERIAL PRIMARY KEY,
    full_name VARCHAR(200) NOT NULL,
    normalized_name VARCHAR(200) NOT NULL, -- Normalized version (removes "Hon.", "Judge", etc.)
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Case types table (normalized)
CREATE TABLE case_types (
    id SERIAL PRIMARY KEY,
    name VARCHAR(50) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Cases table (main table)
CREATE TABLE cases (
    id SERIAL PRIMARY KEY,
    case_number VARCHAR(50) NOT NULL UNIQUE, -- Unique constraint to prevent duplicates
    court_id INTEGER NOT NULL REFERENCES courts(id) ON DELETE RESTRICT,
    title VARCHAR(500) NOT NULL,
    filed_date DATE NOT NULL,
    case_type_id INTEGER NOT NULL REFERENCES case_types(id) ON DELETE RESTRICT,
    judge_id INTEGER REFERENCES judges(id) ON DELETE SET NULL, -- NULL allowed (some cases have no judge)
    docket_text TEXT,
    status VARCHAR(20) NOT NULL CHECK (status IN ('active', 'closed', 'pending', 'dismissed')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Parties table (normalized - one row per unique party name)
CREATE TABLE parties (
    id SERIAL PRIMARY KEY,
    name VARCHAR(500) NOT NULL,
    normalized_name VARCHAR(500) NOT NULL, -- Normalized for matching variations
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Case-Party junction table (many-to-many with roles)
CREATE TABLE case_parties (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    role VARCHAR(50) NOT NULL CHECK (role IN ('plaintiff', 'defendant', 'third_party', 'intervenor', 'other')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(case_id, party_id, role) -- Prevent duplicate party-role assignments
);

-- Name variations tables to track all seen forms
CREATE TABLE court_name_variations (
    id SERIAL PRIMARY KEY,
    court_id INTEGER NOT NULL REFERENCES courts(id) ON DELETE CASCADE,
    raw_name VARCHAR(100) NOT NULL,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seen_count INT NOT NULL DEFAULT 1,
    UNIQUE(court_id, raw_name) -- Prevent duplicate variations
);

CREATE TABLE judge_name_variations (
    id SERIAL PRIMARY KEY,
    judge_id INTEGER NOT NULL REFERENCES judges(id) ON DELETE CASCADE,
    raw_name VARCHAR(200) NOT NULL,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seen_count INT NOT NULL DEFAULT 1,
    UNIQUE(judge_id, raw_name) -- Prevent duplicate variations
);

CREATE TABLE party_name_variations (
    id SERIAL PRIMARY KEY,
    party_id INTEGER NOT NULL REFERENCES parties(id) ON DELETE CASCADE,
    raw_name VARCHAR(500) NOT NULL,
    first_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    seen_count INT NOT NULL DEFAULT 1,
    UNIQUE(party_id, raw_name) -- Prevent duplicate variations
);

-- Indexes for performance optimization
-- Case lookups by case_number (most common query)
CREATE INDEX idx_cases_case_number ON cases(case_number);

-- Date range queries (e.g., "Find all cases in 2023")
CREATE INDEX idx_cases_filed_date ON cases(filed_date);

-- Judge queries (e.g., "Find all cases for Judge X")
CREATE INDEX idx_cases_judge_id ON cases(judge_id);

-- Court queries (e.g., "Find all cases in S.D.N.Y.")
CREATE INDEX idx_cases_court_id ON cases(court_id);

-- Case type queries
CREATE INDEX idx_cases_case_type_id ON cases(case_type_id);

-- Status queries
CREATE INDEX idx_cases_status ON cases(status);

-- Composite index for common query pattern: judge + year
CREATE INDEX idx_cases_judge_date ON cases(judge_id, filed_date);

-- Composite index for common query pattern: court + case_type
CREATE INDEX idx_cases_court_type ON cases(court_id, case_type_id);

-- Party lookups
CREATE INDEX idx_parties_normalized_name ON parties(normalized_name);

-- Case-party lookups (find all cases for a party)
CREATE INDEX idx_case_parties_party_id ON case_parties(party_id);

-- Case-party lookups (find all parties for a case)
CREATE INDEX idx_case_parties_case_id ON case_parties(case_id);

-- Role-based queries (e.g., "Find all cases where Acme Corp is defendant")
CREATE INDEX idx_case_parties_role ON case_parties(role);

-- Composite index for party + role queries
CREATE INDEX idx_case_parties_party_role ON case_parties(party_id, role);

-- Full-text search on docket_text (for future use)
CREATE INDEX idx_cases_docket_text_gin ON cases USING gin(to_tsvector('english', docket_text));

-- Court and judge normalized name lookups
CREATE INDEX idx_courts_normalized_name ON courts(normalized_name);
CREATE INDEX idx_judges_normalized_name ON judges(normalized_name);

-- Indexes for name variations tables
CREATE INDEX idx_court_name_variations_court_id ON court_name_variations(court_id);
CREATE INDEX idx_court_name_variations_raw_name ON court_name_variations(raw_name);
CREATE INDEX idx_judge_name_variations_judge_id ON judge_name_variations(judge_id);
CREATE INDEX idx_judge_name_variations_raw_name ON judge_name_variations(raw_name);
CREATE INDEX idx_party_name_variations_party_id ON party_name_variations(party_id);
CREATE INDEX idx_party_name_variations_raw_name ON party_name_variations(raw_name);

-- Updated_at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Triggers to auto-update updated_at
CREATE TRIGGER update_courts_updated_at BEFORE UPDATE ON courts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_judges_updated_at BEFORE UPDATE ON judges
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_cases_updated_at BEFORE UPDATE ON cases
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_parties_updated_at BEFORE UPDATE ON parties
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ===== Ingest tracking (append-only) =====

CREATE TABLE IF NOT EXISTS ingest_runs (
  run_id           BIGSERIAL PRIMARY KEY,
  source_name      TEXT NOT NULL,
  source_uri       TEXT,
  started_at       TIMESTAMP NOT NULL DEFAULT now(),
  finished_at      TIMESTAMP,
  total_read       INT NOT NULL DEFAULT 0,
  total_inserted   INT NOT NULL DEFAULT 0,
  total_updated    INT NOT NULL DEFAULT 0,
  total_failed     INT NOT NULL DEFAULT 0,
  notes            TEXT
);

CREATE TABLE IF NOT EXISTS ingest_errors (
  error_id         BIGSERIAL PRIMARY KEY,
  run_id           BIGINT NOT NULL REFERENCES ingest_runs(run_id) ON DELETE CASCADE,
  record_hash      TEXT,            -- sha256 of the raw record (for dedupe)
  case_number      TEXT,            -- optional for quick filtering
  error_code       TEXT NOT NULL,   -- e.g. BAD_DATE, STATUS_UNMAPPED, FK_CASE_TYPE
  error_message    TEXT,            -- short human-readable message
  details          JSONB,           -- { raw, normalized_attempt, context, why, suggestion }
  first_seen_at    TIMESTAMP NOT NULL DEFAULT now(),
  last_seen_at     TIMESTAMP NOT NULL DEFAULT now(),
  retry_count      INT NOT NULL DEFAULT 0,
  resolved         BOOLEAN NOT NULL DEFAULT FALSE,
  resolver_note    TEXT
);

-- Helpful indexes for triage and dashboards
CREATE INDEX IF NOT EXISTS idx_ingest_errors_run_id       ON ingest_errors (run_id);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_error_code   ON ingest_errors (error_code);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_case_number  ON ingest_errors (case_number);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_resolved     ON ingest_errors (resolved);
CREATE INDEX IF NOT EXISTS idx_ingest_errors_record_hash  ON ingest_errors (record_hash);

-- Enforce one canonical row per normalized entity
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'u_courts_normalized_name'
    ) THEN
        ALTER TABLE courts
            ADD CONSTRAINT u_courts_normalized_name UNIQUE (normalized_name);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'u_judges_normalized_name'
    ) THEN
        ALTER TABLE judges
            ADD CONSTRAINT u_judges_normalized_name UNIQUE (normalized_name);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint 
        WHERE conname = 'u_parties_normalized_name'
    ) THEN
        ALTER TABLE parties
            ADD CONSTRAINT u_parties_normalized_name UNIQUE (normalized_name);
    END IF;
END $$;

