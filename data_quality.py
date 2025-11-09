#!/usr/bin/env python3
"""
Data Quality Dashboard

Generates a concise, human-readable quality report for the legal docket database.
Supports filtering by run_id or date range.
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import psycopg2
from psycopg2.extras import RealDictCursor

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@db:5432/dockets")


def format_number(n: int) -> str:
    """Format number with commas"""
    return f"{n:,}"


def format_percent(numerator: int, denominator: int) -> str:
    """Format percentage with one decimal place"""
    if denominator == 0:
        return "0.0%"
    return f"{(numerator / denominator * 100):.1f}%"


def get_connection():
    """Get database connection"""
    return psycopg2.connect(DATABASE_URL)


def print_header(scope_desc: str):
    """Print report header"""
    print("=" * 60)
    print("Data Quality Report")
    print("=" * 60)
    print(f"Scope: {scope_desc}")
    print(f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
    print()


def print_section(title: str):
    """Print section header"""
    print(f"\n--- {title} ---")


def get_scope_description(run_id: Optional[int], since: Optional[str]) -> str:
    """Generate scope description"""
    if run_id:
        return f"run_id={run_id}"
    elif since:
        return f"cases filed on/after {since}"
    else:
        return "all-time (lifetime aggregates)"


def get_volume_summary(conn, run_id: Optional[int]) -> Dict:
    """Get volume summary from ingest_runs"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if run_id:
            cur.execute("""
                SELECT 
                    total_read as total_records,
                    total_inserted as inserted,
                    total_updated as updated,
                    total_failed as failed,
                    0 as warnings
                FROM ingest_runs
                WHERE run_id = %s
            """, (run_id,))
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)
        else:
            cur.execute("""
                SELECT 
                    SUM(total_read) as total_records,
                    SUM(total_inserted) as inserted,
                    SUM(total_updated) as updated,
                    SUM(total_failed) as failed,
                    0 as warnings
                FROM ingest_runs
            """)
            row = cur.fetchone()
            return dict(row) if row else {
                "total_records": 0, "inserted": 0, "updated": 0, "failed": 0, "warnings": 0
            }


def get_error_breakdown(conn, run_id: Optional[int], since: Optional[str]) -> List[Dict]:
    """Get top 10 error codes with counts"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if run_id:
            cur.execute("""
                SELECT 
                    error_code,
                    COUNT(*) AS cnt,
                    MAX(last_seen_at) AS most_recent
                FROM ingest_errors
                WHERE run_id = %s
                GROUP BY error_code
                ORDER BY cnt DESC
                LIMIT 10
            """, (run_id,))
        elif since:
            cur.execute("""
                SELECT 
                    e.error_code,
                    COUNT(*) AS cnt,
                    MAX(e.last_seen_at) AS most_recent
                FROM ingest_errors e
                JOIN ingest_runs r ON e.run_id = r.run_id
                WHERE r.started_at >= %s::date
                GROUP BY e.error_code
                ORDER BY cnt DESC
                LIMIT 10
            """, (since,))
        else:
            cur.execute("""
                SELECT 
                    error_code,
                    COUNT(*) AS cnt,
                    MAX(last_seen_at) AS most_recent
                FROM ingest_errors
                GROUP BY error_code
                ORDER BY cnt DESC
                LIMIT 10
            """)
        return [dict(row) for row in cur.fetchall()]


def get_completeness(conn, since: Optional[str]) -> Dict:
    """Get completeness checks for cases"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if since:
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE judge_id IS NULL) AS no_judge,
                    COUNT(*) FILTER (WHERE court_id IS NULL) AS no_court,
                    COUNT(*) FILTER (WHERE case_type_id IS NULL) AS no_case_type,
                    COUNT(*) FILTER (WHERE COALESCE(NULLIF(docket_text, ''), NULL) IS NULL) AS no_docket
                FROM cases
                WHERE filed_date >= %s::date
            """, (since,))
        else:
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE judge_id IS NULL) AS no_judge,
                    COUNT(*) FILTER (WHERE court_id IS NULL) AS no_court,
                    COUNT(*) FILTER (WHERE case_type_id IS NULL) AS no_case_type,
                    COUNT(*) FILTER (WHERE COALESCE(NULLIF(docket_text, ''), NULL) IS NULL) AS no_docket
                FROM cases
            """)
        row = cur.fetchone()
        return dict(row) if row else {
            "total": 0, "no_judge": 0, "no_court": 0, "no_case_type": 0, "no_docket": 0
        }


def get_date_sanity(conn, run_id: Optional[int], since: Optional[str]) -> Dict:
    """Get date sanity checks"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Get min/max filed_date
        if since:
            cur.execute("""
                SELECT MIN(filed_date) AS min_date, MAX(filed_date) AS max_date
                FROM cases
                WHERE filed_date >= %s::date
            """, (since,))
        else:
            cur.execute("""
                SELECT MIN(filed_date) AS min_date, MAX(filed_date) AS max_date
                FROM cases
            """)
        date_row = cur.fetchone()
        min_date = date_row["min_date"] if date_row and date_row["min_date"] else None
        max_date = date_row["max_date"] if date_row and date_row["max_date"] else None
        
        # Get bad dates count
        if run_id:
            cur.execute("""
                SELECT COUNT(*) AS bad_dates
                FROM ingest_errors
                WHERE run_id = %s
                  AND error_code LIKE 'filed_date parse failed%'
            """, (run_id,))
        elif since:
            cur.execute("""
                SELECT COUNT(*) AS bad_dates
                FROM ingest_errors e
                JOIN ingest_runs r ON e.run_id = r.run_id
                WHERE r.started_at >= %s::date
                  AND e.error_code LIKE 'filed_date parse failed%'
            """, (since,))
        else:
            cur.execute("""
                SELECT COUNT(*) AS bad_dates
                FROM ingest_errors
                WHERE error_code LIKE 'filed_date parse failed%'
            """)
        bad_row = cur.fetchone()
        bad_dates = bad_row["bad_dates"] if bad_row else 0
        
        return {
            "min_date": min_date,
            "max_date": max_date,
            "bad_dates": bad_dates
        }


def get_entity_normalization(conn) -> Dict:
    """Get entity normalization sanity checks"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # Judges (uses full_name, not name)
        cur.execute("""
            SELECT 
                COUNT(DISTINCT full_name) AS distinct_names,
                COUNT(DISTINCT normalized_name) AS distinct_normalized,
                COUNT(*) AS total
            FROM judges
        """)
        judges_row = cur.fetchone()
        
        # Courts (uses name)
        cur.execute("""
            SELECT 
                COUNT(DISTINCT name) AS distinct_names,
                COUNT(DISTINCT normalized_name) AS distinct_normalized,
                COUNT(*) AS total
            FROM courts
        """)
        courts_row = cur.fetchone()
        
        return {
            "judges": dict(judges_row) if judges_row else {"distinct_names": 0, "distinct_normalized": 0, "total": 0},
            "courts": dict(courts_row) if courts_row else {"distinct_names": 0, "distinct_normalized": 0, "total": 0}
        }


def get_parties_coverage(conn, since: Optional[str]) -> Dict:
    """Get parties coverage statistics"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if since:
            cur.execute("""
                WITH per_case AS (
                    SELECT cp.case_number,
                        BOOL_OR(cp.role = 'plaintiff') AS has_plaintiff,
                        BOOL_OR(cp.role = 'defendant') AS has_defendant
                    FROM case_parties cp
                    JOIN cases c ON cp.case_id = c.id
                    WHERE c.filed_date >= %s::date
                    GROUP BY cp.case_number
                )
                SELECT
                    COUNT(*) AS cases_with_parties,
                    COUNT(*) FILTER (WHERE has_plaintiff) AS cases_with_plaintiff,
                    COUNT(*) FILTER (WHERE has_defendant) AS cases_with_defendant
                FROM per_case
            """, (since,))
        else:
            cur.execute("""
                WITH per_case AS (
                    SELECT case_number,
                        BOOL_OR(role = 'plaintiff') AS has_plaintiff,
                        BOOL_OR(role = 'defendant') AS has_defendant
                    FROM case_parties
                    GROUP BY case_number
                )
                SELECT
                    COUNT(*) AS cases_with_parties,
                    COUNT(*) FILTER (WHERE has_plaintiff) AS cases_with_plaintiff,
                    COUNT(*) FILTER (WHERE has_defendant) AS cases_with_defendant
                FROM per_case
            """)
        coverage_row = cur.fetchone()
        
        # Get top 10 roles
        cur.execute("""
            SELECT role, COUNT(*) AS cnt
            FROM case_parties
            GROUP BY role
            ORDER BY cnt DESC
            LIMIT 10
        """)
        roles = [dict(row) for row in cur.fetchall()]
        
        return {
            "coverage": dict(coverage_row) if coverage_row else {
                "cases_with_parties": 0, "cases_with_plaintiff": 0, "cases_with_defendant": 0
            },
            "roles": roles
        }


def get_recent_7_days(conn) -> List[Dict]:
    """Get daily statistics for last 7 days"""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT 
                DATE(r.started_at) AS day,
                SUM(r.total_read) AS ingested,
                SUM(r.total_failed) AS failed
            FROM ingest_runs r
            WHERE r.started_at >= CURRENT_DATE - INTERVAL '7 days'
            GROUP BY DATE(r.started_at)
            ORDER BY day DESC
        """)
        return [dict(row) for row in cur.fetchall()]


def print_ascii_bar(value: int, max_value: int, width: int = 40) -> str:
    """Generate ASCII bar for sparkline"""
    if max_value == 0:
        return " " * width
    filled = int((value / max_value) * width)
    return "█" * filled + "░" * (width - filled)


def generate_report(run_id: Optional[int], since: Optional[str]):
    """Generate and print the data quality report"""
    conn = get_connection()
    
    try:
        scope_desc = get_scope_description(run_id, since)
        print_header(scope_desc)
        
        # Check if run_id exists
        if run_id:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("SELECT 1 FROM ingest_runs WHERE run_id = %s", (run_id,))
                if not cur.fetchone():
                    print(f"ERROR: Run ID {run_id} not found")
                    sys.exit(1)
        
        # Volume Summary
        print_section("Volume Summary")
        volume = get_volume_summary(conn, run_id)
        if volume:
            total = volume["total_records"] or 0
            print(f"Total Records:     {format_number(total)}")
            print(f"  Inserted:       {format_number(volume['inserted'] or 0)}")
            print(f"  Updated:        {format_number(volume['updated'] or 0)}")
            print(f"  Failed:         {format_number(volume['failed'] or 0)}")
            if total > 0:
                failed_pct = (volume['failed'] or 0) / total * 100
                print(f"  Failed %:       {failed_pct:.1f}%")
        else:
            print("No data available")
        
        # Error Breakdown
        print_section("Error Breakdown (Top 10)")
        errors = get_error_breakdown(conn, run_id, since)
        if errors:
            total_errors = sum(e["cnt"] for e in errors)
            print(f"{'Error Code':<40} {'Count':>12} {'%':>8} {'Most Recent':<20}")
            print("-" * 80)
            for err in errors:
                pct = format_percent(err["cnt"], total_errors)
                recent = err["most_recent"].strftime("%Y-%m-%d %H:%M") if err["most_recent"] else "N/A"
                print(f"{err['error_code']:<40} {format_number(err['cnt']):>12} {pct:>8} {recent:<20}")
        else:
            print("No errors found")
        
        # Completeness Checks
        print_section("Completeness Checks (Cases)")
        completeness = get_completeness(conn, since)
        total = completeness["total"] or 0
        if total > 0:
            print(f"Total Cases:      {format_number(total)}")
            print(f"Missing Judge:    {format_number(completeness['no_judge'])} ({format_percent(completeness['no_judge'], total)})")
            print(f"Missing Court:    {format_number(completeness['no_court'])} ({format_percent(completeness['no_court'], total)})")
            print(f"Missing Case Type:{format_number(completeness['no_case_type'])} ({format_percent(completeness['no_case_type'], total)})")
            print(f"Missing Docket:   {format_number(completeness['no_docket'])} ({format_percent(completeness['no_docket'], total)})")
        else:
            print("No cases found")
        
        # Date Sanity
        print_section("Date Sanity")
        date_sanity = get_date_sanity(conn, run_id, since)
        if date_sanity["min_date"]:
            print(f"Min Filed Date:   {date_sanity['min_date']}")
            print(f"Max Filed Date:   {date_sanity['max_date']}")
        else:
            print("No dates found")
        
        if run_id or since:
            # Get total cases for bad date percentage
            completeness = get_completeness(conn, since)
            total_cases = completeness["total"] or 0
            if total_cases > 0:
                bad_pct = format_percent(date_sanity["bad_dates"], total_cases)
                print(f"Invalid Dates:    {format_number(date_sanity['bad_dates'])} ({bad_pct})")
            else:
                print(f"Invalid Dates:    {format_number(date_sanity['bad_dates'])}")
        else:
            # For all-time, use total from ingest_runs
            volume = get_volume_summary(conn, None)
            total_records = volume["total_records"] or 0
            if total_records > 0:
                bad_pct = format_percent(date_sanity["bad_dates"], total_records)
                print(f"Invalid Dates:    {format_number(date_sanity['bad_dates'])} ({bad_pct})")
            else:
                print(f"Invalid Dates:    {format_number(date_sanity['bad_dates'])}")
        
        # Entity Normalization
        print_section("Entity Normalization Sanity")
        norm = get_entity_normalization(conn)
        print("Judges:")
        print(f"  Distinct Names:        {format_number(norm['judges']['distinct_names'])}")
        print(f"  Distinct Normalized:    {format_number(norm['judges']['distinct_normalized'])}")
        print(f"  Total Rows:            {format_number(norm['judges']['total'])}")
        print("Courts:")
        print(f"  Distinct Names:        {format_number(norm['courts']['distinct_names'])}")
        print(f"  Distinct Normalized:    {format_number(norm['courts']['distinct_normalized'])}")
        print(f"  Total Rows:            {format_number(norm['courts']['total'])}")
        
        # Parties Coverage
        print_section("Parties Coverage")
        parties = get_parties_coverage(conn, since)
        coverage = parties["coverage"]
        total_with_parties = coverage["cases_with_parties"] or 0
        if total_with_parties > 0:
            print(f"Cases with Parties:     {format_number(total_with_parties)}")
            print(f"  With Plaintiff:      {format_number(coverage['cases_with_plaintiff'])} ({format_percent(coverage['cases_with_plaintiff'], total_with_parties)})")
            print(f"  With Defendant:      {format_number(coverage['cases_with_defendant'])} ({format_percent(coverage['cases_with_defendant'], total_with_parties)})")
        else:
            print("No cases with parties found")
        
        print("\nTop 10 Party Roles:")
        if parties["roles"]:
            print(f"{'Role':<20} {'Count':>12}")
            print("-" * 32)
            for role in parties["roles"]:
                print(f"{role['role']:<20} {format_number(role['cnt']):>12}")
        else:
            print("No party roles found")
        
        # Recent 7 Days (only if no run_id)
        if not run_id:
            print_section("Recent 7 Days")
            recent = get_recent_7_days(conn)
            if recent:
                max_ingested = max((r["ingested"] or 0) for r in recent) if recent else 1
                print(f"{'Date':<12} {'Ingested':>12} {'Failed':>12} {'Chart':<40}")
                print("-" * 76)
                for day in recent:
                    ingested = day["ingested"] or 0
                    failed = day["failed"] or 0
                    bar = print_ascii_bar(ingested, max_ingested)
                    print(f"{day['day']:<12} {format_number(ingested):>12} {format_number(failed):>12} {bar}")
            else:
                print("No data for last 7 days")
        
        # Check exit conditions
        exit_code = 0
        volume = get_volume_summary(conn, run_id)
        if volume and volume["total_records"]:
            failed_pct = (volume["failed"] or 0) / volume["total_records"] * 100
            if failed_pct > 5:
                exit_code = 1
        
        completeness = get_completeness(conn, since)
        total = completeness["total"] or 0
        if total > 0:
            missing_judge_pct = (completeness["no_judge"] or 0) / total * 100
            missing_court_pct = (completeness["no_court"] or 0) / total * 100
            missing_type_pct = (completeness["no_case_type"] or 0) / total * 100
            
            if missing_judge_pct > 10 or missing_court_pct > 10 or missing_type_pct > 10:
                exit_code = 1
        
        return exit_code
        
    finally:
        conn.close()


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Generate data quality report")
    parser.add_argument("--run-id", type=int, help="Restrict to specific ingest run ID")
    parser.add_argument("--since", type=str, help="Scope to cases filed on/after this date (YYYY-MM-DD)")
    
    args = parser.parse_args()
    
    # Validate --since format
    if args.since:
        try:
            datetime.strptime(args.since, "%Y-%m-%d")
        except ValueError:
            print(f"ERROR: Invalid date format for --since. Use YYYY-MM-DD")
            sys.exit(1)
    
    exit_code = generate_report(args.run_id, args.since)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

