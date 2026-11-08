import io
import sqlite3
import zipfile
from datetime import datetime

from conftest import event

from app import backup, config


def test_auto_backup_created_once_per_day(client, home):
    autos = [b for b in client.get("/api/backups").json() if b["kind"] == "auto"]
    assert len(autos) == 1
    assert backup.auto_backup_if_needed() is None  # วันเดียวกัน ไม่สร้างซ้ำ


def test_auto_backup_retention_keeps_30(client, home):
    for i in range(35):
        (config.BACKUP_DIR / f"T14_backup_202601{(i % 28) + 1:02d}_{i:06d}_auto.zip").write_bytes(b"x")
    (config.BACKUP_DIR / "T14_backup_20250101_000000_manual.zip").write_bytes(b"x")
    backup.auto_backup_if_needed()
    names = [b["name"] for b in backup.list_backups()]
    assert sum(1 for n in names if n.endswith("_auto.zip")) == 30
    assert "T14_backup_20250101_000000_manual.zip" in names  # Backup ที่สร้างเองไม่ถูกลบ


def test_manual_backup_restore_roundtrip(client, home):
    client.post("/api/events", json=event(problem="ก่อน Backup"))
    b = client.post("/api/backups").json()
    assert b["kind"] == "manual"
    with zipfile.ZipFile(config.BACKUP_DIR / b["name"]) as zf:
        assert set(zf.namelist()) == {"t14.db", "manifest.json"}

    client.post("/api/events", json=event(problem="หลัง Backup"))
    assert len(client.get("/api/events", params={"date": "2026-10-13"}).json()) == 2

    r = client.post(f"/api/backups/{b['name']}/restore")
    assert r.status_code == 200
    safety = r.json()["safety_backup"]
    assert "_pre-restore" in safety
    events = client.get("/api/events", params={"date": "2026-10-13"}).json()
    assert [e["problem"] for e in events] == ["ก่อน Backup"]

    # Backup ก่อน Restore ต้องมีข้อมูลล่าสุด (2 รายการ) — กู้คืนได้ถ้า Restore ผิด
    client.post(f"/api/backups/{safety}/restore")
    assert len(client.get("/api/events", params={"date": "2026-10-13"}).json()) == 2


def test_restore_upload_and_rejects_bad_files(client, home):
    client.post("/api/events", json=event())
    name = client.post("/api/backups").json()["name"]
    data = (config.BACKUP_DIR / name).read_bytes()
    client.post("/api/events", json=event())
    r = client.post("/api/restore-upload", files={"file": ("x.zip", data, "application/zip")})
    assert r.status_code == 200
    assert len(client.get("/api/events", params={"date": "2026-10-13"}).json()) == 1

    before = len(backup.list_backups())
    bad = client.post("/api/restore-upload", files={"file": ("x.zip", b"not a zip", "application/zip")})
    assert bad.status_code == 400 and "zip" in bad.json()["detail"]

    buf = io.BytesIO()
    other = home / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE foo(x)")
    conn.commit()
    conn.close()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.write(other, "t14.db")
    wrong = client.post("/api/restore-upload", files={"file": ("x.zip", buf.getvalue(), "application/zip")})
    assert wrong.status_code == 400 and "ไม่ใช่ Backup" in wrong.json()["detail"]
    # ไฟล์ที่ไม่ผ่านการตรวจสอบต้องไม่แตะข้อมูลเดิม
    assert len(backup.list_backups()) == before
    assert len(client.get("/api/events", params={"date": "2026-10-13"}).json()) == 1


def test_backup_name_traversal_rejected(client):
    assert client.post("/api/backups/..%2Fdata%2Ft14.db/restore").status_code in (400, 404)
    assert client.get("/api/backups/evil.zip").status_code == 400


def test_list_sorted_newest_first(client):
    client.post("/api/backups")
    names = [b["name"] for b in client.get("/api/backups").json()]
    stamps = [n.split("_")[2] + n.split("_")[3] for n in names]
    assert stamps == sorted(stamps, reverse=True)
    assert datetime.now().strftime("%Y%m%d") in names[0]
