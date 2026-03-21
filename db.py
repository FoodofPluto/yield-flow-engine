import os
import sqlite3
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
                email TEXT PRIMARY KEY,
                is_admin INTEGER NOT NULL DEFAULT 0,
                lifetime_access INTEGER NOT NULL DEFAULT 0,
                pro_active INTEGER NOT NULL DEFAULT 0,
                stripe_customer_id TEXT,
                stripe_subscription_id TEXT,
                subscription_status TEXT,
                purchase_source TEXT,
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
            ("stripe_subscription_id", "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT"),
            ("subscription_status", "ALTER TABLE users ADD COLUMN subscription_status TEXT"),
            ("current_session_id", "ALTER TABLE users ADD COLUMN current_session_id TEXT"),
            ("current_session_seen_at", "ALTER TABLE users ADD COLUMN current_session_seen_at TEXT"),
        ]
        for col, sql in migrations:
            if col not in existing_cols:
                conn.execute(sql)

        conn.commit()


def _row_to_dict(row):
    if not row:
        return None
    columns = [
        "email", "is_admin", "lifetime_access", "pro_active",
        "stripe_customer_id", "stripe_subscription_id", "subscription_status",
        "purchase_source", "current_session_id", "current_session_seen_at",
        "created_at", "updated_at"
    ]
    data = dict(zip(columns, row))
    data["is_admin"] = bool(data["is_admin"])
    data["lifetime_access"] = bool(data["lifetime_access"])
    data["pro_active"] = bool(data["pro_active"])
    return data


def get_user_by_email(email: str):
    with closing(get_conn()) as conn:
        row = conn.execute(
            """
            SELECT email, is_admin, lifetime_access, pro_active,
                   stripe_customer_id, stripe_subscription_id, subscription_status,
                   purchase_source, current_session_id, current_session_seen_at,
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
                   stripe_customer_id, stripe_subscription_id, subscription_status,
                   purchase_source, current_session_id, current_session_seen_at,
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
                   stripe_customer_id, stripe_subscription_id, subscription_status,
                   purchase_source, current_session_id, current_session_seen_at,
                   created_at, updated_at
            FROM users
            WHERE stripe_subscription_id = ?
            """,
            (subscription_id,),
        ).fetchone()
        return _row_to_dict(row)


def upsert_user(
    email: str,
    is_admin: Optional[bool] = None,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
    subscription_status: str | None = None,
    purchase_source: str | None = None,
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
                    subscription_status = COALESCE(?, subscription_status),
                    purchase_source = COALESCE(?, purchase_source),
                    updated_at = CURRENT_TIMESTAMP
                WHERE email = ?
                """,
                (
                    1 if admin_value else 0,
                    stripe_customer_id,
                    stripe_subscription_id,
                    subscription_status,
                    purchase_source,
                    email,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (
                    email, is_admin, stripe_customer_id, stripe_subscription_id,
                    subscription_status, purchase_source
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    email,
                    1 if bool(is_admin) else 0,
                    stripe_customer_id,
                    stripe_subscription_id,
                    subscription_status,
                    purchase_source,
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


def search_users(query: str = "", limit: int = 50):
    query = (query or "").strip().lower()
    with closing(get_conn()) as conn:
        if query:
            rows = conn.execute(
                """
                SELECT email, is_admin, lifetime_access, pro_active,
                       stripe_customer_id, stripe_subscription_id, subscription_status,
                       purchase_source, current_session_id, current_session_seen_at,
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
                       stripe_customer_id, stripe_subscription_id, subscription_status,
                       purchase_source, current_session_id, current_session_seen_at,
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
