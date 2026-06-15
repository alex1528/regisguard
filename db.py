import sqlite3
import os
import json

from config import DB_PATH, JSON_PATH


def get_connection():
    """Get a database connection with row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    """Initialize database tables and migrate from JSON if needed."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS domains (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            domain TEXT NOT NULL UNIQUE,
            keyword TEXT NOT NULL,
            icp_number TEXT NOT NULL DEFAULT '',
            gradient TEXT NOT NULL DEFAULT '',
            https_enabled INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    conn.commit()

    _ensure_domain_columns(conn)

    # Migrate from JSON if DB is empty and JSON exists
    count = conn.execute("SELECT COUNT(*) FROM domains").fetchone()[0]
    if count == 0 and os.path.exists(JSON_PATH):
        _migrate_from_json(conn)

    conn.close()


def _ensure_domain_columns(conn):
    """Add columns introduced after the initial SQLite schema."""
    columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(domains)").fetchall()
    }
    if "icp_number" not in columns:
        conn.execute(
            "ALTER TABLE domains ADD COLUMN icp_number TEXT NOT NULL DEFAULT ''"
        )
        conn.commit()


def _migrate_from_json(conn):
    """Migrate data from domains.json to SQLite."""
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    for item in data.get("domains", []):
        conn.execute(
            "INSERT OR IGNORE INTO domains (domain, keyword, icp_number, gradient, https_enabled) VALUES (?, ?, ?, ?, ?)",
            (
                item["domain"],
                item["keyword"],
                item.get("icp_number", ""),
                item.get("gradient", ""),
                int(item.get("https_enabled", False)),
            ),
        )

    settings = data.get("settings", {})
    for key in ("allowed_ips", "admin_password", "ssl_global_enabled", "force_https_redirect"):
        if key in settings:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                (key, str(settings[key])),
            )

    conn.commit()


# --- Domain CRUD ---

def get_all_domains():
    """Return list of domain dicts."""
    conn = get_connection()
    rows = conn.execute("SELECT id, domain, keyword, icp_number, gradient, https_enabled FROM domains ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_domain(domain, keyword, icp_number, gradient):
    """Add a new domain. Returns (success, message)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO domains (domain, keyword, icp_number, gradient, https_enabled) VALUES (?, ?, ?, ?, 0)",
            (domain, keyword, icp_number, gradient),
        )
        conn.commit()
        return True, f"Domain {domain} added"
    except sqlite3.IntegrityError:
        return False, f"Domain {domain} already exists"
    finally:
        conn.close()


def update_domain(domain_id, domain, keyword, icp_number, gradient):
    """Update a domain by ID. Returns (success, message)."""
    conn = get_connection()
    row = conn.execute("SELECT id FROM domains WHERE id = ?", (domain_id,)).fetchone()
    if not row:
        conn.close()
        return False, "Domain not found"
    conn.execute(
        "UPDATE domains SET domain = ?, keyword = ?, icp_number = ?, gradient = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (domain, keyword, icp_number, gradient, domain_id),
    )
    conn.commit()
    conn.close()
    return True, f"Domain {domain} updated"


def delete_domain(domain_id):
    """Delete a domain by ID. Returns (success, message, removed_domain)."""
    conn = get_connection()
    row = conn.execute("SELECT domain FROM domains WHERE id = ?", (domain_id,)).fetchone()
    if not row:
        conn.close()
        return False, "Domain not found", None
    removed = row["domain"]
    conn.execute("DELETE FROM domains WHERE id = ?", (domain_id,))
    conn.commit()
    conn.close()
    return True, f"Domain {removed} deleted", removed


def get_domain_by_index(index):
    """Get domain by positional index (ordered by id)."""
    conn = get_connection()
    rows = conn.execute("SELECT id, domain, keyword, icp_number, gradient, https_enabled FROM domains ORDER BY id").fetchall()
    conn.close()
    if index < 0 or index >= len(rows):
        return None
    return dict(rows[index])


def get_domain_index(domain_id):
    """Get the positional index of a domain by its ID."""
    conn = get_connection()
    rows = conn.execute("SELECT id FROM domains ORDER BY id").fetchall()
    conn.close()
    for i, row in enumerate(rows):
        if row["id"] == domain_id:
            return i
    return -1


def update_domain_https(domain_id, https_enabled):
    """Update https_enabled for a domain. Returns (success, message, domain_name)."""
    conn = get_connection()
    row = conn.execute("SELECT domain FROM domains WHERE id = ?", (domain_id,)).fetchone()
    if not row:
        conn.close()
        return False, "Domain not found", None
    domain = row["domain"]
    conn.execute(
        "UPDATE domains SET https_enabled = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (int(https_enabled), domain_id),
    )
    conn.commit()
    conn.close()
    return True, f"HTTPS {'enabled' if https_enabled else 'disabled'} for {domain}", domain


# --- Settings ---

def get_setting(key, default=""):
    """Get a setting value."""
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    """Set a setting value."""
    conn = get_connection()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()


def get_all_settings():
    """Return all settings as a dict."""
    conn = get_connection()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {r["key"]: r["value"] for r in rows}
