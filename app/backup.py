"""Backup / Restore ฐานข้อมูล (ไฟล์ .zip ใน backups/)."""
import json
import re
import shutil
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path

from app import config, db
from app.attachments import STORED_NAME_RE

DB_NAME_IN_ZIP = "t14.db"
MANIFEST_NAME = "manifest.json"
ATTACH_PREFIX = "attachments/"
KINDS = {"auto": "อัตโนมัติ", "manual": "สร้างเอง", "pre-restore": "ก่อน Restore", "pre-upgrade": "ก่อนอัปเกรด"}
_NAME_RE = re.compile(r"^T14_backup_(\d{8}_\d{6})_(auto|manual|pre-restore|pre-upgrade)(?:_\d+)?\.zip$")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024

# กันไม่ให้ Backup/Restore ทำงานซ้อนกัน
LOCK = threading.Lock()


class BackupError(Exception):
    pass


def _backup_path(kind: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = config.BACKUP_DIR / f"T14_backup_{stamp}_{kind}.zip"
    n = 1
    while path.exists():
        path = config.BACKUP_DIR / f"T14_backup_{stamp}_{kind}_{n}.zip"
        n += 1
    return path


def _counts(conn: sqlite3.Connection) -> dict:
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("events", "daily_output", "master_items", "attachments") if t in tables
    }


def create_backup(kind: str = "manual") -> dict:
    if kind not in KINDS:
        raise BackupError("ประเภท Backup ไม่ถูกต้อง")
    config.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK:
        return _create_backup_locked(kind)


def _create_backup_locked(kind: str) -> dict:
    path = _backup_path(kind)
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / DB_NAME_IN_ZIP
        src = db.connect()
        dst = sqlite3.connect(snapshot)
        try:
            src.backup(dst)  # สำเนาที่สอดคล้องกันแม้โปรแกรมกำลังทำงาน
            manifest = {
                "app": config.APP_NAME,
                "app_version": config.APP_VERSION,
                "schema_version": src.execute("PRAGMA user_version").fetchone()[0],
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "kind": kind,
                "counts": _counts(src),
            }
        finally:
            dst.close()
            src.close()
        tmp_zip = path.with_suffix(".zip.tmp")
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snapshot, DB_NAME_IN_ZIP)
            folder = db.attach_dir()
            if folder.exists():
                for f in sorted(folder.iterdir()):
                    if f.is_file() and STORED_NAME_RE.match(f.name):
                        zf.write(f, ATTACH_PREFIX + f.name, compress_type=zipfile.ZIP_STORED)
            zf.writestr(MANIFEST_NAME, json.dumps(manifest, ensure_ascii=False, indent=2))
        tmp_zip.replace(path)
    return _describe(path)


def _describe(path: Path) -> dict:
    m = _NAME_RE.match(path.name)
    stamp = datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
    return {
        "name": path.name,
        "kind": m.group(2),
        "kind_label": KINDS[m.group(2)],
        "created_at": stamp.isoformat(sep=" "),
        "size_bytes": path.stat().st_size,
    }


def list_backups() -> list[dict]:
    if not config.BACKUP_DIR.exists():
        return []
    items = [_describe(p) for p in config.BACKUP_DIR.iterdir() if _NAME_RE.match(p.name)]
    return sorted(items, key=lambda b: b["name"].split("_")[2:4], reverse=True)


def resolve_backup(name: str) -> Path:
    """คืน path ของไฟล์ Backup — ยอมรับเฉพาะชื่อที่ถูกรูปแบบ (กัน path traversal)."""
    if not _NAME_RE.match(name or ""):
        raise BackupError("ชื่อไฟล์ Backup ไม่ถูกต้อง")
    path = config.BACKUP_DIR / name
    if not path.is_file():
        raise BackupError("ไม่พบไฟล์ Backup")
    return path


def auto_backup_if_needed() -> dict | None:
    """Backup อัตโนมัติวันละครั้ง และลบ Backup อัตโนมัติที่เก่ากว่า 30 ชุดล่าสุด."""
    today = datetime.now().strftime("%Y%m%d")
    autos = [b for b in list_backups() if b["kind"] == "auto"]
    created = None
    if not any(b["name"].startswith(f"T14_backup_{today}_") for b in autos):
        created = create_backup("auto")
        autos.insert(0, created)
    for old in autos[config.AUTO_BACKUP_KEEP:]:
        (config.BACKUP_DIR / old["name"]).unlink(missing_ok=True)
    return created


def _validate_db_file(path: Path) -> dict:
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"เปิดไฟล์ฐานข้อมูลไม่ได้: {exc}") from exc
    try:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise BackupError("ไฟล์ฐานข้อมูลใน Backup เสียหาย (integrity check ไม่ผ่าน)")
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = db.REQUIRED_TABLES - tables
        if missing:
            raise BackupError("ไฟล์นี้ไม่ใช่ Backup ของโปรแกรมนี้ (ไม่พบตาราง: " + ", ".join(sorted(missing)) + ")")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > db.SCHEMA_VERSION:
            raise BackupError("Backup นี้มาจากโปรแกรมเวอร์ชันใหม่กว่า ไม่สามารถ Restore ได้")
        return {"schema_version": version, "counts": _counts(conn)}
    except sqlite3.DatabaseError as exc:
        raise BackupError(f"ไฟล์ฐานข้อมูลใน Backup ไม่ถูกต้อง: {exc}") from exc
    finally:
        conn.close()


def restore_from_zip(zip_path: Path) -> dict:
    """ตรวจสอบไฟล์ → Backup ข้อมูลปัจจุบัน (pre-restore) → แทนที่ข้อมูล."""
    with tempfile.TemporaryDirectory() as tmp:
        extracted = Path(tmp) / DB_NAME_IN_ZIP
        new_attach = Path(tmp) / "attachments"
        new_attach.mkdir()
        try:
            with zipfile.ZipFile(zip_path) as zf:
                if DB_NAME_IN_ZIP not in zf.namelist():
                    raise BackupError("ไม่พบไฟล์ฐานข้อมูลในไฟล์ Backup")
                with zf.open(DB_NAME_IN_ZIP) as src, open(extracted, "wb") as out:
                    shutil.copyfileobj(src, out)
                for name in zf.namelist():
                    base = name[len(ATTACH_PREFIX):]
                    if name.startswith(ATTACH_PREFIX) and STORED_NAME_RE.match(base):
                        with zf.open(name) as src, open(new_attach / base, "wb") as out:
                            shutil.copyfileobj(src, out)
        except zipfile.BadZipFile as exc:
            raise BackupError("ไฟล์ไม่ใช่ .zip ที่ถูกต้อง") from exc
        info = _validate_db_file(extracted)

        with LOCK:
            safety = _create_backup_locked("pre-restore")
            src = sqlite3.connect(extracted)
            dst = db.connect()
            try:
                src.backup(dst)  # เขียนทับเนื้อหาฐานข้อมูลปัจจุบันทั้งหมด
                db.migrate(dst)  # อัปเกรดถ้า Backup เป็นเวอร์ชันเก่า
            finally:
                src.close()
                dst.close()
            _replace_attachments(new_attach)
    return {"restored": info, "safety_backup": safety["name"]}


def _replace_attachments(new_folder: Path) -> None:
    """แทนที่โฟลเดอร์ไฟล์แนบด้วยไฟล์จาก Backup (Backup ที่ไม่มีไฟล์แนบ = โฟลเดอร์ว่าง)."""
    target = db.attach_dir()
    old = target.with_name("attachments_old")
    if old.exists():
        shutil.rmtree(old)
    if target.exists():
        target.rename(old)
    shutil.copytree(new_folder, target)
    shutil.rmtree(old, ignore_errors=True)
