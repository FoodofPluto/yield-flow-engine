import os
import sqlite3
from contextlib import closing

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
                purchase_source TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.commit()

def _row_to_dict(row):
    if not row:
        return None
    columns = [
        "email", "is_admin", "lifetime_access", "pro_active",
        "stripe_customer_id", "purchase_source", "created_at", "updated_at"
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
                   stripe_customer_id, purchase_source, created_at, updated_at
            FROM users
            WHERE email = ?
            """,
            (email.lower(),),
        ).fetchone()
        return _row_to_dict(row)

def upsert_user(email: str, is_admin: bool = False, stripe_customer_id: str = None, purchase_source: str = None):
    email = email.lower()
    existing = get_user_by_email(email)
    with closing(get_conn()) as conn:
        if existing:
            conn.execute(
                """
                UPDATE users
                SET is_admin = ?, 
                    stripe_customer_id = COALESCE(?, stripe_customer_id),
                    purchase_source = COALESCE(?, purchase_source),
                    updated_at = CURRENT_TIMESTAMP
                WHERE email = ?
                """,
                (1 if is_admin else 0, stripe_customer_id, purchase_source, email),
            )
        else:
            conn.execute(
                """
                INSERT INTO users (email, is_admin, stripe_customer_id, purchase_source)
                VALUES (?, ?, ?, ?)
                """,
                (email, 1 if is_admin else 0, stripe_customer_id, purchase_source),
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
