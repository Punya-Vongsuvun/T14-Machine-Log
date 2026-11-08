"""ไฟล์แนบของรายการ (เก็บใน data/attachments/)."""
import re
import sqlite3
import uuid
from pathlib import Path

from app import db

ALLOWED_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".pdf",
    ".xls", ".xlsx", ".xlsm", ".csv",
    ".doc", ".docx",
}
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PER_EVENT = 5
STORED_NAME_RE = re.compile(r"^[0-9a-f]{32}\.[a-z0-9]{1,5}$")


class AttachmentError(Exception):
    pass


def _ext(name: str) -> str:
    return Path(name).suffix.lower()


def check_name(name: str) -> None:
    if _ext(name) not in ALLOWED_EXT:
        raise AttachmentError(
            f"ไม่รองรับไฟล์ '{name}' — แนบได้เฉพาะรูปภาพ, PDF, Excel, Word"
        )


def count_for(conn: sqlite3.Connection, event_id: int) -> int:
    return conn.execute("SELECT COUNT(*) FROM attachments WHERE event_id = ?", (event_id,)).fetchone()[0]


def save(conn: sqlite3.Connection, event_id: int, orig_name: str, stream) -> dict:
    """บันทึกไฟล์จาก stream (อ่านทีละส่วน ตัดเมื่อเกินขนาด) แล้วเพิ่มแถวในฐานข้อมูล."""
    orig_name = Path(orig_name.replace("\\", "/")).name.strip() or "file"
    check_name(orig_name)
    stored = f"{uuid.uuid4().hex}{_ext(orig_name)}"
    folder = db.attach_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / stored
    size = 0
    try:
        with open(path, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise AttachmentError(f"ไฟล์ '{orig_name}' ใหญ่เกิน {MAX_FILE_BYTES // 1048576} MB")
                out.write(chunk)
        if size == 0:
            raise AttachmentError(f"ไฟล์ '{orig_name}' ว่างเปล่า")
        with conn:
            cur = conn.execute(
                "INSERT INTO attachments(event_id, orig_name, stored_name, size_bytes) VALUES (?, ?, ?, ?)",
                (event_id, orig_name, stored, size),
            )
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return {"id": cur.lastrowid, "name": orig_name, "size_bytes": size}


def for_events(conn: sqlite3.Connection, event_ids: list[int]) -> dict[int, list[dict]]:
    result: dict[int, list[dict]] = {i: [] for i in event_ids}
    if not event_ids:
        return result
    marks = ", ".join("?" for _ in event_ids)
    for r in conn.execute(
        f"SELECT id, event_id, orig_name, size_bytes FROM attachments WHERE event_id IN ({marks}) ORDER BY id",
        event_ids,
    ):
        result[r["event_id"]].append({"id": r["id"], "name": r["orig_name"], "size_bytes": r["size_bytes"]})
    return result


def get(conn: sqlite3.Connection, attachment_id: int):
    return conn.execute("SELECT * FROM attachments WHERE id = ?", (attachment_id,)).fetchone()


def remove_files(stored_names: list[str]) -> None:
    for name in stored_names:
        if STORED_NAME_RE.match(name):
            (db.attach_dir() / name).unlink(missing_ok=True)
