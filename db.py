import os
import sqlite3
import uuid
from contextlib import closing
from typing import Optional

DB_PATH = os.getenv("FURUFLOW_DB_PATH", "furuflow.db")


def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    with closing(get_conn()) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT UNIQUE,
                email TEXT PRIMARY KEY,
                is_admin INTEGER NOT NULL DEFAULT 0,
                lifetime_access INTEGER NOT NULL DEFAULT 0,
                pro_active INTEGER NOT NULL DEFAULT 0,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                latest_checkout_session TEXT,
                subscription_status TEXT,
                purchase_source TEXT,
                provider_user_id TEXT,
                auth_provider TEXT,
                email_verified INTEGER NOT NULL DEFAULT 0,
                last_login_at TEXT,
                migrated_at TEXT,
                migrated_from_legacy INTEGER NOT NULL DEFAULT 0,
                migration_notes TEXT,
                current_session_id TEXT,
                current_session_seen_at TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # Lightweight migrations for older local DBs.
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
        migrations = [
            ("user_id", "ALTER TABLE users ADD COLUMN user_id TEXT"),
            ("stripe_subscription_id", "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT"),
            ("latest_checkout_session", "ALTER TABLE users ADD COLUMN latest_checkout_session TEXT"),
            ("subscription_status", "ALTER TABLE users ADD COLUMN subscription_status TEXT"),
            ("provider_user_id", "ALTER TABLE users ADD COLUMN provider_user_id TEXT"),
            ("auth_provider", "ALTER TABLE users ADD COLUMN auth_provider TEXT"),
            ("email_verified", "ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 0"),
            ("last_login_at", "ALTER TABLE users ADD COLUMN last_login_at TEXT"),
            ("migrated_at", "ALTER TABLE users ADD COLUMN migrated_at TEXT"),
            ("migrated_from_legacy", "ALTER TABLE users ADD COLUMN migrated_from_legacy INTEGER NOT NULL DEFAULT 0"),
            ("migration_notes", "ALTER TABLE users ADD COLUMN migration_notes TEXT"),
            ("current_session_id", "ALTER TABLE users ADD COLUMN current_session_id TEXT"),
            ("current_session_seen_at", "ALTER TABLE users ADD COLUMN current_session_seen_at TEXT"),
        ]
        for col, sql in migrations:
            if col not in existing_cols:
                conn.execute(sql)

        conn.execute(
            """
            UPDATE users
            SET auth_provider = 'legacy_email'
            WHERE auth_provider IS NULL
            """
        )

        for (email,) in conn.execute("SELECT email FROM users WHERE user_id IS NULL OR user_id = ''").fetchall():
            conn.execute("UPDATE users SET user_id = ? WHERE email = ?", (uuid.uuid4().hex, email))

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stripe_events (
                event_id TEXT PRIMARY KEY,
                event_type TEXT,
                processed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS admin_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor_user_id TEXT NOT NULL,
                target_user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                reason TEXT,
                metadata_json TEXT
            )
            """
        )

        conn.commit()


def _row_to_dict(row):
    if not row:
        return None
    columns = [
        "email", "is_admin", "lifetime_access", "pro_active",
        "stripe_customer_id", "stripe_subscription_id", "latest_checkout_session", "subscription_status",
        "purchase_source", "provider_user_id", "auth_provider", "email_verified",
        "last_login_at", "migrated_at", "migrated_from_legacy", "migration_notes",
        "current_session_id", "current_session_seen_at", "user_id",
        "created_at", "updated_at"
    ]
    data = dict(zip(columns, row))
    data["is_admin"] = bool(data["is_admin"])
    data["lifetime_access"] = bool(data["lifetime_access"])
    data["pro_active"] = bool(data["pro_active"])
    data["email_verified"] = bool(data["email_verified"])
    data["migrated_from_legacy"] = bool(data["migrated_from_legacy"])
    return data


def get_user_by_email(email: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT email, is_admin, lifetime_access, pro_active,
                   stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                   purchase_source, provider_user_id, auth_provider, email_verified,
                   last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                   current_session_id, current_session_seen_at, user_id,
                   created_at, updated_at
            FROM users
            WHERE email = ?
            """,
            (email.lower(),),
        ).fetchone()
        return _row_to_dict(row)


def get_user_by_stripe_customer_id(customer_id: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT email, is_admin, lifetime_access, pro_active,
                   stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                   purchase_source, provider_user_id, auth_provider, email_verified,
                   last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                   current_session_id, current_session_seen_at, user_id,
                   created_at, updated_at
            FROM users
            WHERE stripe_customer_id = ?
            """,
            (customer_id,),
        ).fetchone()
        return _row_to_dict(row)


def get_user_by_subscription_id(subscription_id: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT email, is_admin, lifetime_access, pro_active,
                   stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                   purchase_source, provider_user_id, auth_provider, email_verified,
                   last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                   current_session_id, current_session_seen_at, user_id,
                   created_at, updated_at
            FROM users
            WHERE stripe_subscription_id = ?
            """,
            (subscription_id,),
        ).fetchone()
        return _row_to_dict(row)


def get_user_by_user_id(user_id: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT email, is_admin, lifetime_access, pro_active,
                   stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                   purchase_source, provider_user_id, auth_provider, email_verified,
                   last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                   current_session_id, current_session_seen_at, user_id,
                   created_at, updated_at
            FROM users
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        return _row_to_dict(row)


def get_user_by_provider_user_id(provider_user_id: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT email, is_admin, lifetime_access, pro_active,
                   stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                   purchase_source, provider_user_id, auth_provider, email_verified,
                   last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                   current_session_id, current_session_seen_at, user_id,
                   created_at, updated_at
            FROM users
            WHERE provider_user_id = ?
            """,
            (provider_user_id,),
        ).fetchone()
        return _row_to_dict(row)


def upsert_user(
    email: str,
    is_admin: Optional[bool] = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    latest_checkout_session: str | None = None,
    subscription_status: str | None = None,
    purchase_source: str | None = None,
    provider_user_id: str | None = None,
    auth_provider: str | None = None,
    email_verified: bool | None = None,
    last_login_at: str | None = None,
    migrated_at: str | None = None,
    migrated_from_legacy: bool | None = None,
    migration_notes: str | None = None,
):
    email = email.lower()
    existing = get_user_by_email(email)
    with closing(get_conn()) as conn:
        if existing:
            admin_value = existing["is_admin"] if is_admin is None else is_admin
            conn.execute(
                """
                UPDATE users
                SET is_admin = ?,
                    stripe_customer_id = COALESCE(?, stripe_customer_id),
                    stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                    latest_checkout_session = COALESCE(?, latest_checkout_session),
                    subscription_status = COALESCE(?, subscription_status),
                    purchase_source = COALESCE(?, purchase_source),
                    provider_user_id = COALESCE(?, provider_user_id),
                    auth_provider = COALESCE(?, auth_provider),
                    email_verified = COALESCE(?, email_verified),
                    last_login_at = COALESCE(?, last_login_at),
                    migrated_at = COALESCE(?, migrated_at),
                    migrated_from_legacy = COALESCE(?, migrated_from_legacy),
                    migration_notes = COALESCE(?, migration_notes),
                    updated_at = CURRENT_TIMESTAMP
                WHERE email = ?
                """,
                (
                    1 if admin_value else 0,
                    stripe_customer_id,
                    stripe_subscription_id,
                    latest_checkout_session,
                    subscription_status,
                    purchase_source,
                    provider_user_id,
                    auth_provider,
                    None if email_verified is None else (1 if email_verified else 0),
                    last_login_at,
                    migrated_at,
                    None if migrated_from_legacy is None else (1 if migrated_from_legacy else 0),
                    migration_notes,
                    email,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (
                    user_id, email, is_admin, stripe_customer_id, stripe_subscription_id,
                    latest_checkout_session, subscription_status, purchase_source, provider_user_id,
                    auth_provider, email_verified, last_login_at, migrated_at,
                    migrated_from_legacy, migration_notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    email,
                    1 if bool(is_admin) else 0,
                    stripe_customer_id,
                    stripe_subscription_id,
                    latest_checkout_session,
                    subscription_status,
                    purchase_source,
                    provider_user_id,
                    auth_provider or "legacy_email",
                    1 if bool(email_verified) else 0,
                    last_login_at,
                    migrated_at,
                    1 if bool(migrated_from_legacy) else 0,
                    migration_notes,
                ),
            )
        conn.commit()
    return get_user_by_email(email)


def set_lifetime_access(email: str, value: bool = True):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET lifetime_access = ?, updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
            """,
            (1 if value else 0, email.lower()),
        )
        conn.commit()


def set_pro_active(email: str, value: bool = True):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET pro_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
            """,
            (1 if value else 0, email.lower()),
        )
        conn.commit()


def set_subscription_state(
    email: str,
    *,
    pro_active: bool,
    subscription_status: str | None = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    purchase_source: str | None = None,
):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET pro_active = ?,
                subscription_status = COALESCE(?, subscription_status),
                stripe_customer_id = COALESCE(?, stripe_customer_id),
                stripe_subscription_id = COALESCE(?, stripe_subscription_id),
                purchase_source = COALESCE(?, purchase_source),
                updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
            """,
            (
                1 if pro_active else 0,
                subscription_status,
                stripe_customer_id,
                stripe_subscription_id,
                purchase_source,
                email.lower(),
            ),
        )
        conn.commit()


def set_latest_checkout_session(user_id: str, checkout_session_id: str) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET latest_checkout_session = ?,
                purchase_source = COALESCE(purchase_source, 'stripe'),
                updated_at = CURRENT_TIMESTAMP
            WHERE user_id = ?
            """,
            (checkout_session_id, user_id),
        )
        conn.commit()


def search_users(query: str = "", limit: int = 50):
    query = (query or "").strip().lower()
    with closing(get_conn()) as conn:
        if query:
            rows = conn.execute(
                """
                SELECT email, is_admin, lifetime_access, pro_active,
                       stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                       purchase_source, provider_user_id, auth_provider, email_verified,
                       last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                       current_session_id, current_session_seen_at, user_id,
                       created_at, updated_at
                FROM users
                WHERE lower(email) LIKE ?
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (f"%{query}%", limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT email, is_admin, lifetime_access, pro_active,
                       stripe_customer_id, stripe_subscription_id, latest_checkout_session, subscription_status,
                       purchase_source, provider_user_id, auth_provider, email_verified,
                       last_login_at, migrated_at, migrated_from_legacy, migration_notes,
                       current_session_id, current_session_seen_at, user_id,
                       created_at, updated_at
                FROM users
                ORDER BY updated_at DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_row_to_dict(row) for row in rows]


def set_admin(email: str, value: bool = True):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET is_admin = ?, updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
            """,
            (1 if value else 0, email.lower()),
        )
        conn.commit()



def claim_session(email: str, session_id: str):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET current_session_id = ?,
                current_session_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE email = ?
            """,
            (session_id, email.lower()),
        )
        conn.commit()


def touch_session(email: str, session_id: str):
    with closing(get_conn()) as conn:
        conn.execute(
            """
            UPDATE users
            SET current_session_seen_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE email = ? AND current_session_id = ?
            """,
            (email.lower(), session_id),
        )
        conn.commit()


def clear_session(email: str, session_id: str | None = None):
    with closing(get_conn()) as conn:
        if session_id:
            conn.execute(
                """
                UPDATE users
                SET current_session_id = NULL,
                    current_session_seen_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE email = ? AND current_session_id = ?
                """,
                (email.lower(), session_id),
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET current_session_id = NULL,
                    current_session_seen_at = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE email = ?
                """,
                (email.lower(),),
            )
        conn.commit()


def has_processed_stripe_event(event_id: str) -> bool:
    with closing(get_conn()) as conn:
        row = conn.execute(
            "SELECT 1 FROM stripe_events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
        return row is not None


def mark_stripe_event_processed(event_id: str, event_type: str | None = None) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO stripe_events (event_id, event_type)
            VALUES (?, ?)
            """,
            (event_id, event_type),
        )
        conn.commit()


def verify_webhook_idempotency(event_id: str, event_type: str | None = None) -> bool:
    if has_processed_stripe_event(event_id):
        return False
    mark_stripe_event_processed(event_id, event_type)
    return True


def record_admin_audit(
    *,
    actor_user_id: str,
    target_user_id: str,
    action: str,
    reason: str | None = None,
    metadata_json: str | None = None,
) -> None:
    with closing(get_conn()) as conn:
        conn.execute(
            """
            INSERT INTO admin_audit_log (
                actor_user_id, target_user_id, action, reason, metadata_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (actor_user_id, target_user_id, action, reason, metadata_json),
        )
        conn.commit()


def list_admin_audit(limit: int = 50):
    with closing(get_conn()) as conn:
        rows = conn.execute(
            """
            SELECT actor_user_id, target_user_id, action, timestamp, reason, metadata_json
            FROM admin_audit_log
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "actor_user_id": row[0],
                "target_user_id": row[1],
                "action": row[2],
                "timestamp": row[3],
                "reason": row[4],
                "metadata_json": row[5],
            }
            for row in rows
        ]
