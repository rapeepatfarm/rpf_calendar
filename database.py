"""database.py — connection pool และ helper สำหรับ PostgreSQL"""
from contextlib import contextmanager

from psycopg2 import pool
from psycopg2.extras import RealDictCursor

from config import DB_CONFIG, FARM_DB_CONFIG

_pool: pool.ThreadedConnectionPool | None = None
_farm_pool: pool.ThreadedConnectionPool | None = None


def init_pool():
    global _pool
    if _pool is None:
        _pool = pool.ThreadedConnectionPool(1, 10, **DB_CONFIG)


def close_pool():
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_conn():
    if _pool is None:
        init_pool()
    conn = _pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _pool.putconn(conn)


@contextmanager
def get_farm_conn():
    """ต่อไปยัง rpf_farm เพื่ออ่านแผนวัคซีน — อ่านอย่างเดียวเสมอ

    เปิด pool ตอนใช้ครั้งแรก เพราะโปรแกรมต้องสตาร์ตได้แม้ยังไม่ได้เปิดใช้แหล่งซิงค์
    rollback ตอนออกเสมอ transaction ที่เผลอเขียนจะได้ไม่ค้าง
    """
    global _farm_pool
    if _farm_pool is None:
        _farm_pool = pool.ThreadedConnectionPool(1, 5, **FARM_DB_CONFIG)
    conn = _farm_pool.getconn()
    try:
        yield conn
    finally:
        conn.rollback()
        _farm_pool.putconn(conn)


def fetchall(conn, sql, params=None) -> list[dict]:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def fetchone(conn, sql, params=None) -> dict | None:
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(sql, params)
        if cur.description is None:
            return None
        row = cur.fetchone()
        return dict(row) if row else None


def execute(conn, sql, params=None) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.rowcount
