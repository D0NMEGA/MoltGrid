#!/usr/bin/env python3
"""
MoltGrid Data Migration: SQLite -> PostgreSQL

Copies all data from the SQLite database to PostgreSQL with proper type
conversions. Handles BLOB-to-BYTEA for vector_memory embeddings, resets
SERIAL sequences for autoincrement tables, and verifies row counts.

Usage:
    python migrate_data.py                   # Migrate all data
    python migrate_data.py --verify          # Verify row counts match
    python migrate_data.py --table agents    # Migrate single table
    python migrate_data.py --dry-run         # Print what would be migrated
    python migrate_data.py --force           # Truncate target tables before insert
"""

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

# ─── Config ──────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("MOLTGRID_DB", "moltgrid.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")

# Tables with SERIAL PRIMARY KEY (need sequence reset after insert)
SERIAL_TABLES = {"uptime_checks", "pubsub_subscriptions"}

# Columns that need BLOB -> bytes conversion for BYTEA
BYTEA_COLUMNS = {
    "vector_memory": {"embedding"},
}

# Batch size for executemany inserts
BATCH_SIZE = 500


# ─── Helpers ──────────────────────────────────────────────────────────────────
def get_sqlite_tables(sqlite_conn):
    """Get all user table names from SQLite, sorted alphabetically."""
    cursor = sqlite_conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    return [row[0] for row in cursor.fetchall()]


def get_sqlite_columns(sqlite_conn, table_name):
    """Get column names for a SQLite table in order."""
    cursor = sqlite_conn.cursor()
    cursor.execute("PRAGMA table_info(%s)" % table_name)
    return [row[1] for row in cursor.fetchall()]


def get_pg_columns(pg_conn, table_name):
    """Get column names for a PostgreSQL table in order."""
    cursor = pg_conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s "
        "ORDER BY ordinal_position",
        (table_name,),
    )
    return [row[0] for row in cursor.fetchall()]


def convert_row(table_name, columns, row):
    """Apply type conversions to a row before inserting into PostgreSQL.

    - BLOB columns in vector_memory.embedding: ensure bytes type for BYTEA
    - All other columns: pass through as-is
    """
    bytea_cols = BYTEA_COLUMNS.get(table_name, set())
    if not bytea_cols:
        return row

    converted = list(row)
    for i, col in enumerate(columns):
        if col in bytea_cols and converted[i] is not None:
            # Ensure the value is bytes for PostgreSQL BYTEA
            val = converted[i]
            if isinstance(val, memoryview):
                converted[i] = bytes(val)
            elif not isinstance(val, bytes):
                converted[i] = bytes(val)
    return tuple(converted)


def pg_row_count(pg_conn, table_name):
    """Get row count from a PostgreSQL table."""
    cursor = pg_conn.execute("SELECT COUNT(*) FROM %s" % table_name)
    return cursor.fetchone()[0]


def sqlite_row_count(sqlite_conn, table_name):
    """Get row count from a SQLite table."""
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM %s" % table_name)
    return cursor.fetchone()[0]


# ─── Migration ────────────────────────────────────────────────────────────────
def migrate_table(sqlite_conn, pg_conn, table_name, force=False):
    """Migrate a single table from SQLite to PostgreSQL.

    Returns the number of rows migrated.
    """
    # Check if target table already has rows
    existing_count = pg_row_count(pg_conn, table_name)
    if existing_count > 0 and not force:
        print("Skipped %s: already has %d rows (use --force to overwrite)" % (table_name, existing_count))
        return 0

    if existing_count > 0 and force:
        pg_conn.execute("DELETE FROM %s" % table_name)
        print("Truncated %s: removed %d existing rows" % (table_name, existing_count))

    # Get column info
    sqlite_cols = get_sqlite_columns(sqlite_conn, table_name)
    pg_cols = get_pg_columns(pg_conn, table_name)

    # Use intersection of columns (in SQLite column order) to handle
    # cases where PG has extra columns with defaults
    common_cols = [c for c in sqlite_cols if c in pg_cols]

    if not common_cols:
        print("WARNING: No common columns for %s, skipping" % table_name)
        return 0

    # Read all rows from SQLite
    col_list = ", ".join(common_cols)
    cursor = sqlite_conn.cursor()
    cursor.execute("SELECT %s FROM %s" % (col_list, table_name))
    rows = cursor.fetchall()

    if not rows:
        print("Migrated %s: 0 rows (empty)" % table_name)
        return 0

    # Build INSERT statement with %s placeholders for psycopg
    placeholders = ", ".join(["%s"] * len(common_cols))
    insert_sql = "INSERT INTO %s (%s) VALUES (%s)" % (table_name, col_list, placeholders)

    # Convert rows and batch insert
    converted_rows = [convert_row(table_name, common_cols, row) for row in rows]

    # Insert in batches using cursor (psycopg3 requires cursor for executemany)
    cur = pg_conn.cursor()
    for i in range(0, len(converted_rows), BATCH_SIZE):
        batch = converted_rows[i : i + BATCH_SIZE]
        cur.executemany(insert_sql, batch)

    count = len(converted_rows)
    print("Migrated %s: %d rows" % (table_name, count))
    return count


def reset_serial_sequences(pg_conn):
    """Reset SERIAL sequences for tables with autoincrement PKs."""
    for table_name in SERIAL_TABLES:
        try:
            pg_conn.execute(
                "SELECT setval(pg_get_serial_sequence('%s', 'id'), "
                "COALESCE((SELECT MAX(id) FROM %s), 0) + 1, false)"
                % (table_name, table_name)
            )
            print("Reset sequence for %s" % table_name)
        except Exception as e:
            print("WARNING: Could not reset sequence for %s: %s" % (table_name, e))


# ─── Dry Run ──────────────────────────────────────────────────────────────────
def dry_run(table_filter=None):
    """Print what would be migrated without writing anything."""
    if not os.path.exists(DB_PATH):
        print("ERROR: SQLite database not found at %s" % DB_PATH)
        sys.exit(1)

    sqlite_conn = sqlite3.connect(DB_PATH)
    tables = get_sqlite_tables(sqlite_conn)

    if table_filter:
        tables = [t for t in tables if t == table_filter]
        if not tables:
            print("ERROR: Table '%s' not found in SQLite database" % table_filter)
            sqlite_conn.close()
            sys.exit(1)

    print("DRY RUN: Data migration plan")
    print("Source: %s" % DB_PATH)
    print("Target: PostgreSQL (DATABASE_URL)")
    print("-" * 50)
    print("%-30s %10s %s" % ("Table", "Rows", "Notes"))
    print("-" * 50)

    total_rows = 0
    for table in tables:
        count = sqlite_row_count(sqlite_conn, table)
        total_rows += count
        notes = []
        if table in SERIAL_TABLES:
            notes.append("SERIAL seq reset")
        if table in BYTEA_COLUMNS:
            notes.append("BLOB->BYTEA")
        note_str = ", ".join(notes) if notes else ""
        print("%-30s %10d %s" % (table, count, note_str))

    print("-" * 50)
    print("Total: %d tables, %d rows" % (len(tables), total_rows))
    sqlite_conn.close()


# ─── Verification ─────────────────────────────────────────────────────────────
def verify():
    """Compare row counts between SQLite and PostgreSQL for every table."""
    if not os.path.exists(DB_PATH):
        print("ERROR: SQLite database not found at %s" % DB_PATH)
        sys.exit(1)

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    import psycopg

    sqlite_conn = sqlite3.connect(DB_PATH)
    pg_conn = psycopg.connect(DATABASE_URL)

    try:
        tables = get_sqlite_tables(sqlite_conn)

        print("Data Verification: SQLite vs PostgreSQL")
        print("-" * 60)
        print("%-30s %10s %10s %s" % ("Table", "SQLite", "PG", "Status"))
        print("-" * 60)

        mismatches = 0
        total_sqlite = 0
        total_pg = 0

        for table in tables:
            s_count = sqlite_row_count(sqlite_conn, table)
            total_sqlite += s_count

            try:
                p_count = pg_row_count(pg_conn, table)
                total_pg += p_count
            except Exception:
                p_count = "-"
                mismatches += 1

            if isinstance(p_count, int) and s_count == p_count:
                status = "OK"
            elif isinstance(p_count, int):
                status = "MISMATCH"
                mismatches += 1
            else:
                status = "TABLE MISSING"

            print("%-30s %10d %10s %s" % (table, s_count, str(p_count), status))

        print("-" * 60)
        print("SQLite total: %d rows | PostgreSQL total: %d rows" % (total_sqlite, total_pg))

        if mismatches > 0:
            print("FAILED: %d table(s) with mismatches" % mismatches)
            sys.exit(1)
        else:
            print("PASSED: All row counts match")

    finally:
        sqlite_conn.close()
        pg_conn.close()


# ─── Full Migration ──────────────────────────────────────────────────────────
def migrate(table_filter=None, force=False):
    """Migrate all (or one) table from SQLite to PostgreSQL."""
    if not os.path.exists(DB_PATH):
        print("ERROR: SQLite database not found at %s" % DB_PATH)
        sys.exit(1)

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    import psycopg

    start_time = time.time()
    start_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    print("Data migration started at %s" % start_ts)
    print("Source: %s" % DB_PATH)
    print("Target: PostgreSQL")
    print()

    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_conn.row_factory = None  # We want tuples, not Row objects

    pg_conn = psycopg.connect(DATABASE_URL, autocommit=False)

    try:
        tables = get_sqlite_tables(sqlite_conn)

        if table_filter:
            tables = [t for t in tables if t == table_filter]
            if not tables:
                print("ERROR: Table '%s' not found in SQLite database" % table_filter)
                sys.exit(1)

        total_rows = 0
        for table in tables:
            rows = migrate_table(sqlite_conn, pg_conn, table, force=force)
            total_rows += rows

        # Reset SERIAL sequences
        if not table_filter or table_filter in SERIAL_TABLES:
            reset_serial_sequences(pg_conn)

        # Commit the entire migration
        pg_conn.commit()

        elapsed = time.time() - start_time
        end_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        print()
        print("Data migration complete at %s" % end_ts)
        print("Total: %d tables, %d rows migrated in %.1f seconds" % (len(tables), total_rows, elapsed))

    except Exception as e:
        pg_conn.rollback()
        print()
        print("ERROR: Migration failed, all changes rolled back: %s" % e)
        sys.exit(1)
    finally:
        sqlite_conn.close()
        pg_conn.close()


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="MoltGrid Data Migration: SQLite -> PostgreSQL"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify row counts match between SQLite and PostgreSQL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be migrated without writing",
    )
    parser.add_argument(
        "--table",
        type=str,
        default=None,
        help="Migrate a single table by name",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Truncate target tables before inserting (overwrite existing data)",
    )

    args = parser.parse_args()

    if args.verify:
        verify()
    elif args.dry_run:
        dry_run(table_filter=args.table)
    else:
        migrate(table_filter=args.table, force=args.force)


if __name__ == "__main__":
    main()
