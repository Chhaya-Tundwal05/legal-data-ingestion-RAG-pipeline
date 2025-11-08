#!/usr/bin/env python3
"""
Legal Docket Data Ingestion Script

This script:
- Parses and cleans messy JSON docket data
- Extracts structured entities (parties, dates, judges, courts)
- Loads data into normalized PostgreSQL schema
- Handles duplicates and data quality issues
- Logs anomalies and warnings
"""

import json
import re
import logging
import hashlib
import os
import pathlib
import psycopg2
from psycopg2.extras import execute_values
from psycopg2 import sql
from datetime import datetime, date
from typing import Dict, List, Tuple, Optional, Set
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ingestion.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Quarantine directory for failed records
QUARANTINE_DIR = os.environ.get("QUARANTINE_DIR", "quarantine")


# Utility functions for error tracking
def canonical_json(obj: dict) -> str:
    """Convert dict to canonical JSON string for hashing"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_hex(s: str) -> str:
    """Compute SHA256 hash of string as hex"""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class DocketIngester:
    """Handles ingestion of legal docket data into PostgreSQL"""
    
    def __init__(self, db_config: Dict[str, str]):
        """
        Initialize ingester with database configuration
        
        Args:
            db_config: Dictionary with keys: host, port, database, user, password
        """
        self.db_config = db_config
        self.conn = None
        self.cursor = None
        
        # Track entities for normalization
        self.courts_cache = {}  # normalized_name -> id
        self.judges_cache = {}  # normalized_name -> id
        self.case_types_cache = {}  # name -> id
        self.parties_cache = {}  # normalized_name -> id
        
        # Track processed case numbers to detect duplicates
        self.processed_cases = set()
        
        # Run tracking
        self.run_id = None
        self.quarantine_path = None
        
        # Statistics
        self.stats = {
            'total_records': 0,
            'successful': 0,
            'duplicates_skipped': 0,
            'errors': 0,
            'warnings': []
        }
        
        # New tracking counters
        self.counts = {
            'read': 0,
            'inserted': 0,
            'updated': 0,
            'failed': 0
        }
    
    def connect(self):
        """Establish database connection"""
        try:
            self.conn = psycopg2.connect(**self.db_config)
            self.cursor = self.conn.cursor()
            logger.info("Connected to database successfully")
        except psycopg2.Error as e:
            logger.error(f"Database connection failed: {e}")
            raise
    
    def close(self):
        """Close database connection"""
        if self.cursor:
            self.cursor.close()
        if self.conn:
            self.conn.close()
        logger.info("Database connection closed")
    
    def start_run(self, source_name: str, source_uri: Optional[str] = None) -> int:
        """
        Start a new ingestion run and return run_id
        
        Args:
            source_name: Name of the source (e.g., filename)
            source_uri: Optional URI/path to the source
            
        Returns:
            run_id: The ID of the created run
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_runs (source_name, source_uri)
                VALUES (%s, %s)
                RETURNING run_id
                """,
                (source_name, source_uri),
            )
            run_id = cur.fetchone()[0]
            self.conn.commit()
            self.run_id = run_id
            logger.info(f"Started ingestion run {run_id} for source: {source_name}")
            return run_id
    
    def finish_run(self, run_id: int, totals: Dict[str, int]):
        """
        Finish an ingestion run and update totals
        
        Args:
            run_id: The run ID to finish
            totals: Dictionary with keys: read, inserted, updated, failed
        """
        with self.conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_runs
                   SET finished_at = now(),
                       total_read = %s,
                       total_inserted = %s,
                       total_updated = %s,
                       total_failed = %s
                 WHERE run_id = %s
                """,
                (
                    totals.get("read", 0),
                    totals.get("inserted", 0),
                    totals.get("updated", 0),
                    totals.get("failed", 0),
                    run_id,
                ),
            )
            self.conn.commit()
            logger.info(f"Finished ingestion run {run_id}")
    
    def write_quarantine_jsonl(self, run_id: int, raw_row: Dict, error_code: str, why: str, path: Optional[str] = None) -> str:
        """
        Write a failed record to quarantine JSONL file
        
        Args:
            run_id: The ingestion run ID
            raw_row: The raw record that failed
            error_code: Error code (e.g., BAD_DATE, MISSING_CASE_NUMBER)
            why: Human-readable error message
            path: Optional path to quarantine file (auto-generated if None)
            
        Returns:
            Absolute path to the quarantine file
        """
        if not path:
            path = os.path.join(QUARANTINE_DIR, f"ingest_run_{run_id}.jsonl")
        
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
        
        record_hash = sha256_hex(canonical_json(raw_row))
        rec = {
            "run_id": run_id,
            "error_code": error_code,
            "why": why,
            "raw": raw_row,
            "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "record_hash": record_hash,
        }
        
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        
        return os.path.abspath(path)
    
    def record_error(self, run_id: int, raw_row: Dict, error_code: str, error_msg: str, 
                     case_number: Optional[str] = None, normalized_attempt: Optional[Dict] = None):
        """
        Record an error in the ingest_errors table
        
        Args:
            run_id: The ingestion run ID
            raw_row: The raw record that failed
            error_code: Error code (e.g., BAD_DATE, MISSING_CASE_NUMBER)
            error_msg: Human-readable error message
            case_number: Optional case number for quick filtering
            normalized_attempt: Optional dict with normalized values that were attempted
        """
        record_hash = sha256_hex(canonical_json(raw_row))
        details = {
            "raw": raw_row,
            "normalized_attempt": normalized_attempt or {},
            "context": {},
            "why": error_msg,
            "suggestion": ""
        }
        
        with self.conn.cursor() as cur:
            # Try update existing by (run_id, record_hash)
            cur.execute(
                """
                UPDATE ingest_errors
                   SET last_seen_at = now(),
                       retry_count = retry_count + 1
                 WHERE run_id = %s AND record_hash = %s
                """,
                (run_id, record_hash),
            )
            
            if cur.rowcount == 0:
                # Insert new error record
                cur.execute(
                    """
                    INSERT INTO ingest_errors
                        (run_id, record_hash, case_number, error_code, error_message, details)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (run_id, record_hash, case_number, error_code, error_msg, json.dumps(details)),
                )
        
        self.conn.commit()
    
    def normalize_court_name(self, court: str) -> str:
        """
        Normalize court name to handle variations
        
        Examples:
        - "S.D.N.Y" -> "SDNY"
        - "S.D.N.Y." -> "SDNY"
        - "N.D. Cal." -> "NDCAL"
        """
        if not court:
            return ""
        
        # Remove periods, spaces, convert to uppercase
        normalized = re.sub(r'[.\s]+', '', court.upper())
        return normalized
    
    def normalize_judge_name(self, judge: str) -> str:
        """
        Normalize judge name by removing titles and extra whitespace
        
        Examples:
        - "Hon. Maria Rodriguez" -> "maria rodriguez"
        - "Judge Sarah Chen" -> "sarah chen"
        """
        if not judge:
            return ""
        
        # Remove common titles
        normalized = re.sub(r'^(hon\.?|judge|justice)\s+', '', judge, flags=re.IGNORECASE)
        # Normalize whitespace and convert to lowercase
        normalized = ' '.join(normalized.split()).lower()
        return normalized
    
    def normalize_party_name(self, party: str) -> str:
        """
        Normalize party name for matching variations
        
        Examples:
        - "Acme Corp" -> "acme corp"
        - "Acme Corporation" -> "acme corporation" (kept separate for now)
        """
        if not party:
            return ""
        
        # Remove extra whitespace, convert to lowercase
        normalized = ' '.join(party.split()).lower().strip()
        return normalized
    
    def parse_date(self, date_str: str) -> date:
        """
        Parse docket dates assuming US ordering (month-day-year).
        
        Accepts:
        - ISO: YYYY-MM-DD (2024-10-03)
        - Numeric MDY: M/D/YYYY, M-D-YYYY, MM/DD/YYYY, MM-DD-YYYY (single-digit month/day allowed)
        - Month name: Oct 3, 2024, October 3, 2024
        
        Raises:
            ValueError: If date cannot be parsed
        """
        if date_str is None:
            raise ValueError("filed_date missing")
        
        s = str(date_str).strip()
        if not s:
            raise ValueError("filed_date missing")
        
        # 1) Try ISO (strict)
        try:
            return datetime.strptime(s, '%Y-%m-%d').date()
        except ValueError:
            pass
        
        # 2) Try numeric MDY with regex to allow single-digit month/day
        # Pattern: M-D-YYYY or M/D/YYYY (1-2 digits for month, 1-2 digits for day)
        mdy_numeric = re.match(r'^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$', s)
        if mdy_numeric:
            mm, dd, yyyy = map(int, mdy_numeric.groups())
            try:
                return date(yyyy, mm, dd)
            except ValueError as e:
                # e.g., 13-40-2024 will land here
                raise ValueError(f"filed_date parse failed (mdy numeric): {s!r}: {e}")
        
        # 3) Try named-month forms
        for fmt in ['%b %d, %Y', '%B %d, %Y']:  # Oct 3, 2024 or October 3, 2024
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        
        # 4) Try standard mdy forms with zero-padded expectations
        for fmt in ['%m/%d/%Y', '%m-%d-%Y']:  # 10/03/2024 or 10-03-2024
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        
        # Final failure
        raise ValueError(f"filed_date parse failed: {s!r}")
    
    def parse_parties(self, parties_str: str) -> List[Tuple[str, str]]:
        """
        Parse parties string into list of (name, role) tuples
        
        Handles various formats:
        - "John Smith (plaintiff); Acme Corp, Jane Doe (defendants)"
        - "TechStart Inc (plaintiff), MegaCorp (defendant)"
        - "Robert Anderson (plaintiff) / HealthPlus Insurance Co. (defendant)"
        
        Returns:
            List of tuples: [(party_name, role), ...]
        """
        if not parties_str:
            return []
        
        parties = []
        
        # Split by semicolon or slash first (major separators)
        major_sections = re.split(r'[;/]', parties_str)
        
        for section in major_sections:
            section = section.strip()
            if not section:
                continue
            
            # Try to extract role from parentheses
            role_match = re.search(r'\((plaintiff|defendant|plaintiffs|defendants|third_party|intervenor|other)\)', 
                                 section, re.IGNORECASE)
            
            if role_match:
                role = role_match.group(1).lower()
                # Normalize plural forms
                if role.endswith('s'):
                    role = role[:-1]
                
                # Remove role from section
                section = re.sub(r'\([^)]+\)', '', section).strip()
                
                # Split by comma to get individual parties
                party_names = [p.strip() for p in section.split(',') if p.strip()]
                
                for party_name in party_names:
                    if party_name:
                        parties.append((party_name, role))
            else:
                # No role specified, try to infer from context or mark as 'other'
                party_names = [p.strip() for p in section.split(',') if p.strip()]
                for party_name in party_names:
                    if party_name:
                        parties.append((party_name, 'other'))
        
        return parties
    
    def record_court_variation(self, court_id: int, raw_name: str):
        """Record a court name variation"""
        self.cursor.execute(
            """
            INSERT INTO court_name_variations (court_id, raw_name)
            VALUES (%s, %s)
            ON CONFLICT (court_id, raw_name) DO UPDATE
                SET last_seen_at = now(),
                    seen_count = court_name_variations.seen_count + 1
            """,
            (court_id, raw_name)
        )
    
    def get_or_create_court(self, court_name: str) -> int:
        """Get or create court record, return court_id"""
        if not court_name:
            raise ValueError("Court name cannot be empty")
        
        normalized = self.normalize_court_name(court_name)
        
        if normalized in self.courts_cache:
            court_id = self.courts_cache[normalized]
        else:
            # Check if exists in database
            self.cursor.execute(
                "SELECT id FROM courts WHERE normalized_name = %s",
                (normalized,)
            )
            result = self.cursor.fetchone()
            
            if result:
                court_id = result[0]
            else:
                # Insert new court
                self.cursor.execute(
                    "INSERT INTO courts (name, normalized_name) VALUES (%s, %s) RETURNING id",
                    (court_name, normalized)
                )
                court_id = self.cursor.fetchone()[0]
                logger.info(f"Created new court: {court_name} (normalized: {normalized})")
            
            self.courts_cache[normalized] = court_id
        
        # Record this variation (always record, tracks all seen forms)
        self.record_court_variation(court_id, court_name)
        
        return court_id
    
    def record_judge_variation(self, judge_id: int, raw_name: str):
        """Record a judge name variation"""
        self.cursor.execute(
            """
            INSERT INTO judge_name_variations (judge_id, raw_name)
            VALUES (%s, %s)
            ON CONFLICT (judge_id, raw_name) DO UPDATE
                SET last_seen_at = now(),
                    seen_count = judge_name_variations.seen_count + 1
            """,
            (judge_id, raw_name)
        )
    
    def get_or_create_judge(self, judge_name: str) -> Optional[int]:
        """Get or create judge record, return judge_id (or None if name is empty)"""
        if not judge_name:
            return None
        
        normalized = self.normalize_judge_name(judge_name)
        
        if not normalized:
            return None
        
        if normalized in self.judges_cache:
            judge_id = self.judges_cache[normalized]
        else:
            # Check if exists in database
            self.cursor.execute(
                "SELECT id FROM judges WHERE normalized_name = %s",
                (normalized,)
            )
            result = self.cursor.fetchone()
            
            if result:
                judge_id = result[0]
            else:
                # Insert new judge
                self.cursor.execute(
                    "INSERT INTO judges (full_name, normalized_name) VALUES (%s, %s) RETURNING id",
                    (judge_name, normalized)
                )
                judge_id = self.cursor.fetchone()[0]
                logger.info(f"Created new judge: {judge_name} (normalized: {normalized})")
            
            self.judges_cache[normalized] = judge_id
        
        # Record this variation (always record, tracks all seen forms)
        self.record_judge_variation(judge_id, judge_name)
        
        return judge_id
    
    def get_or_create_case_type(self, case_type: str) -> int:
        """Get or create case type record, return case_type_id"""
        if not case_type:
            raise ValueError("Case type cannot be empty")
        
        case_type = case_type.lower().strip()
        
        if case_type in self.case_types_cache:
            return self.case_types_cache[case_type]
        
        # Check if exists in database
        self.cursor.execute(
            "SELECT id FROM case_types WHERE name = %s",
            (case_type,)
        )
        result = self.cursor.fetchone()
        
        if result:
            type_id = result[0]
        else:
            # Insert new case type
            self.cursor.execute(
                "INSERT INTO case_types (name) VALUES (%s) RETURNING id",
                (case_type,)
            )
            type_id = self.cursor.fetchone()[0]
            logger.info(f"Created new case type: {case_type}")
        
        self.case_types_cache[case_type] = type_id
        return type_id
    
    def record_party_variation(self, party_id: int, raw_name: str):
        """Record a party name variation"""
        self.cursor.execute(
            """
            INSERT INTO party_name_variations (party_id, raw_name)
            VALUES (%s, %s)
            ON CONFLICT (party_id, raw_name) DO UPDATE
                SET last_seen_at = now(),
                    seen_count = party_name_variations.seen_count + 1
            """,
            (party_id, raw_name)
        )
    
    def get_or_create_party(self, party_name: str) -> int:
        """Get or create party record, return party_id"""
        if not party_name:
            raise ValueError("Party name cannot be empty")
        
        normalized = self.normalize_party_name(party_name)
        
        if normalized in self.parties_cache:
            party_id = self.parties_cache[normalized]
        else:
            # Check if exists in database
            self.cursor.execute(
                "SELECT id FROM parties WHERE normalized_name = %s",
                (normalized,)
            )
            result = self.cursor.fetchone()
            
            if result:
                party_id = result[0]
            else:
                # Insert new party
                self.cursor.execute(
                    "INSERT INTO parties (name, normalized_name) VALUES (%s, %s) RETURNING id",
                    (party_name, normalized)
                )
                party_id = self.cursor.fetchone()[0]
            
            self.parties_cache[normalized] = party_id
        
        # Record this variation (always record, tracks all seen forms)
        self.record_party_variation(party_id, party_name)
        
        return party_id
    
    def process_docket(self, docket: Dict) -> Tuple[bool, str]:
        """
        Process a single docket record
        
        Returns:
            Tuple of (success: bool, action: str) where action is 'inserted' or 'updated'
            
        Raises:
            ValueError: For validation errors (missing required fields, bad dates, etc.)
        """
        # Extract and validate required fields
        case_number = docket.get('case_number', '').strip()
        if not case_number:
            raise ValueError("case_number is required and cannot be empty")
        
        # Parse date - raises ValueError if invalid
        filed_date_str = docket.get('filed_date', '')
        filed_date = self.parse_date(filed_date_str)  # Returns date object
        
        # Get or create related entities - these may raise ValueError
        court_id = self.get_or_create_court(docket.get('court', ''))
        judge_id = self.get_or_create_judge(docket.get('judge'))
        case_type_id = self.get_or_create_case_type(docket.get('case_type', 'civil'))
        
        # Validate status
        status = docket.get('status', 'active').lower()
        if status not in ['active', 'closed', 'pending', 'dismissed']:
            raise ValueError(f"Invalid status '{status}'. Must be one of: active, closed, pending, dismissed")
        
        # True upsert with ON CONFLICT DO UPDATE
        # Use xmax = 0 to detect if row was newly inserted (xmax = 0) or updated (xmax > 0)
        self.cursor.execute(
            """
            INSERT INTO cases (case_number, court_id, title, filed_date, case_type_id, 
                             judge_id, docket_text, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (case_number) DO UPDATE
                SET court_id = EXCLUDED.court_id,
                    title = EXCLUDED.title,
                    filed_date = EXCLUDED.filed_date,
                    case_type_id = EXCLUDED.case_type_id,
                    judge_id = EXCLUDED.judge_id,
                    docket_text = EXCLUDED.docket_text,
                    status = EXCLUDED.status,
                    updated_at = now()
            RETURNING id, (xmax = 0) AS inserted
            """,
                (
                    case_number,
                    court_id,
                    docket.get('title', ''),
                    filed_date,  # Already a date object
                    case_type_id,
                    judge_id,
                    docket.get('docket_text', ''),
                    status
                )
        )
        result = self.cursor.fetchone()
        case_id = result[0]
        is_inserted = result[1]  # True if inserted, False if updated
        
        action = 'inserted' if is_inserted else 'updated'
        
        self.processed_cases.add(case_number)
        
        # Parse and insert parties
        parties_str = docket.get('parties', '')
        parties = self.parse_parties(parties_str)
        
        # Note: Missing parties is not a fatal error, just a warning
        if not parties:
            logger.warning(f"No parties found for case {case_number}")
            self.stats['warnings'].append(f"No parties for case {case_number}")
        else:
            for party_name, role in parties:
                try:
                    party_id = self.get_or_create_party(party_name)
                    
                    # Insert case-party relationship
                    self.cursor.execute(
                        """
                        INSERT INTO case_parties (case_id, party_id, role)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (case_id, party_id, role) DO NOTHING
                        """,
                        (case_id, party_id, role)
                    )
                except Exception as e:
                    logger.error(f"Error processing party '{party_name}' for case {case_number}: {e}")
                    self.stats['warnings'].append(f"Error processing party for case {case_number}: {e}")
        
        return (True, action)
    
    def ingest_file(self, json_file_path: str, source_name: Optional[str] = None):
        """
        Ingest all dockets from JSON file with run tracking and error handling
        
        Args:
            json_file_path: Path to raw_dockets.json file
            source_name: Optional name for the source (defaults to filename)
        """
        if not source_name:
            source_name = os.path.basename(json_file_path)
        
        logger.info(f"Starting ingestion from {json_file_path}")
        
        # Reset counters
        self.counts = {'read': 0, 'inserted': 0, 'updated': 0, 'failed': 0}
        
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                dockets = json.load(f)
            
            # Start ingestion run
            run_id = self.start_run(source_name, json_file_path)
            self.quarantine_path = None
            
            logger.info(f"Loaded {len(dockets)} docket records")
            
            # Process each docket
            for i, docket in enumerate(dockets, 1):
                self.counts['read'] += 1
                
                try:
                    # Process the docket - may raise ValueError for validation errors
                    success, action = self.process_docket(docket)
                    
                    if success:
                        if action == 'inserted':
                            self.counts['inserted'] += 1
                        elif action == 'updated':
                            self.counts['updated'] += 1
                    
                    # Commit every 100 records for better performance
                    if i % 100 == 0:
                        self.conn.commit()
                        logger.info(f"Processed {i}/{len(dockets)} records... "
                                  f"(inserted: {self.counts['inserted']}, "
                                  f"updated: {self.counts['updated']}, "
                                  f"failed: {self.counts['failed']})")
                
                except ValueError as e:
                    # Validation error - record in quarantine and error table
                    error_code = self._determine_error_code(e, docket)
                    error_msg = str(e)
                    case_number = docket.get('case_number', '').strip() or None
                    
                    # Write to quarantine file
                    self.quarantine_path = self.write_quarantine_jsonl(
                        run_id, docket, error_code, error_msg, self.quarantine_path
                    )
                    
                    # Record error in database
                    self.record_error(
                        run_id, docket, error_code, error_msg, case_number, normalized_attempt=None
                    )
                    
                    self.counts['failed'] += 1
                    logger.warning(f"Failed to process record {i}: {error_msg}")
                
                except Exception as e:
                    # Unknown error - record in quarantine and error table
                    error_code = "UNKNOWN"
                    error_msg = str(e)
                    case_number = docket.get('case_number', '').strip() or None
                    
                    # Write to quarantine file
                    self.quarantine_path = self.write_quarantine_jsonl(
                        run_id, docket, error_code, error_msg, self.quarantine_path
                    )
                    
                    # Record error in database
                    self.record_error(
                        run_id, docket, error_code, error_msg, case_number, normalized_attempt=None
                    )
                    
                    self.counts['failed'] += 1
                    logger.error(f"Unexpected error processing record {i}: {e}", exc_info=True)
            
            # Final commit
            self.conn.commit()
            
            # Finish the run
            self.finish_run(run_id, self.counts)
            
            # Print JSON summary
            summary = {
                "run_id": run_id,
                "summary": self.counts
            }
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            
            # Also log summary
            logger.info("=" * 60)
            logger.info("INGESTION SUMMARY")
            logger.info("=" * 60)
            logger.info(f"Run ID: {run_id}")
            logger.info(f"Total read: {self.counts['read']}")
            logger.info(f"Inserted: {self.counts['inserted']}")
            logger.info(f"Updated: {self.counts['updated']}")
            logger.info(f"Failed: {self.counts['failed']}")
            
            if self.quarantine_path:
                logger.info(f"Quarantine file: {self.quarantine_path}")
            
        except FileNotFoundError:
            logger.error(f"File not found: {json_file_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON file: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during ingestion: {e}")
            if self.conn:
                self.conn.rollback()
            raise
    
    def _determine_error_code(self, error: Exception, docket: Dict) -> str:
        """
        Determine error code from exception and docket data
        
        Args:
            error: The exception that was raised
            docket: The raw docket record
            
        Returns:
            Error code string
        """
        error_msg = str(error).lower()
        
        if "case_number" in error_msg:
            return "MISSING_CASE_NUMBER"
        elif "filed_date" in error_msg or "date" in error_msg:
            return "BAD_DATE"
        elif "status" in error_msg:
            return "STATUS_UNMAPPED"
        elif "court" in error_msg:
            return "FK_COURT"
        elif "case_type" in error_msg:
            return "FK_CASE_TYPE"
        elif "judge" in error_msg:
            return "FK_JUDGE"
        else:
            return "VALIDATION_ERROR"


def main():
    """Main entry point"""
    import os
    import argparse
    from urllib.parse import urlparse
    from dotenv import load_dotenv
    
    # Load environment variables
    load_dotenv()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Legal Docket Ingestion Pipeline')
    parser.add_argument('--file', type=str, help='Path to JSON file to ingest')
    args = parser.parse_args()
    
    # Database configuration - support DATABASE_URL or individual env vars
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        # Parse DATABASE_URL: postgresql://user:password@host:port/database
        parsed = urlparse(database_url)
        db_config = {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or 5432,
            'database': parsed.path.lstrip('/') or 'dockets',
            'user': parsed.username or 'postgres',
            'password': parsed.password or 'postgres'
        }
    else:
        # Fall back to individual environment variables
        db_config = {
            'host': os.getenv('DB_HOST', 'localhost'),
            'port': os.getenv('DB_PORT', '5432'),
            'database': os.getenv('DB_NAME', 'legal_dockets'),
            'user': os.getenv('DB_USER', 'postgres'),
            'password': os.getenv('DB_PASSWORD', 'postgres')
        }
    
    # JSON file path - command line argument takes precedence
    json_file = args.file or os.getenv('JSON_FILE', 'raw_dockets.json')
    
    # Create ingester and run
    ingester = DocketIngester(db_config)
    
    try:
        ingester.connect()
        ingester.ingest_file(json_file)
    finally:
        ingester.close()


def selftest():
    """Self-test for date parser - run with --selftest flag"""
    print("Testing date parser...")
    
    # Create a minimal ingester instance just for parse_date method
    class TestIngester:
        def parse_date(self, date_str: str) -> date:
            """Parse docket dates assuming US ordering (month-day-year)."""
            if date_str is None:
                raise ValueError("filed_date missing")
            
            s = str(date_str).strip()
            if not s:
                raise ValueError("filed_date missing")
            
            # 1) Try ISO (strict)
            try:
                return datetime.strptime(s, '%Y-%m-%d').date()
            except ValueError:
                pass
            
            # 2) Try numeric MDY with regex to allow single-digit month/day
            mdy_numeric = re.match(r'^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$', s)
            if mdy_numeric:
                mm, dd, yyyy = map(int, mdy_numeric.groups())
                try:
                    return date(yyyy, mm, dd)
                except ValueError as e:
                    raise ValueError(f"filed_date parse failed (mdy numeric): {s!r}: {e}")
            
            # 3) Try named-month forms
            for fmt in ['%b %d, %Y', '%B %d, %Y']:
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    pass
            
            # 4) Try standard mdy forms with zero-padded expectations
            for fmt in ['%m/%d/%Y', '%m-%d-%Y']:
                try:
                    return datetime.strptime(s, fmt).date()
                except ValueError:
                    pass
            
            # Final failure
            raise ValueError(f"filed_date parse failed: {s!r}")
    
    test_cases = [
        ("10-3-2024", date(2024, 10, 3)),
        ("4-5-2023", date(2023, 4, 5)),
        ("12-11-2025", date(2025, 12, 11)),
        ("6-6-2025", date(2025, 6, 6)),
        ("7-17-2022", date(2022, 7, 17)),
        ("9-25-2022", date(2022, 9, 25)),
        ("11-1-2025", date(2025, 11, 1)),
        ("8/8/2025", date(2025, 8, 8)),
        ("Oct 3, 2024", date(2024, 10, 3)),
        ("October 3, 2024", date(2024, 10, 3)),
        ("2024-10-03", date(2024, 10, 3)),
        ("03/15/2023", date(2023, 3, 15)),
    ]
    
    parser = TestIngester()
    passed = 0
    failed = 0
    
    for input_str, expected in test_cases:
        try:
            result = parser.parse_date(input_str)
            if result == expected:
                print(f"✅ {input_str!r} → {result}")
                passed += 1
            else:
                print(f"❌ {input_str!r} → {result} (expected {expected})")
                failed += 1
        except Exception as e:
            print(f"❌ {input_str!r} → ERROR: {e}")
            failed += 1
    
    # Test invalid dates
    invalid_cases = [
        "13-40-2024",  # Invalid month/day
        "",  # Empty
        None,  # None
    ]
    
    for input_str in invalid_cases:
        try:
            result = parser.parse_date(input_str)
            print(f"❌ {input_str!r} → {result} (should have raised ValueError)")
            failed += 1
        except ValueError:
            print(f"✅ {input_str!r} → ValueError (as expected)")
            passed += 1
        except Exception as e:
            print(f"⚠️  {input_str!r} → {type(e).__name__}: {e}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


if __name__ == '__main__':
    import sys
    if '--selftest' in sys.argv:
        success = selftest()
        sys.exit(0 if success else 1)
    else:
        main()

