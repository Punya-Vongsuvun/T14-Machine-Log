import sqlite3
import zipfile

from conftest import event  # noqa: F401  (ใช้ fixture home/client)

from app import backup, config, db

V1_ROWS = [
    # (date, type, from, to, hours, shift, machine, problem)
    ("2026-10-08", "stop", "19.00", "03.00", 9, "N", "Change Size", "34.92 to 28"),
    ("2026-10-10", "stop", "05.00", "06.00", 2, "N", "STOP LINE", "ไม่มี Order"),
    ("2026-10-11", "stop", "19.00", "03.00", 9, "N", "STOP LINE", "ไฟดับ"),
    ("2026-10-12", "problem", "07.00", "08.00", 2, "M", "Press", "หลอดติด"),
]


def _make_v1_db(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("BEGIN")
    db._migrate_v1(conn)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.executemany(
        "INSERT INTO events(date, type, time_from, time_to, hours, shift, machine, problem) VALUES (?,?,?,?,?,?,?,?)",
        V1_ROWS,
    )
    conn.commit()
    conn.close()


def test_upgrade_v1_to_latest_converts_stop_rows(home):
    config.DATA_DIR.mkdir(parents=True)
    _make_v1_db(config.DB_PATH)
    db.init_db()
    conn = db.connect()
    rows = {r["problem"]: dict(r) for r in conn.execute("SELECT * FROM events")}
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION
    assert {r["type"] for r in rows.values()} == {"problem"}
    cs = rows["34.92 to 28"]
    assert cs["stop_line"] == 0 and cs["machine"] == "Change Size" and cs["hours"] == 9
    order = rows["ไม่มี Order"]
    assert order["stop_line"] == 1 and order["machine"] == "" and order["end_date"] == "2026-10-10"
    night = rows["ไฟดับ"]
    assert night["stop_line"] == 1 and night["end_date"] == "2026-10-12" and night["hours"] == 9
    assert rows["หลอดติด"]["stop_line"] == 0 and rows["หลอดติด"]["end_date"] is None
    machines = [r[0] for r in conn.execute("SELECT name FROM master_items WHERE kind='machine' ORDER BY sort_order")]
    # v2 ย้าย MONDAY Cleaning / Change Size มาเป็นเครื่องจักร, v5 เพิ่มชื่อเครื่องจริง, v6 จัดตามลำดับจริงและลบชื่อที่ไม่ใช้
    assert machines == list(db.V6_MACHINE_ORDER)
    assert conn.execute("SELECT COUNT(*) FROM master_items WHERE kind='stop'").fetchone()[0] == 0
    conn.close()


def test_app_start_backs_up_before_upgrade(home):
    config.DATA_DIR.mkdir(parents=True)
    _make_v1_db(config.DB_PATH)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        kinds = [b["kind"] for b in c.get("/api/backups").json()]
        assert "pre-upgrade" in kinds
    pre = next(b for b in backup.list_backups() if b["kind"] == "pre-upgrade")
    with zipfile.ZipFile(config.BACKUP_DIR / pre["name"]) as zf:
        zf.extract("t14.db", home)
    old = sqlite3.connect(home / "t14.db")
    assert old.execute("PRAGMA user_version").fetchone()[0] == 1  # สำเนาก่อนอัปเกรด
    old.close()


def test_restore_v1_backup_is_upgraded(client, home):
    v1 = home / "v1.db"
    _make_v1_db(v1)
    zpath = home / "v1.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.write(v1, "t14.db")
    r = client.post("/api/restore-upload", files={"file": ("v1.zip", zpath.read_bytes(), "application/zip")})
    assert r.status_code == 200
    events = client.get("/api/events", params={"date": "2026-10-10"}).json()
    assert events[0]["stop_line"] is True and events[0]["attachments"] == []


def test_failed_migration_rolls_back(home, monkeypatch):
    config.DATA_DIR.mkdir(parents=True)
    _make_v1_db(config.DB_PATH)

    def boom(conn):
        db._run_sql(conn, db._V2_SQL)
        raise RuntimeError("จำลองความผิดพลาด")

    monkeypatch.setitem(db._MIGRATIONS, 2, boom)
    try:
        db.init_db()
    except RuntimeError:
        pass
    conn = db.connect()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(events)")]
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 1 and "stop_line" not in cols
    conn.close()


def _make_v2_db_with_attachment(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    for v in (1, 2):
        conn.execute("BEGIN")
        db._MIGRATIONS[v](conn)
        conn.execute(f"PRAGMA user_version = {v}")
        conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    rows = [
        # date, type, stop_line, end_date, from, to, hours, shift, size, machine, problem, due, resp, status
        ("2026-10-13", "problem", 0, None, "07.00", "08.00", 2, "M", "34.92", "Press", "หลอดติด",
         "2026-10-20", "สมชาย", "open"),
        ("2026-10-13", "problem", 1, "2026-10-14", "19.00", "03.00", 9, "N", "28", "", "ไฟดับ", None, "", "done"),
        ("2026-10-13", "improve", 0, None, "09.00", "10.00", 2, "M", "", "Latex", "ปรับปรุง", "2026-10-30",
         "สมหญิง", "open"),
    ]
    conn.executemany(
        "INSERT INTO events(date, type, stop_line, end_date, time_from, time_to, hours, shift, size, machine, "
        "problem, due_date, responsible, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.execute("INSERT INTO attachments(event_id, orig_name, stored_name, size_bytes) "
                 "VALUES (1, 'a.png', '0123456789abcdef0123456789abcdef.png', 10)")
    conn.commit()
    conn.close()


def test_upgrade_v2_to_v3_keeps_data_and_attachments(home):
    config.DATA_DIR.mkdir(parents=True)
    _make_v2_db_with_attachment(config.DB_PATH)
    db.init_db()
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION  # v3 → ล่าสุด
    # ไฟล์แนบต้องไม่ถูกลบตาม (ON DELETE CASCADE) ตอนสร้างตารางใหม่
    assert conn.execute("SELECT COUNT(*) FROM attachments WHERE event_id = 1").fetchone()[0] == 1
    rows = {r["problem"]: dict(r) for r in conn.execute("SELECT * FROM events")}
    assert rows["หลอดติด"]["status"] == "pending"            # 'open' → 'pending' (ข้อมูลเดิมยังอยู่)
    assert rows["หลอดติด"]["responsible"] == "สมชาย"        # เก็บไว้ แม้ไม่แสดงแล้ว
    assert rows["ไฟดับ"]["time_from"] == "19.00" and rows["ไฟดับ"]["hours"] == 9
    assert rows["ปรับปรุง"]["status"] == "pending"
    # เพิ่ม Stop Line แบบใหม่ (ไม่มีเวลา/กะ) ได้
    conn.execute("INSERT INTO events(date, type, stop_line, end_date, hours, problem) "
                 "VALUES ('2026-10-15', 'problem', 1, '2026-10-15', 24, 'x')")
    conn.commit()
    # ลบรายการยังลบไฟล์แนบตาม (foreign key ยังทำงาน)
    conn.execute("DELETE FROM events WHERE id = 1")
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM attachments").fetchone()[0] == 0
    conn.close()


def test_upgrade_v2_api_hides_old_fields(home):
    config.DATA_DIR.mkdir(parents=True)
    _make_v2_db_with_attachment(config.DB_PATH)
    from fastapi.testclient import TestClient
    from app.main import app
    with TestClient(app) as c:
        events = {e["problem"]: e for e in c.get("/api/events", params={"date": "2026-10-13"}).json()}
    assert events["หลอดติด"]["status"] is None and events["หลอดติด"]["responsible"] == ""
    assert events["ไฟดับ"]["time_from"] is None and events["ไฟดับ"]["shift"] is None
    assert events["ปรับปรุง"]["status_label"] == "รอดำเนินการ" and events["ปรับปรุง"]["responsible"] == "สมหญิง"
    assert len(events["หลอดติด"]["attachments"]) == 1


def test_upgrade_v3_to_v4_adds_holiday(home):
    config.DATA_DIR.mkdir(parents=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    for v in (1, 2, 3):
        conn.execute("BEGIN")
        db._MIGRATIONS[v](conn)
        conn.execute(f"PRAGMA user_version = {v}")
        conn.commit()
    conn.execute("INSERT INTO daily_output(date, target, output) VALUES ('2026-10-13', 120000, 123200)")
    conn.commit()
    conn.close()
    db.init_db()
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION  # v3 → ล่าสุด
    row = conn.execute("SELECT * FROM daily_output").fetchone()
    assert (row["target"], row["output"], row["holiday"]) == (120000, 123200, 0)   # ข้อมูลเดิมครบ, ไม่ใช่วันหยุด
    conn.close()


def _db_at(version: int):
    """ฐานข้อมูลที่อัปเกรดถึงเวอร์ชันที่กำหนด (ใช้ทดสอบ Migration ทีละขั้น)."""
    config.DATA_DIR.mkdir(parents=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    for v in range(1, version + 1):
        conn.execute("BEGIN")
        db._MIGRATIONS[v](conn)
        conn.execute(f"PRAGMA user_version = {v}")
        conn.commit()
    return conn


def _machines(conn):
    return [r[0] for r in conn.execute("SELECT name FROM master_items WHERE kind='machine' ORDER BY sort_order")]


def test_upgrade_v4_to_v5_adds_machines_without_duplicates(home):
    conn = _db_at(4)
    # ผู้ใช้เพิ่มเองไว้แล้วบางชื่อ (ตัวพิมพ์ต่างกัน)
    conn.execute("INSERT INTO master_items(kind, name, sort_order) VALUES ('machine', 'ibo', 50)")
    conn.commit()
    conn.execute("BEGIN")
    db._MIGRATIONS[5](conn)
    conn.commit()
    machines = _machines(conn)
    assert machines[:7] == ["Press", "Latex", "Print", "Inside Coat", "Cap", "MONDAY Cleaning", "Change Size"]  # ของเดิมครบ
    assert machines[7:] == ["ibo", "Trim", "Aneal", "Base", "DO-BC", "DO-PT", "Accu.", "Pack"]   # ไม่เพิ่ม IBO ซ้ำ
    conn.close()


def test_upgrade_v5_to_v6_orders_machines_and_keeps_events(home):
    conn = _db_at(5)
    # ผู้ใช้เพิ่มเครื่องเองไว้ 1 ชื่อ + รายการเดิมใช้ชื่อที่จะถูกลบออกจาก Master
    conn.execute("INSERT INTO master_items(kind, name, sort_order) VALUES ('machine', 'Robot', 99)")
    conn.execute("INSERT INTO events(date, type, time_from, time_to, hours, shift, machine, problem) "
                 "VALUES ('2026-10-13', 'problem', '07.00', '08.00', 2, 'M', 'Inside Coat', 'x')")
    conn.commit()
    conn.close()
    db.init_db()
    conn = db.connect()
    assert conn.execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION  # v5 → ล่าสุด
    assert _machines(conn) == [*db.V6_MACHINE_ORDER, "Robot"]          # ลำดับจริง + ชื่อที่ผู้ใช้เพิ่มเองต่อท้าย
    ev = conn.execute("SELECT machine, hours, rate_target, rate_actuals FROM events").fetchone()
    assert tuple(ev) == ("Inside Coat", 2, None, None)                  # รายการเดิมไม่เปลี่ยน
    db.migrate(conn)                                                     # รันซ้ำไม่เปลี่ยน
    assert _machines(conn) == [*db.V6_MACHINE_ORDER, "Robot"]
    conn.close()
