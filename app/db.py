"""การเชื่อมต่อ SQLite, Schema Migration และข้อมูลเริ่มต้น."""
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from app import config
from app.timecalc import parse_time

MASTER_KINDS = ("machine", "size", "problem", "corrective", "person")  # problem/corrective: ไม่ใช้ตั้งแต่ v1.2 (เก็บข้อมูลไว้)

_V1_SQL = """
    CREATE TABLE settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );

    CREATE TABLE master_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        kind       TEXT NOT NULL CHECK (kind IN ('machine','stop','size','problem','corrective','person')),
        name       TEXT NOT NULL,
        sort_order INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        UNIQUE (kind, name)
    );

    CREATE TABLE daily_output (
        date       TEXT PRIMARY KEY,
        target     INTEGER CHECK (target IS NULL OR target >= 0),
        output     INTEGER CHECK (output IS NULL OR output >= 0),
        updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        type        TEXT NOT NULL CHECK (type IN ('problem','improve','stop')),
        time_from   TEXT NOT NULL,
        time_to     TEXT NOT NULL,
        hours       REAL NOT NULL,
        shift       TEXT NOT NULL CHECK (shift IN ('M','N')),
        size        TEXT NOT NULL DEFAULT '',
        machine     TEXT NOT NULL,
        problem     TEXT NOT NULL,
        corrective  TEXT NOT NULL DEFAULT '',
        due_date    TEXT,
        responsible TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'done' CHECK (status IN ('open','done')),
        created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX idx_events_date ON events(date);
    """

_V2_SQL = """
    ALTER TABLE events ADD COLUMN stop_line INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE events ADD COLUMN end_date TEXT;
    CREATE TABLE attachments (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id     INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        orig_name    TEXT NOT NULL,
        stored_name  TEXT NOT NULL UNIQUE,
        size_bytes   INTEGER NOT NULL,
        created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX idx_attachments_event ON attachments(event_id);
"""


def _run_sql(conn: sqlite3.Connection, sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            conn.execute(statement)


def _migrate_v1(conn: sqlite3.Connection) -> None:
    _run_sql(conn, _V1_SQL)
    _seed(conn)


def _migrate_v2(conn: sqlite3.Connection) -> None:
    """v1.1: ไฟล์แนบ + Stop Line (ระบุวันที่เริ่ม-สิ้นสุด) และยุบประเภท "หยุดตามแผน" เข้าประเภทปัญหา."""
    _run_sql(conn, _V2_SQL)
    rows = conn.execute("SELECT id, date, time_from, time_to, machine FROM events WHERE type = 'stop'").fetchall()
    for r in rows:
        if r["machine"].strip().upper() == "STOP LINE":
            start, end = parse_time(r["time_from"]), parse_time(r["time_to"])
            # รายการเดิมข้ามเที่ยงคืนได้ → วันที่สิ้นสุดคือวันถัดไป (ชั่วโมงเท่าเดิม)
            end_date = date.fromisoformat(r["date"]) + timedelta(days=1 if end < start else 0)
            conn.execute(
                "UPDATE events SET type = 'problem', stop_line = 1, machine = '', end_date = ? WHERE id = ?",
                (end_date.isoformat(), r["id"]),
            )
        else:
            conn.execute("UPDATE events SET type = 'problem' WHERE id = ?", (r["id"],))
    # MONDAY Cleaning / Change Size → ตัวเลือกในช่องเครื่องจักร, STOP LINE → ปุ่ม Stop Line
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM master_items WHERE kind = 'machine'"
    ).fetchone()[0]
    for r in conn.execute("SELECT name FROM master_items WHERE kind = 'stop' ORDER BY sort_order").fetchall():
        if r["name"].strip().upper() != "STOP LINE":
            conn.execute(
                "INSERT OR IGNORE INTO master_items(kind, name, sort_order) VALUES ('machine', ?, ?)",
                (r["name"], next_order),
            )
            next_order += 1
    conn.execute("DELETE FROM master_items WHERE kind = 'stop'")


_EVENT_COLS_V3 = ("id, date, type, stop_line, end_date, time_from, time_to, hours, shift, size, machine, problem, "
                  "corrective, due_date, responsible, status, created_at, updated_at")

_V3_SQL = """
    CREATE TABLE events_v3 (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        date        TEXT NOT NULL,
        type        TEXT NOT NULL CHECK (type IN ('problem','improve')),
        stop_line   INTEGER NOT NULL DEFAULT 0,
        end_date    TEXT,
        time_from   TEXT,
        time_to     TEXT,
        hours       REAL NOT NULL,
        shift       TEXT CHECK (shift IS NULL OR shift IN ('M','N')),
        size        TEXT NOT NULL DEFAULT '',
        machine     TEXT NOT NULL DEFAULT '',
        problem     TEXT NOT NULL,
        corrective  TEXT NOT NULL DEFAULT '',
        due_date    TEXT,
        responsible TEXT NOT NULL DEFAULT '',
        status      TEXT CHECK (status IS NULL OR status IN ('done','pending','in_progress')),
        created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
    );
"""


def _migrate_v3(conn: sqlite3.Connection) -> None:
    """v1.2: Stop Line ไม่มีเวลา/กะ (NULL ได้), สถานะงานปรับปรุง 3 ค่า ('open' → 'pending').

    ข้อมูลเดิม (เวลา/กะ/Size ของ Stop Line, กำหนดเสร็จ/ผู้รับผิดชอบ/สถานะของปัญหา) เก็บไว้ครบ แค่ไม่แสดง
    สร้างตารางใหม่ตามขั้นตอนของ SQLite (ต้องปิด foreign_keys ก่อนเริ่ม transaction — ดู migrate())
    """
    _run_sql(conn, _V3_SQL)
    cols = _EVENT_COLS_V3
    select = cols.replace("status", "CASE status WHEN 'open' THEN 'pending' ELSE status END")
    conn.execute(f"INSERT INTO events_v3 ({cols}) SELECT {select} FROM events")
    conn.execute("DROP TABLE events")
    conn.execute("ALTER TABLE events_v3 RENAME TO events")
    conn.execute("CREATE INDEX idx_events_date ON events(date)")


def _migrate_v4(conn: sqlite3.Connection) -> None:
    """v1.5: วันหยุด (ผู้ใช้เลือกเองได้อิสระ) — ข้อมูลเดิมทุกวัน = ไม่ใช่วันหยุด."""
    conn.execute("ALTER TABLE daily_output ADD COLUMN holiday INTEGER NOT NULL DEFAULT 0")


# v1.7: ชื่อเครื่องจักรจริงของ Line T14 ที่ยังไม่มีใน Master (ผู้ใช้อนุมัติให้เพิ่ม)
V5_MACHINES = ("Trim", "Aneal", "IBO", "Base", "DO-BC", "DO-PT", "Accu.", "Pack")


def _migrate_v5(conn: sqlite3.Connection) -> None:
    """v1.7: เพิ่มชื่อเครื่องจักรต่อท้าย Master — เพิ่มเฉพาะชื่อที่ยังไม่มี (ไม่สนตัวพิมพ์เล็ก/ใหญ่), ไม่ลบ/แก้ของเดิม."""
    existing = {r["name"].strip().lower() for r in
                conn.execute("SELECT name FROM master_items WHERE kind = 'machine'").fetchall()}
    next_order = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM master_items WHERE kind = 'machine'"
    ).fetchone()[0]
    for name in V5_MACHINES:
        if name.lower() not in existing:
            conn.execute("INSERT INTO master_items(kind, name, sort_order) VALUES ('machine', ?, ?)", (name, next_order))
            next_order += 1


# v1.9: ลำดับเครื่องจักรจริงของ Line (ผู้ใช้กำหนด) + ชื่อที่ไม่ใช้แล้ว (ผู้ใช้สั่งลบออกจาก Master)
V6_MACHINE_ORDER = ("Press", "Trim", "Aneal", "Inside", "IBO", "Base", "DO-BC", "Print", "DO-PT", "Cap", "Latex", "Accu.", "Pack")
V6_REMOVE_MACHINES = ("Inside Coat", "MONDAY Cleaning", "Change Size")


def _migrate_v6(conn: sqlite3.Connection) -> None:
    """v1.9: รายการคิดชั่วโมงจากยอดผลิต (เป้า/ชม. + ผลิตได้จริงแต่ละชั่วโมง) และจัด Master เครื่องจักรตามลำดับจริง.

    รายการที่บันทึกไว้แล้วไม่เปลี่ยน (เก็บชื่อเครื่องเป็นข้อความ) — ลบเฉพาะตัวเลือกใน Master
    """
    conn.execute("ALTER TABLE events ADD COLUMN rate_target INTEGER")
    conn.execute("ALTER TABLE events ADD COLUMN rate_actuals TEXT")  # JSON เช่น "[4500, 3000]"
    for name in V6_REMOVE_MACHINES:
        conn.execute("DELETE FROM master_items WHERE kind = 'machine' AND lower(name) = lower(?)", (name,))
    rows = conn.execute("SELECT id, name FROM master_items WHERE kind = 'machine' ORDER BY sort_order, id").fetchall()
    by_name = {r["name"].strip().lower(): r["id"] for r in rows}
    for name in V6_MACHINE_ORDER:
        if name.lower() not in by_name:
            by_name[name.lower()] = conn.execute(
                "INSERT INTO master_items(kind, name, sort_order) VALUES ('machine', ?, 0)", (name,)).lastrowid
    # ตามลำดับจริงก่อน แล้วต่อด้วยชื่ออื่นที่ผู้ใช้เพิ่มเอง (ลำดับเดิม)
    ordered = [by_name[n.lower()] for n in V6_MACHINE_ORDER]
    ordered += [r["id"] for r in rows if r["id"] not in ordered]
    for i, item_id in enumerate(ordered):
        conn.execute("UPDATE master_items SET sort_order = ? WHERE id = ?", (i, item_id))


def _migrate_v7(conn: sqlite3.Connection) -> None:
    """v1.10: หยุดตามแผน Monday Cleaning (บันทึกอย่างเดียว ไม่นับชั่วโมง/กราฟ) — `events.planned_stop`.

    รายการเดิมที่บันทึกเป็นปัญหาเครื่องจักรด้วยชื่อเครื่อง "MONDAY Cleaning" (ไม่สนตัวพิมพ์) → Monday Cleaning
    (ผู้ใช้อนุมัติ 1.1) ช่องเครื่องจักรว่าง (= ทั้ง Line), ข้อความ/เวลา/ชั่วโมง/ไฟล์แนบเดิมไม่เปลี่ยน
    ไม่แปลง: Stop Line, งานปรับปรุง, รายการคิดจากยอดผลิต
    """
    conn.execute("ALTER TABLE events ADD COLUMN planned_stop TEXT")
    conn.execute(
        "UPDATE events SET planned_stop = 'cleaning', machine = '' "
        "WHERE type = 'problem' AND stop_line = 0 AND rate_actuals IS NULL AND time_from IS NOT NULL "
        "AND lower(trim(machine)) = 'monday cleaning'"
    )


# Migration แต่ละเวอร์ชัน — เพิ่มต่อท้ายเท่านั้น ห้ามแก้ของเดิม
_MIGRATIONS = {1: _migrate_v1, 2: _migrate_v2, 3: _migrate_v3, 4: _migrate_v4, 5: _migrate_v5, 6: _migrate_v6,
               7: _migrate_v7}

SCHEMA_VERSION = max(_MIGRATIONS)

REQUIRED_TABLES = {"settings", "master_items", "daily_output", "events"}  # มีในทุกเวอร์ชัน

DEFAULT_SETTINGS = {
    "line_name": "T14",
    "default_target": "",
    "morning_start": "06.00",
    "night_start": "18.00",
}

DEFAULT_MASTER = {
    "machine": ["Press", "Latex", "Print", "Inside Coat", "Cap"],
    "stop": ["STOP LINE", "MONDAY Cleaning", "Change Size"],
    "size": ["34.92", "28"],
}


def connect(path: Path | None = None) -> sqlite3.Connection:
    # check_same_thread=False: FastAPI อาจเปิด connection (dependency) กับใช้งาน (endpoint) คนละ thread
    # แต่ละ request มี connection ของตัวเองและใช้งานทีละขั้น จึงปลอดภัย
    conn = sqlite3.connect(path or config.DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # DELETE journal + FULL sync: ข้อมูลอยู่ในไฟล์เดียว และทนไฟดับได้ดีที่สุด
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """อัปเกรด Schema ให้เป็นเวอร์ชันล่าสุด (ไม่ลบข้อมูลเดิม)."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current > SCHEMA_VERSION:
        raise RuntimeError(
            f"ฐานข้อมูลเป็นเวอร์ชัน {current} ใหม่กว่าโปรแกรม ({SCHEMA_VERSION}) — กรุณาใช้โปรแกรมเวอร์ชันใหม่กว่า"
        )
    # ปิด foreign_keys ระหว่างแปลง (การสร้างตารางใหม่แทนตารางเดิมต้องไม่ลบไฟล์แนบตาม CASCADE)
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        for version in range(current + 1, SCHEMA_VERSION + 1):
            # ทำทั้งเวอร์ชันใน transaction เดียว — ผิดพลาดกลางทางจะย้อนกลับทั้งหมด
            conn.execute("BEGIN")
            try:
                _MIGRATIONS[version](conn)
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"ข้อมูลอ้างอิงไม่ถูกต้องหลังแปลงเวอร์ชัน {version}: {len(broken)} แถว")
                conn.execute(f"PRAGMA user_version = {version}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _seed(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO settings(key, value) VALUES (?, ?)", DEFAULT_SETTINGS.items()
    )
    for kind, names in DEFAULT_MASTER.items():
        conn.executemany(
            "INSERT INTO master_items(kind, name, sort_order) VALUES (?, ?, ?)",
            [(kind, name, i) for i, name in enumerate(names)],
        )


def attach_dir() -> Path:
    return config.DATA_DIR / "attachments"


def ensure_dirs() -> None:
    for d in (config.DATA_DIR, config.BACKUP_DIR, attach_dir()):
        d.mkdir(parents=True, exist_ok=True)


def current_version() -> int:
    """เวอร์ชันของฐานข้อมูลในเครื่อง (0 = ยังไม่มีฐานข้อมูล)."""
    if not config.DB_PATH.exists():
        return 0
    conn = connect()
    try:
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def init_db() -> None:
    ensure_dirs()
    conn = connect()
    try:
        migrate(conn)
    finally:
        conn.close()


# ค่าตั้งที่เพิ่มหลัง v1 (ไม่แก้ข้อมูลเริ่มต้นของ Migration v1) — rate_target = เป้าผลิต/ชม. ล่าสุด (v1.9)
LATER_SETTINGS = {"rate_target": ""}


def get_settings(conn: sqlite3.Connection) -> dict:
    values = {**DEFAULT_SETTINGS, **LATER_SETTINGS}
    values.update({r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM settings")})
    return values
