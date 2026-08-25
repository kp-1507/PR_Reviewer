import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "code_memory.db")

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    # Check if table exists and has 'sha' column
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(file_store)")
    columns = [row[1] for row in cursor.fetchall()]
    if columns and "sha" not in columns:
        cursor.execute("DROP TABLE file_store")
        conn.commit()
        
    conn.execute("""
        CREATE TABLE IF NOT EXISTS file_store (
            repo TEXT,
            filepath TEXT,
            sha TEXT,
            content TEXT,
            PRIMARY KEY (repo, filepath, sha)
        )
    """)
    conn.commit()
    return conn

def get_stored_file(repo: str, filepath: str, sha: str) -> str | None:
    """Retrieve content from the SQLite database matching a specific commit SHA."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT content FROM file_store WHERE repo=? AND filepath=? AND sha=?",
        (repo, filepath, sha)
    ).fetchone()
    conn.close()
    if row:
        return row[0]
    return None

def save_file(repo: str, filepath: str, sha: str, content: str):
    """Save or update file content for a specific commit SHA."""
    conn = _get_conn()
    conn.execute("""
        INSERT INTO file_store (repo, filepath, sha, content)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(repo, filepath, sha) DO UPDATE SET
            content = excluded.content
    """, (repo, filepath, sha, content))
    conn.commit()
    conn.close()


