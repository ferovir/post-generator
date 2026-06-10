import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "posts.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_text TEXT NOT NULL,
            source_url TEXT DEFAULT '',
            mood TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS scheduled_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_text TEXT NOT NULL,
            publish_at TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            error TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()


# ===== Избранное =====

def add_favorite(post_text, source_url="", mood=""):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO favorites (post_text, source_url, mood) VALUES (?, ?, ?)",
        (post_text, source_url, mood),
    )
    conn.commit()
    fav_id = cur.lastrowid
    conn.close()
    return fav_id


def get_favorites():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM favorites ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_favorite(fav_id):
    conn = get_db()
    conn.execute("DELETE FROM favorites WHERE id = ?", (fav_id,))
    conn.commit()
    conn.close()


# ===== Отложенные посты =====

def add_scheduled_post(post_text, publish_at):
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO scheduled_posts (post_text, publish_at) VALUES (?, ?)",
        (post_text, publish_at),
    )
    conn.commit()
    post_id = cur.lastrowid
    conn.close()
    return post_id


def get_pending_posts():
    """Возвращает отложенные посты, которые пора публиковать."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM scheduled_posts "
        "WHERE status='pending' AND publish_at <= datetime('now','localtime')"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_scheduled():
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM scheduled_posts ORDER BY publish_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_scheduled_status(post_id, status, error=""):
    conn = get_db()
    conn.execute(
        "UPDATE scheduled_posts SET status=?, error=? WHERE id=?",
        (status, error, post_id),
    )
    conn.commit()
    conn.close()


def delete_scheduled(post_id):
    conn = get_db()
    conn.execute("DELETE FROM scheduled_posts WHERE id = ?", (post_id,))
    conn.commit()
    conn.close()
