# Step-by-Step Testing Guide

This guide walks you through testing the entire legal docket ingestion pipeline.

## Prerequisites

- PostgreSQL 12+ installed and running
- Python 3.8+ installed
- `pip` package manager
- Access to terminal/command line

## Step 1: Install Dependencies

```bash
# Navigate to project directory
cd "/Users/icg/Downloads/OurFirm Assesment"

# Install Python dependencies
pip install -r requirements.txt
```

**Expected output:** Dependencies installed successfully (psycopg2-binary, python-dotenv)

---

## Step 2: Set Up PostgreSQL Database

### 2.1 Start PostgreSQL Service

```bash
# On macOS (if using Homebrew)
brew services start postgresql

# On Linux
sudo systemctl start postgresql

# Or use your system's PostgreSQL service manager
```

### 2.2 Create Database

```bash
# Connect to PostgreSQL (adjust user if needed)
psql -U postgres

# In psql prompt, create database
CREATE DATABASE legal_dockets;

# Exit psql
\q
```

**Expected output:** Database `legal_dockets` created successfully

---

## Step 3: Create Database Schema

```bash
# Run schema.sql to create all tables
psql -U postgres -d legal_dockets -f schema.sql
```

**Expected output:** 
- All tables created
- Indexes created
- Triggers created
- Constraints added

**Verify schema:**
```bash
psql -U postgres -d legal_dockets -c "\dt"
```

You should see tables: courts, judges, case_types, cases, parties, case_parties, court_name_variations, judge_name_variations, party_name_variations, ingest_runs, ingest_errors

---

## Step 4: Configure Environment Variables

### 4.1 Create .env File

```bash
# Create .env file in project directory
cat > .env << EOF
DB_HOST=localhost
DB_PORT=5432
DB_NAME=legal_dockets
DB_USER=postgres
DB_PASSWORD=postgres
JSON_FILE=raw_dockets.json
QUARANTINE_DIR=quarantine
EOF
```

**Note:** Adjust `DB_PASSWORD` and `DB_USER` to match your PostgreSQL setup.

### 4.2 Verify .env File

```bash
cat .env
```

**Expected output:** All environment variables listed

---

## Step 5: Run Initial Ingestion Test

### 5.1 Run the Ingestion Script

```bash
python ingest.py
```

**Expected output:**
- Connection to database successful
- Started ingestion run X
- Processing records...
- JSON summary printed at the end

**Example output:**
```json
{
  "run_id": 1,
  "summary": {
    "read": 100,
    "inserted": 85,
    "updated": 0,
    "failed": 15
  }
}
```

### 5.2 Check Logs

```bash
# Check ingestion log
cat ingestion.log | tail -50
```

**Expected:** Log entries showing processing progress, warnings, and errors

---

## Step 6: Verify Data Ingestion

### 6.1 Check Ingest Run Record

```bash
psql -U postgres -d legal_dockets -c "SELECT * FROM ingest_runs ORDER BY run_id DESC LIMIT 1;"
```

**Expected:** One row with run_id, source_name, totals, timestamps

### 6.2 Check Cases Table

```bash
psql -U postgres -d legal_dockets -c "SELECT COUNT(*) as total_cases FROM cases;"
psql -U postgres -d legal_dockets -c "SELECT case_number, title, status FROM cases LIMIT 5;"
```

**Expected:** Cases inserted with proper data

### 6.3 Check Courts Table

```bash
psql -U postgres -d legal_dockets -c "SELECT id, name, normalized_name FROM courts LIMIT 10;"
```

**Expected:** Courts with both raw and normalized names

### 6.4 Check Court Name Variations

```bash
psql -U postgres -d legal_dockets -c "
SELECT c.name as canonical_name, cnv.raw_name, cnv.seen_count 
FROM courts c 
JOIN court_name_variations cnv ON c.id = cnv.court_id 
ORDER BY c.id, cnv.seen_count DESC 
LIMIT 10;
"
```

**Expected:** Multiple variations for courts (e.g., "S.D.N.Y" and "S.D.N.Y.")

### 6.5 Check Judges Table

```bash
psql -U postgres -d legal_dockets -c "SELECT id, full_name, normalized_name FROM judges LIMIT 10;"
```

**Expected:** Judges with both raw and normalized names

### 6.6 Check Judge Name Variations

```bash
psql -U postgres -d legal_dockets -c "
SELECT j.full_name as canonical_name, jnv.raw_name, jnv.seen_count 
FROM judges j 
JOIN judge_name_variations jnv ON j.id = jnv.judge_id 
ORDER BY j.id, jnv.seen_count DESC 
LIMIT 10;
"
```

**Expected:** Multiple variations for judges (e.g., "Hon. Maria Rodriguez" and "Judge Maria Rodriguez")

### 6.7 Check Parties Table

```bash
psql -U postgres -d legal_dockets -c "SELECT COUNT(*) as total_parties FROM parties;"
psql -U postgres -d legal_dockets -c "SELECT id, name, normalized_name FROM parties LIMIT 10;"
```

**Expected:** Parties with both raw and normalized names

### 6.8 Check Party Name Variations

```bash
psql -U postgres -d legal_dockets -c "
SELECT p.name as canonical_name, pnv.raw_name, pnv.seen_count 
FROM parties p 
JOIN party_name_variations pnv ON p.id = pnv.party_id 
ORDER BY p.id, pnv.seen_count DESC 
LIMIT 10;
"
```

**Expected:** Multiple variations for parties

### 6.9 Check Case-Party Relationships

```bash
psql -U postgres -d legal_dockets -c "
SELECT c.case_number, p.name as party_name, cp.role 
FROM cases c 
JOIN case_parties cp ON c.id = cp.case_id 
JOIN parties p ON cp.party_id = p.id 
LIMIT 10;
"
```

**Expected:** Cases linked to parties with roles

---

## Step 7: Test Error Handling

### 7.1 Check Failed Records

```bash
psql -U postgres -d legal_dockets -c "
SELECT error_code, COUNT(*) as count 
FROM ingest_errors 
GROUP BY error_code 
ORDER BY count DESC;
"
```

**Expected:** Error codes and counts (e.g., BAD_DATE, MISSING_CASE_NUMBER)

### 7.2 Check Quarantine File

```bash
# List quarantine files
ls -lh quarantine/

# View quarantine file (if exists)
cat quarantine/ingest_run_1.jsonl | head -5
```

**Expected:** JSONL file with failed records, each line containing error details

### 7.3 View Sample Error Details

```bash
psql -U postgres -d legal_dockets -c "
SELECT error_code, error_message, case_number, retry_count 
FROM ingest_errors 
LIMIT 5;
"
```

**Expected:** Error details with codes and messages

---

## Step 8: Test Upsert Functionality

### 8.1 Run Ingestion Again (Should Update Existing Cases)

```bash
python ingest.py
```

**Expected output:**
- New run_id created
- `updated` count > 0 (cases that already existed)
- `inserted` count for new cases
- `failed` count for bad records

### 8.2 Verify Updates

```bash
psql -U postgres -d legal_dockets -c "
SELECT run_id, total_inserted, total_updated, total_failed 
FROM ingest_runs 
ORDER BY run_id DESC 
LIMIT 2;
"
```

**Expected:** Second run shows `total_updated > 0`

### 8.3 Check Updated Timestamps

```bash
psql -U postgres -d legal_dockets -c "
SELECT case_number, created_at, updated_at 
FROM cases 
WHERE updated_at > created_at 
LIMIT 5;
"
```

**Expected:** Cases with `updated_at` later than `created_at`

---

## Step 9: Test Normalized Name Uniqueness

### 9.1 Verify Unique Constraints

```bash
# Try to insert duplicate normalized name (should fail)
psql -U postgres -d legal_dockets -c "
INSERT INTO courts (name, normalized_name) 
VALUES ('Test Court', 'SDNY');
"
```

**Expected:** Error if a court with normalized_name='SDNY' already exists

### 9.2 Check Constraint Names

```bash
psql -U postgres -d legal_dockets -c "
SELECT conname, contype 
FROM pg_constraint 
WHERE conrelid IN (
    'courts'::regclass,
    'judges'::regclass,
    'parties'::regclass
) 
AND conname LIKE 'u_%normalized_name';
"
```

**Expected:** Three unique constraints listed

---

## Step 10: Test Complex Queries

### 10.1 Find Cases by Judge

```bash
psql -U postgres -d legal_dockets -c "
SELECT c.case_number, c.title, j.full_name as judge
FROM cases c
JOIN judges j ON c.judge_id = j.id
WHERE j.normalized_name = 'maria rodriguez'
LIMIT 5;
"
```

**Expected:** Cases for the specified judge (works even if judge name has variations)

### 10.2 Find Cases by Court and Year

```bash
psql -U postgres -d legal_dockets -c "
SELECT c.case_number, c.title, co.name as court, c.filed_date
FROM cases c
JOIN courts co ON c.court_id = co.id
WHERE co.normalized_name = 'SDNY'
AND EXTRACT(YEAR FROM c.filed_date) = 2023
LIMIT 5;
"
```

**Expected:** Cases in S.D.N.Y. filed in 2023

### 10.3 Find Cases by Party Role

```bash
psql -U postgres -d legal_dockets -c "
SELECT c.case_number, p.name as party_name, cp.role
FROM cases c
JOIN case_parties cp ON c.id = cp.case_id
JOIN parties p ON cp.party_id = p.id
WHERE cp.role = 'defendant'
LIMIT 5;
"
```

**Expected:** Cases with defendants

---

## Step 11: Test Edge Cases

### 11.1 Test with Bad Date

Create a test file with a bad date:

```bash
cat > test_bad_date.json << EOF
[
  {
    "case_number": "TEST-001",
    "court": "S.D.N.Y",
    "title": "Test Case",
    "filed_date": "INVALID-DATE",
    "parties": "Test Party (plaintiff)",
    "case_type": "civil",
    "judge": "Hon. Test Judge",
    "docket_text": "Test text",
    "status": "active"
  }
]
EOF
```

Run ingestion:
```bash
JSON_FILE=test_bad_date.json python ingest.py
```

**Expected:**
- Record quarantined
- Error recorded in `ingest_errors` with `error_code='BAD_DATE'`
- `failed` count = 1

### 11.2 Test with Missing Case Number

```bash
cat > test_missing_case.json << EOF
[
  {
    "case_number": "",
    "court": "S.D.N.Y",
    "title": "Test Case",
    "filed_date": "2023-01-01",
    "parties": "Test Party (plaintiff)",
    "case_type": "civil",
    "judge": "Hon. Test Judge",
    "docket_text": "Test text",
    "status": "active"
  }
]
EOF
```

Run ingestion:
```bash
JSON_FILE=test_missing_case.json python ingest.py
```

**Expected:**
- Record quarantined
- Error recorded with `error_code='MISSING_CASE_NUMBER'`
- `failed` count = 1

---

## Step 12: Verify Statistics

### 12.1 Overall Statistics

```bash
psql -U postgres -d legal_dockets << EOF
SELECT 
    (SELECT COUNT(*) FROM cases) as total_cases,
    (SELECT COUNT(*) FROM courts) as total_courts,
    (SELECT COUNT(*) FROM judges) as total_judges,
    (SELECT COUNT(*) FROM parties) as total_parties,
    (SELECT COUNT(*) FROM case_parties) as total_case_party_links,
    (SELECT COUNT(*) FROM court_name_variations) as total_court_variations,
    (SELECT COUNT(*) FROM judge_name_variations) as total_judge_variations,
    (SELECT COUNT(*) FROM party_name_variations) as total_party_variations,
    (SELECT COUNT(*) FROM ingest_runs) as total_runs,
    (SELECT COUNT(*) FROM ingest_errors) as total_errors;
EOF
```

**Expected:** All counts > 0, showing data was ingested

### 12.2 Ingestion Summary

```bash
psql -U postgres -d legal_dockets -c "
SELECT 
    run_id,
    source_name,
    total_read,
    total_inserted,
    total_updated,
    total_failed,
    started_at,
    finished_at
FROM ingest_runs
ORDER BY run_id DESC;
"
```

**Expected:** Summary of all ingestion runs

---

## Step 13: Clean Up Test Data (Optional)

```bash
# Remove test files
rm -f test_bad_date.json test_missing_case.json

# Optional: Drop database if you want to start fresh
# psql -U postgres -c "DROP DATABASE legal_dockets;"
```

---

## Troubleshooting

### Issue: Connection refused

**Solution:** Ensure PostgreSQL is running:
```bash
# Check PostgreSQL status
brew services list | grep postgresql
# Or
sudo systemctl status postgresql
```

### Issue: Permission denied

**Solution:** Check PostgreSQL user permissions:
```bash
psql -U postgres -c "\du"
```

### Issue: Constraint already exists

**Solution:** The `IF NOT EXISTS` should prevent this, but if it occurs:
```bash
# Check existing constraints
psql -U postgres -d legal_dockets -c "\d courts"
```

### Issue: No data in tables

**Solution:** 
1. Check ingestion log: `cat ingestion.log`
2. Check for errors: `SELECT * FROM ingest_errors;`
3. Verify JSON file path in `.env`

---

## Success Criteria

✅ All tables created successfully  
✅ Data ingested with proper counts  
✅ Name variations tracked for courts, judges, parties  
✅ Failed records quarantined and logged  
✅ Upsert works (updates existing cases)  
✅ Unique constraints enforce one canonical row per normalized name  
✅ Complex queries return expected results  
✅ Error handling works for bad dates, missing fields, etc.  

---

## Next Steps

Once testing is complete, you can:
1. Build Part 2: RAG/Semantic Search
2. Build Part 3: REST API
3. Add more validation rules
4. Create data quality reports

