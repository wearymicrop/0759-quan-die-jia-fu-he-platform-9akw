import json
import sqlite3
from contextlib import closing, contextmanager

from app.config import db_path
from app.errors import DomainError
from app.manifest import canonical


@contextmanager
def connection():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn, conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY, source TEXT NOT NULL, record TEXT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS settlements (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, record TEXT NOT NULL)""")
        yield conn


def fetch(run_id):
    with connection() as conn:
        row = conn.execute("SELECT source, record FROM runs WHERE id = ?", (run_id,)).fetchone()
    if row is None:
        raise DomainError("RUN_NOT_FOUND", "找不到该批次", 404)
    return json.loads(row[0]), json.loads(row[1])


def save(source, record):
    with connection() as conn:
        inserted = conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (record["id"], canonical(source), canonical(record)),
        ).rowcount
        kept = conn.execute("SELECT record FROM runs WHERE id = ?", (record["id"],)).fetchone()[0]
    return {**json.loads(kept), "reused": not bool(inserted)}


def publish_settlement(run_id, record):
    """同键复核单只入账一次：重试或中断恢复拿到同一份记录，不重复冲减。"""
    with connection() as conn:
        inserted = conn.execute(
            "INSERT INTO settlements VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING",
            (record["id"], run_id, canonical(record)),
        ).rowcount
        kept = conn.execute("SELECT record FROM settlements WHERE id = ?", (record["id"],)).fetchone()[0]
    return {**json.loads(kept), "reused": not bool(inserted)}


def list_settlements(run_id):
    with connection() as conn:
        rows = conn.execute(
            "SELECT record FROM settlements WHERE run_id = ? ORDER BY id", (run_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def fetch_settlement(run_id, settlement_id):
    with connection() as conn:
        row = conn.execute(
            "SELECT record FROM settlements WHERE run_id = ? AND id = ?",
            (run_id, settlement_id)).fetchone()
    if row is None:
        raise DomainError("SETTLEMENT_NOT_FOUND", "找不到该复核单", 404)
    return json.loads(row[0])
