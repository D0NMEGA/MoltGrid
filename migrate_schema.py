#!/usr/bin/env python3
"""
MoltGrid Schema Migration: SQLite -> PostgreSQL

Reads the existing SQLite schema and creates equivalent PostgreSQL tables
with proper type translations. Uses the authoritative PostgreSQL schema
definitions from db.py._init_db_postgres().

Usage:
    python migrate_schema.py                  # Create schema in PostgreSQL
    python migrate_schema.py --verify         # Verify tables match between SQLite and PG
    python migrate_schema.py --dry-run        # Print SQL without executing
"""

import argparse
import os
import re
import sqlite3
import sys

# ─── Config ──────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("MOLTGRID_DB", "moltgrid.db")
DATABASE_URL = os.getenv("DATABASE_URL", "")


# ─── SQLite Schema Reader ────────────────────────────────────────────────────
def read_sqlite_schema(db_path):
    """Read all CREATE TABLE and CREATE INDEX statements from SQLite."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get table definitions
    cursor.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND sql IS NOT NULL ORDER BY name"
    )
    tables = cursor.fetchall()

    # Get index definitions
    cursor.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL ORDER BY name"
    )
    indexes = cursor.fetchall()

    # Get table info for verification
    table_info = {}
    for name, _ in tables:
        cursor.execute(f"PRAGMA table_info({name})")
        columns = cursor.fetchall()
        table_info[name] = columns

    conn.close()
    return tables, indexes, table_info


# ─── SQL Translation ─────────────────────────────────────────────────────────
def translate_create_table(name, sql):
    """Translate a SQLite CREATE TABLE statement to PostgreSQL syntax."""
    if sql is None:
        return None

    translated = sql

    # Add IF NOT EXISTS
    translated = re.sub(
        r"CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE TABLE IF NOT EXISTS ",
        translated,
        flags=re.IGNORECASE,
    )

    # INTEGER PRIMARY KEY AUTOINCREMENT -> SERIAL PRIMARY KEY
    # Only for uptime_checks.id and pubsub_subscriptions.id
    if name in ("uptime_checks", "pubsub_subscriptions"):
        translated = re.sub(
            r"(\w+)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
            r"\1 SERIAL PRIMARY KEY",
            translated,
            flags=re.IGNORECASE,
        )

    # REAL -> DOUBLE PRECISION (for latency_ms, reputation, importance, expires_at in admin_sessions)
    translated = re.sub(
        r"\bREAL\b",
        "DOUBLE PRECISION",
        translated,
        flags=re.IGNORECASE,
    )

    # BLOB -> BYTEA
    translated = re.sub(
        r"\bBLOB\b",
        "BYTEA",
        translated,
        flags=re.IGNORECASE,
    )

    # Remove standalone AUTOINCREMENT (shouldn't remain after SERIAL conversion)
    translated = re.sub(
        r"\bAUTOINCREMENT\b",
        "",
        translated,
        flags=re.IGNORECASE,
    )

    # Clean up any double spaces from removals
    translated = re.sub(r"  +", " ", translated)

    return translated


def translate_create_index(sql):
    """Translate a SQLite CREATE INDEX statement to PostgreSQL syntax."""
    if sql is None:
        return None

    translated = sql

    # Add IF NOT EXISTS
    translated = re.sub(
        r"CREATE\s+INDEX\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE INDEX IF NOT EXISTS ",
        translated,
        flags=re.IGNORECASE,
    )

    return translated


# ─── PostgreSQL Schema from db.py ────────────────────────────────────────────
def get_authoritative_pg_schema():
    """Return the authoritative PostgreSQL CREATE TABLE and CREATE INDEX statements.

    These are extracted from db.py _init_db_postgres() to ensure the migration
    script creates exactly the same schema that db.py would create on a fresh
    PostgreSQL database.
    """
    tables_sql = [
        """CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            api_key_hash TEXT NOT NULL,
            name TEXT,
            description TEXT,
            capabilities TEXT,
            public INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            last_seen TEXT,
            request_count INTEGER DEFAULT 0,
            available INTEGER DEFAULT 1,
            looking_for TEXT,
            busy_until TEXT,
            reputation DOUBLE PRECISION DEFAULT 0.0,
            reputation_count INTEGER DEFAULT 0,
            credits INTEGER DEFAULT 0,
            heartbeat_at TEXT,
            heartbeat_interval INTEGER DEFAULT 60,
            heartbeat_status TEXT DEFAULT 'unknown',
            heartbeat_meta TEXT,
            owner_id TEXT,
            onboarding_completed INTEGER DEFAULT 0,
            moltbook_profile_id TEXT,
            display_name TEXT,
            featured INTEGER DEFAULT 0,
            verified INTEGER DEFAULT 0,
            skills TEXT,
            interests TEXT,
            worker_status TEXT NOT NULL DEFAULT 'offline'
        )""",
        """CREATE TABLE IF NOT EXISTS memory (
            agent_id TEXT NOT NULL,
            namespace TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            visibility TEXT DEFAULT 'private',
            shared_agents TEXT,
            PRIMARY KEY (agent_id, namespace, key)
        )""",
        """CREATE TABLE IF NOT EXISTS vector_memory (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            namespace TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            text TEXT NOT NULL,
            embedding BYTEA NOT NULL,
            metadata TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            importance DOUBLE PRECISION DEFAULT 0.5,
            access_count INTEGER DEFAULT 0,
            UNIQUE(agent_id, namespace, key)
        )""",
        """CREATE TABLE IF NOT EXISTS queue (
            job_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            queue_name TEXT NOT NULL DEFAULT 'default',
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            max_attempts INTEGER DEFAULT 1,
            attempt_count INTEGER DEFAULT 0,
            retry_delay_seconds INTEGER DEFAULT 0,
            next_retry_at TEXT,
            failed_at TEXT,
            fail_reason TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS dead_letter (
            job_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            queue_name TEXT NOT NULL DEFAULT 'default',
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'failed',
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            result TEXT,
            max_attempts INTEGER DEFAULT 1,
            attempt_count INTEGER DEFAULT 0,
            retry_delay_seconds INTEGER DEFAULT 0,
            failed_at TEXT,
            fail_reason TEXT,
            moved_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS relay (
            message_id TEXT PRIMARY KEY,
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'direct',
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL,
            read_at TEXT,
            status TEXT NOT NULL DEFAULT 'accepted',
            status_updated_at TEXT,
            delivered_at TEXT,
            acted_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS dead_letter_messages (
            dl_id TEXT PRIMARY KEY,
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL,
            channel TEXT NOT NULL DEFAULT 'direct',
            payload TEXT NOT NULL,
            fail_reason TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS message_hops (
            hop_id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            hop TEXT NOT NULL,
            status TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS rate_limits (
            agent_id TEXT NOT NULL,
            window_start INTEGER NOT NULL,
            count INTEGER DEFAULT 1,
            PRIMARY KEY (agent_id, window_start)
        )""",
        """CREATE TABLE IF NOT EXISTS metrics (
            recorded_at TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            latency_ms DOUBLE PRECISION NOT NULL,
            status_code INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS webhooks (
            webhook_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            url TEXT NOT NULL,
            event_types TEXT NOT NULL,
            secret TEXT,
            created_at TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )""",
        """CREATE TABLE IF NOT EXISTS scheduled_tasks (
            task_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            cron_expr TEXT NOT NULL,
            queue_name TEXT NOT NULL DEFAULT 'default',
            payload TEXT NOT NULL,
            priority INTEGER DEFAULT 0,
            enabled INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            next_run_at TEXT NOT NULL,
            last_run_at TEXT,
            run_count INTEGER DEFAULT 0
        )""",
        """CREATE TABLE IF NOT EXISTS shared_memory (
            owner_agent TEXT NOT NULL,
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            expires_at TEXT,
            PRIMARY KEY (owner_agent, namespace, key)
        )""",
        """CREATE TABLE IF NOT EXISTS admin_sessions (
            token TEXT PRIMARY KEY,
            expires_at DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS uptime_checks (
            id SERIAL PRIMARY KEY,
            checked_at TEXT NOT NULL,
            status TEXT NOT NULL,
            response_ms DOUBLE PRECISION NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS collaborations (
            collaboration_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            partner_agent TEXT NOT NULL,
            task_type TEXT,
            outcome TEXT NOT NULL,
            rating INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS marketplace (
            task_id TEXT PRIMARY KEY,
            creator_agent TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            category TEXT,
            requirements TEXT,
            reward_credits INTEGER DEFAULT 0,
            priority INTEGER DEFAULT 0,
            estimated_effort TEXT,
            tags TEXT,
            deadline TEXT,
            status TEXT DEFAULT 'open',
            claimed_by TEXT,
            claimed_at TEXT,
            delivered_at TEXT,
            result TEXT,
            rating INTEGER,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS test_scenarios (
            scenario_id TEXT PRIMARY KEY,
            creator_agent TEXT NOT NULL,
            name TEXT,
            pattern TEXT NOT NULL,
            agent_count INTEGER NOT NULL,
            timeout_seconds INTEGER DEFAULT 60,
            success_criteria TEXT,
            status TEXT DEFAULT 'created',
            results TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS contact_submissions (
            id TEXT PRIMARY KEY,
            name TEXT,
            email TEXT NOT NULL,
            subject TEXT,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            subscription_tier TEXT DEFAULT 'free',
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            usage_count INTEGER DEFAULT 0,
            max_agents INTEGER DEFAULT 1,
            max_api_calls INTEGER DEFAULT 10000,
            created_at TEXT NOT NULL,
            last_login TEXT,
            payment_failed INTEGER DEFAULT 0,
            notification_preferences TEXT,
            known_login_ips TEXT DEFAULT '[]',
            totp_secret TEXT,
            totp_enabled INTEGER DEFAULT 0,
            totp_recovery_codes TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS email_queue (
            id TEXT PRIMARY KEY,
            to_email TEXT NOT NULL,
            subject TEXT NOT NULL,
            body_html TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL,
            sent_at TEXT,
            error TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            title TEXT,
            messages TEXT NOT NULL DEFAULT '[]',
            metadata TEXT,
            token_count INTEGER DEFAULT 0,
            max_tokens INTEGER DEFAULT 128000,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS webhook_deliveries (
            delivery_id TEXT PRIMARY KEY,
            webhook_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            attempt_count INTEGER DEFAULT 0,
            max_attempts INTEGER DEFAULT 3,
            next_retry_at TEXT,
            last_error TEXT,
            created_at TEXT NOT NULL,
            delivered_at TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS pubsub_subscriptions (
            id SERIAL PRIMARY KEY,
            agent_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            subscribed_at TEXT NOT NULL,
            UNIQUE(agent_id, channel)
        )""",
        """CREATE TABLE IF NOT EXISTS password_resets (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS analytics_events (
            id TEXT PRIMARY KEY,
            event_name TEXT NOT NULL,
            user_id TEXT,
            agent_id TEXT,
            metadata TEXT,
            created_at TEXT NOT NULL,
            source TEXT DEFAULT 'moltgrid_api',
            moltbook_url TEXT
        )""",
        """CREATE TABLE IF NOT EXISTS memory_access_log (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            namespace TEXT NOT NULL,
            key TEXT NOT NULL,
            action TEXT NOT NULL,
            actor_agent_id TEXT,
            actor_user_id TEXT,
            old_visibility TEXT,
            new_visibility TEXT,
            authorized INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS audit_logs (
            log_id TEXT PRIMARY KEY,
            user_id TEXT,
            agent_id TEXT,
            action TEXT NOT NULL,
            details TEXT,
            ip_address TEXT,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS templates (
            template_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            category TEXT,
            starter_code TEXT,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS organizations (
            org_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            slug TEXT UNIQUE,
            owner_user_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS org_members (
            org_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            joined_at TEXT NOT NULL,
            PRIMARY KEY (org_id, user_id)
        )""",
        """CREATE TABLE IF NOT EXISTS agent_events (
            event_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL DEFAULT '{}',
            acknowledged INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS obstacle_course_submissions (
            submission_id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            stages_completed TEXT NOT NULL DEFAULT '[]',
            score INTEGER NOT NULL DEFAULT 0,
            submitted_at TEXT NOT NULL,
            feedback TEXT NOT NULL DEFAULT ''
        )""",
        """CREATE TABLE IF NOT EXISTS integrations (
            id TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            config TEXT,
            status TEXT DEFAULT 'active',
            created_at TEXT NOT NULL
        )""",
    ]

    indexes_sql = [
        "CREATE INDEX IF NOT EXISTS idx_vec_agent ON vector_memory(agent_id, namespace)",
        "CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(queue_name, status, priority DESC)",
        "CREATE INDEX IF NOT EXISTS idx_dlq_agent ON dead_letter(agent_id, queue_name)",
        "CREATE INDEX IF NOT EXISTS idx_relay_to ON relay(to_agent, read_at)",
        "CREATE INDEX IF NOT EXISTS idx_dlm_from ON dead_letter_messages(from_agent)",
        "CREATE INDEX IF NOT EXISTS idx_hops_msg ON message_hops(message_id, recorded_at)",
        "CREATE INDEX IF NOT EXISTS idx_webhooks_agent ON webhooks(agent_id, active)",
        "CREATE INDEX IF NOT EXISTS idx_sched_next ON scheduled_tasks(enabled, next_run_at)",
        "CREATE INDEX IF NOT EXISTS idx_shared_ns ON shared_memory(namespace)",
        "CREATE INDEX IF NOT EXISTS idx_uptime_at ON uptime_checks(checked_at)",
        "CREATE INDEX IF NOT EXISTS idx_collab_partner ON collaborations(partner_agent)",
        "CREATE INDEX IF NOT EXISTS idx_collab_agent ON collaborations(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_market_status ON marketplace(status, category)",
        "CREATE INDEX IF NOT EXISTS idx_market_creator ON marketplace(creator_agent)",
        "CREATE INDEX IF NOT EXISTS idx_market_claimed ON marketplace(claimed_by)",
        "CREATE INDEX IF NOT EXISTS idx_scenarios_creator ON test_scenarios(creator_agent)",
        "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)",
        "CREATE INDEX IF NOT EXISTS idx_users_stripe ON users(stripe_customer_id)",
        "CREATE INDEX IF NOT EXISTS idx_email_queue_status ON email_queue(status, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_agent ON sessions(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_webhook_del_status ON webhook_deliveries(status, next_retry_at)",
        "CREATE INDEX IF NOT EXISTS idx_pubsub_channel ON pubsub_subscriptions(channel)",
        "CREATE INDEX IF NOT EXISTS idx_analytics_event ON analytics_events(event_name, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_mal_agent ON memory_access_log(agent_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_user ON audit_logs(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_integrations_agent ON integrations(agent_id)",
        "CREATE INDEX IF NOT EXISTS idx_org_members_user ON org_members(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_agent_events_agent_ack_time ON agent_events(agent_id, acknowledged, created_at)",
    ]

    return tables_sql, indexes_sql


# ─── Schema Creation ─────────────────────────────────────────────────────────
def create_schema(dry_run=False):
    """Create all PostgreSQL tables and indexes.

    Uses the authoritative schema from db.py (not translation from SQLite)
    to ensure exact match with what the application expects.
    """
    tables_sql, indexes_sql = get_authoritative_pg_schema()

    if dry_run:
        print("-- DRY RUN: PostgreSQL schema migration")
        print("-- Tables to create: %d" % len(tables_sql))
        print("-- Indexes to create: %d" % len(indexes_sql))
        print()
        for sql in tables_sql:
            # Extract table name
            match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
            table_name = match.group(1) if match else "unknown"
            print("-- Table: %s" % table_name)
            print(sql.strip() + ";")
            print()
        for sql in indexes_sql:
            print(sql.strip() + ";")
        print()
        print("-- Schema migration complete: %d tables, %d indexes" % (len(tables_sql), len(indexes_sql)))
        return

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    import psycopg

    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    try:
        table_count = 0
        for sql in tables_sql:
            match = re.search(r"CREATE TABLE IF NOT EXISTS (\w+)", sql)
            table_name = match.group(1) if match else "unknown"
            conn.execute(sql)
            print("Created table: %s" % table_name)
            table_count += 1

        for sql in indexes_sql:
            conn.execute(sql)

        print()
        print("Schema migration complete: %d tables created, %d indexes created" % (table_count, len(indexes_sql)))
    except Exception as e:
        print("ERROR: Schema migration failed: %s" % e)
        sys.exit(1)
    finally:
        conn.close()


# ─── Verification ─────────────────────────────────────────────────────────────
def verify_schema():
    """Compare table names and column counts between SQLite and PostgreSQL."""
    if not os.path.exists(DB_PATH):
        print("ERROR: SQLite database not found at %s" % DB_PATH)
        sys.exit(1)

    if not DATABASE_URL:
        print("ERROR: DATABASE_URL environment variable not set")
        sys.exit(1)

    import psycopg
    from psycopg.rows import dict_row

    # Get SQLite tables and columns
    sqlite_conn = sqlite3.connect(DB_PATH)
    sqlite_cursor = sqlite_conn.cursor()
    sqlite_cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    sqlite_tables = {row[0] for row in sqlite_cursor.fetchall()}

    sqlite_info = {}
    for table in sorted(sqlite_tables):
        sqlite_cursor.execute("PRAGMA table_info(%s)" % table)
        cols = sqlite_cursor.fetchall()
        sqlite_info[table] = len(cols)
    sqlite_conn.close()

    # Get PostgreSQL tables and columns
    pg_conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
    try:
        cursor = pg_conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
        pg_tables = {row["table_name"] for row in cursor.fetchall()}

        pg_info = {}
        for table in sorted(pg_tables):
            cursor = pg_conn.execute(
                "SELECT COUNT(*) as cnt FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s",
                (table,),
            )
            pg_info[table] = cursor.fetchone()["cnt"]
    finally:
        pg_conn.close()

    # Compare
    all_tables = sorted(sqlite_tables | pg_tables)
    mismatches = 0

    print("Schema Verification: SQLite vs PostgreSQL")
    print("-" * 60)
    print("%-30s %10s %10s %s" % ("Table", "SQLite", "PG", "Status"))
    print("-" * 60)

    for table in all_tables:
        s_cols = sqlite_info.get(table, "-")
        p_cols = pg_info.get(table, "-")

        if table not in sqlite_tables:
            status = "PG only"
            mismatches += 1
        elif table not in pg_tables:
            status = "MISSING in PG"
            mismatches += 1
        elif s_cols != p_cols:
            # Column count mismatch is expected for migrated tables
            # (PG has all columns from start, SQLite may have fewer before ALTER)
            status = "col diff (%s vs %s)" % (s_cols, p_cols)
        else:
            status = "OK"

        print("%-30s %10s %10s %s" % (table, s_cols, p_cols, status))

    print("-" * 60)
    print("SQLite tables: %d | PostgreSQL tables: %d" % (len(sqlite_tables), len(pg_tables)))

    if mismatches > 0:
        print("WARNING: %d table(s) with issues" % mismatches)
        sys.exit(1)
    else:
        print("All tables present in both databases")


# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="MoltGrid Schema Migration: SQLite -> PostgreSQL"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify tables match between SQLite and PostgreSQL",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL without executing",
    )

    args = parser.parse_args()

    if args.verify:
        verify_schema()
    else:
        create_schema(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
