"""T14 Machine Log — FastAPI application."""
import json
import re
import shutil
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import attachments, backup, config, db, export_xlsx
from app.schemas import CLEANING_LABEL, DailyIn, DailyMoveIn, EventIn, MasterIn, MasterKind, SettingsIn
from app.timecalc import calc_hours, calc_rate_hours, calc_shift, parse_time, production_order

THAI_DAYS = ["จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์", "อาทิตย์"]
SHIFT_LABELS = {"M": "เช้า", "N": "ดึก"}
TYPE_LABELS = {"problem": "ปัญหา", "improve": "การปรับปรุง"}
STOP_LINE_LABEL = "Stop Line"
# ตัวกรองประเภทในรายงาน/Dashboard
# รายงาน: ปัญหา (ไม่รวม Stop Line) / ปัญหารวม Stop Line / การปรับปรุง / Stop Line / ทั้งหมด
# v1.10 + Monday Cleaning (บันทึกอย่างเดียวเหมือน Stop Line) — "ปัญหารวม Stop Line" รวม Monday Cleaning ด้วย
REPORT_TYPES = {"all", "problem", "problem_sl", "improve", "stopline", "cleaning"}
# Dashboard: Stop Line ไม่อยู่ในกราฟ/ชั่วโมงรวมเลย จึงมีแค่ 3 แบบ
DASHBOARD_TYPES = {"all", "problem", "improve"}
STATUS_LABELS = {"done": "เสร็จแล้ว", "pending": "รอดำเนินการ", "in_progress": "ระหว่างดำเนินการ"}
OPEN_STATUSES = ("pending", "in_progress")
FIELD_LABELS = {
    "date": "วันที่", "type": "ประเภท", "time_from": "เวลาเริ่ม", "time_to": "เวลาสิ้นสุด",
    "size": "Size", "machine": "เครื่องจักร", "problem": "ปัญหา", "corrective": "การแก้ไข",
    "due_date": "กำหนดวันเสร็จ", "responsible": "ผู้รับผิดชอบ", "status": "สถานะ",
    "target": "เป้าหมาย", "output": "ผลิตได้", "line_name": "ชื่อ Line",
    "default_target": "เป้าหมายเริ่มต้น", "morning_start": "เวลาเริ่มกะเช้า",
    "night_start": "เวลาเริ่มกะดึก", "name": "ชื่อ", "end_date": "วันที่สิ้นสุด", "stop_line": "Stop Line",
    "planned_stop": "Monday Cleaning", "to": "ย้ายไปวันที่",
}


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.ensure_dirs()
    if 0 < db.current_version() < db.SCHEMA_VERSION:
        backup.create_backup("pre-upgrade")  # สำรองข้อมูลก่อนอัปเกรดโครงสร้างฐานข้อมูล
    db.init_db()
    backup.auto_backup_if_needed()
    yield


app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)


# ---------- Error handling ----------

def _thai_error(err: dict) -> str:
    loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path")]
    field = FIELD_LABELS.get(loc[-1], loc[-1]) if loc else ""
    msg = err.get("msg", "")
    kind = err.get("type", "")
    if kind == "missing":
        msg = "กรุณากรอกข้อมูล"
    elif kind == "string_too_short":
        msg = "กรุณากรอกข้อมูล"
    elif kind == "string_too_long":
        msg = f"ยาวเกิน {err.get('ctx', {}).get('max_length')} ตัวอักษร"
    elif kind in ("greater_than_equal", "less_than_equal"):
        msg = "ค่าตัวเลขอยู่นอกช่วงที่อนุญาต"
    elif kind.startswith("int_"):
        msg = "ต้องเป็นจำนวนเต็ม"
    elif kind.startswith("date_"):
        msg = "วันที่ไม่ถูกต้อง"
    elif kind == "literal_error":
        msg = "ค่าที่เลือกไม่ถูกต้อง"
    elif msg.startswith("Value error, "):
        msg = msg[len("Value error, "):]
    return f"{field}: {msg}" if field else msg


@app.exception_handler(RequestValidationError)
async def _validation_handler(_req: Request, exc: RequestValidationError):
    messages = [_thai_error(e) for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": " / ".join(messages)})


@app.exception_handler(backup.BackupError)
async def _backup_handler(_req: Request, exc: backup.BackupError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(attachments.AttachmentError)
async def _attachment_handler(_req: Request, exc: attachments.AttachmentError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(sqlite3.Error)
async def _db_handler(_req: Request, exc: sqlite3.Error):
    return JSONResponse(status_code=500, content={"detail": f"เกิดข้อผิดพลาดของฐานข้อมูล: {exc}"})


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def _minutes_setting(settings: dict, key: str) -> int:
    return parse_time(settings[key])


# ---------- Health / Settings ----------

@app.get("/api/health")
def health():
    return {"app": config.APP_NAME, "version": config.APP_VERSION}


@app.get("/api/settings")
def read_settings(conn=Depends(get_conn)):
    s = db.get_settings(conn)
    return {**s, "data_dir": str(config.DATA_DIR), "backup_dir": str(config.BACKUP_DIR),
            "app_version": config.APP_VERSION}


@app.put("/api/settings")
def update_settings(body: SettingsIn, conn=Depends(get_conn)):
    values = body.model_dump()
    values["default_target"] = "" if values["default_target"] is None else str(values["default_target"])
    with conn:
        conn.executemany(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            values.items(),
        )
    return read_settings(conn)


# ---------- Master ----------

@app.get("/api/master")
def list_master(conn=Depends(get_conn)):
    result = {k: [] for k in db.MASTER_KINDS}
    for r in conn.execute("SELECT id, kind, name FROM master_items ORDER BY kind, sort_order, name COLLATE NOCASE"):
        result[r["kind"]].append({"id": r["id"], "name": r["name"]})
    return result


def _master_conflict(conn, kind: str, name: str, exclude_id: int | None = None):
    row = conn.execute(
        "SELECT id FROM master_items WHERE kind = ? AND name = ? AND id IS NOT ?", (kind, name, exclude_id)
    ).fetchone()
    if row:
        raise HTTPException(409, f"มี '{name}' อยู่ในรายการแล้ว")


def _master_name(kind: str, name: str) -> str:
    # Size: ⌀ เป็นสัญลักษณ์ที่แสดงบนหน้าจอเท่านั้น — เก็บเฉพาะตัวเลข (ให้ตรงกับข้อมูลรายการ)
    return name.lstrip("⌀Øø ").strip() if kind == "size" else name


@app.post("/api/master/{kind}", status_code=201)
def add_master(kind: MasterKind, body: MasterIn, conn=Depends(get_conn)):
    body.name = _master_name(kind, body.name)
    if not body.name:
        raise HTTPException(422, "ชื่อ: กรุณากรอกข้อมูล")
    _master_conflict(conn, kind, body.name)
    with conn:
        next_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM master_items WHERE kind = ?", (kind,)
        ).fetchone()[0]
        cur = conn.execute(
            "INSERT INTO master_items(kind, name, sort_order) VALUES (?, ?, ?)", (kind, body.name, next_order)
        )
    return {"id": cur.lastrowid, "kind": kind, "name": body.name}


@app.put("/api/master/{kind}/{item_id}")
def rename_master(kind: MasterKind, item_id: int, body: MasterIn, conn=Depends(get_conn)):
    body.name = _master_name(kind, body.name)
    if not body.name:
        raise HTTPException(422, "ชื่อ: กรุณากรอกข้อมูล")
    _master_conflict(conn, kind, body.name, item_id)
    with conn:
        cur = conn.execute("UPDATE master_items SET name = ? WHERE id = ? AND kind = ?", (body.name, item_id, kind))
    if cur.rowcount == 0:
        raise HTTPException(404, "ไม่พบรายการ")
    return {"id": item_id, "kind": kind, "name": body.name}


@app.post("/api/master/{kind}/{item_id}/move")
def move_master(kind: MasterKind, item_id: int, direction: str = Query(..., alias="dir"), conn=Depends(get_conn)):
    """เลื่อนลำดับขึ้น/ลง 1 ตำแหน่ง (v1.9) — ลำดับนี้ใช้ในตัวเลือกและกราฟเครื่องจักร."""
    if direction not in ("up", "down"):
        raise HTTPException(422, "ทิศทางไม่ถูกต้อง")
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM master_items WHERE kind = ? ORDER BY sort_order, name COLLATE NOCASE", (kind,))]
    if item_id not in ids:
        raise HTTPException(404, "ไม่พบรายการ")
    i = ids.index(item_id)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
        with conn:
            conn.executemany("UPDATE master_items SET sort_order = ? WHERE id = ?", [(n, x) for n, x in enumerate(ids)])
    return list_master(conn)


@app.delete("/api/master/{kind}/{item_id}")
def delete_master(kind: MasterKind, item_id: int, conn=Depends(get_conn)):
    with conn:
        cur = conn.execute("DELETE FROM master_items WHERE id = ? AND kind = ?", (item_id, kind))
    if cur.rowcount == 0:
        raise HTTPException(404, "ไม่พบรายการ")
    return {"deleted": item_id}


# ---------- Daily output ----------

def _daily_dict(d: str, row) -> dict:
    target = row["target"] if row else None
    output = row["output"] if row else None
    diff = output - target if target is not None and output is not None else None
    return {"date": d, "target": target, "output": output, "diff": diff, "saved": row is not None,
            "holiday": bool(row["holiday"]) if row else False}


def _missing(info: dict, today: str) -> str:
    """ข้อมูลยอดผลิตที่ยังขาด: "" | "target" | "output" | "both" — วันหยุดและวันในอนาคตไม่นับว่าขาด."""
    if info["holiday"] or info["date"] > today:
        return ""
    no_target, no_output = info["target"] is None, info["output"] is None
    return "both" if no_target and no_output else "target" if no_target else "output" if no_output else ""


def _all_days(d_from: date, d_to: date) -> list[str]:
    return [(d_from + timedelta(days=i)).isoformat() for i in range((d_to - d_from).days + 1)]


@app.get("/api/daily/{d}")
def read_daily(d: date, conn=Depends(get_conn)):
    row = conn.execute("SELECT * FROM daily_output WHERE date = ?", (d.isoformat(),)).fetchone()
    return _daily_dict(d.isoformat(), row)


@app.put("/api/daily/{d}")
def save_daily(d: date, body: DailyIn, conn=Depends(get_conn)):
    with conn:
        conn.execute(
            "INSERT INTO daily_output(date, target, output, holiday) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(date) DO UPDATE SET target = excluded.target, output = excluded.output, "
            "holiday = excluded.holiday, updated_at = datetime('now','localtime')",
            (d.isoformat(), body.target, body.output, int(body.holiday)),
        )
    return read_daily(d, conn)


@app.post("/api/daily/{d}/move")
def move_daily(d: date, body: DailyMoveIn, conn=Depends(get_conn)):
    """v1.10 ย้ายยอดผลิตที่กรอกผิดวัน (+ รายการของวันนั้น ถ้าเลือก) ไปวันที่ถูก — ไม่เขียนทับวันที่มียอดผลิตอยู่แล้ว."""
    src, dst = d.isoformat(), body.to.isoformat()
    if src == dst:
        raise HTTPException(422, "วันที่ปลายทางต้องไม่ใช่วันเดิม")
    has_daily = conn.execute("SELECT 1 FROM daily_output WHERE date = ?", (src,)).fetchone() is not None
    n_events = conn.execute("SELECT COUNT(*) FROM events WHERE date = ?", (src,)).fetchone()[0] if body.with_events else 0
    if not has_daily and not n_events:
        raise HTTPException(404, f"วันที่ {d:%d/%m/%Y} ไม่มียอดผลิตหรือรายการที่จะย้าย")
    if has_daily and conn.execute("SELECT 1 FROM daily_output WHERE date = ?", (dst,)).fetchone():
        raise HTTPException(409, f"วันที่ {body.to:%d/%m/%Y} มียอดผลิตบันทึกไว้แล้ว — ย้ายไม่ได้ (ไม่เขียนทับข้อมูลเดิม) "
                                 "ให้แก้ไขหรือลบยอดผลิตของวันนั้นก่อน")
    shift_days = (body.to - d).days
    moved = 0
    with conn:
        if has_daily:
            conn.execute("UPDATE daily_output SET date = ?, updated_at = datetime('now','localtime') WHERE date = ?",
                         (dst, src))
        if body.with_events:
            rows = conn.execute("SELECT id, end_date FROM events WHERE date = ?", (src,)).fetchall()
            for r in rows:  # Stop Line: วันที่สิ้นสุดเลื่อนเท่ากัน (จำนวนวันเท่าเดิม)
                end = (date.fromisoformat(r["end_date"]) + timedelta(days=shift_days)).isoformat() if r["end_date"] else None
                conn.execute("UPDATE events SET date = ?, end_date = ?, updated_at = datetime('now','localtime') "
                             "WHERE id = ?", (dst, end, r["id"]))
            moved = len(rows)
    return {"daily": read_daily(body.to, conn), "events_moved": moved}


# ---------- Events ----------

def _event_dict(row) -> dict:
    e = dict(row)
    e["stop_line"] = bool(e["stop_line"])
    e["cleaning"] = e.get("planned_stop") == "cleaning"  # v1.10 Monday Cleaning
    # บันทึกอย่างเดียว: ไม่นับในชั่วโมงรวม / ชั่วโมงสูญเสีย / กราฟใด ๆ
    e["record_only"] = e["stop_line"] or e["cleaning"]
    # ช่องที่ไม่ใช้กับรายการแบบนั้นแล้ว (v1.2) — ข้อมูลเดิมยังอยู่ในฐานข้อมูล แต่ไม่แสดง/ไม่นับ
    if e["stop_line"]:
        e.update(time_from=None, time_to=None, shift=None, size="")
    if e["cleaning"]:
        e["size"] = ""
    if e["type"] == "problem":
        e.update(due_date=None, responsible="", status=None)
    e["shift_label"] = SHIFT_LABELS.get(e["shift"], "")
    e["status_label"] = STATUS_LABELS.get(e["status"], "")
    e["type_label"] = (STOP_LINE_LABEL if e["stop_line"] else CLEANING_LABEL if e["cleaning"]
                       else TYPE_LABELS.get(e["type"], e["type"]))
    # v1.9 รายการที่คิดชั่วโมงจากยอดผลิต: ผลิตได้จริงแต่ละชั่วโมง (list) — None = คิดจากเวลา
    e["rate_actuals"] = json.loads(e["rate_actuals"]) if e.get("rate_actuals") else None
    return e


def _sorted_events(conn, rows, settings: dict) -> list[dict]:
    morning = _minutes_setting(settings, "morning_start")
    night = _minutes_setting(settings, "night_start")

    def order(e: dict) -> float:
        if e["time_from"] is not None:
            return production_order(parse_time(e["time_from"]), morning)
        if e["stop_line"]:
            return -1  # Stop Line (ไม่มีเวลา) ขึ้นก่อนรายการอื่นของวัน
        # คิดจากยอดผลิต (ไม่มีเวลา): ไว้ต้นกะที่เลือก
        return production_order(morning if e["shift"] == "M" else night, morning) - 0.5

    events = sorted((_event_dict(r) for r in rows), key=lambda e: (e["date"], order(e), e["id"]))
    files = attachments.for_events(conn, [e["id"] for e in events])
    for e in events:
        e["attachments"] = files[e["id"]]
    return events


def _event_values(body: EventIn, settings: dict) -> dict:
    values = body.model_dump()
    values["date"] = body.date.isoformat()
    values["due_date"] = body.due_date.isoformat() if body.due_date else None
    values["end_date"] = body.end_date.isoformat() if body.end_date else None
    values["stop_line"] = int(body.stop_line)
    values["rate_actuals"] = json.dumps(body.rate_actuals) if body.rate_actuals else None
    if body.stop_line:
        values["shift"] = None  # ชั่วโมงมาจากผู้ใช้ (หรือค่าเริ่มต้น จำนวนวัน × 24)
        return values
    start, end = parse_time(body.time_from), parse_time(body.time_to)
    # v1.10 คิดจากยอดผลิต: ช่วงเวลาบอกตำแหน่ง + กะ เท่านั้น — ชั่วโมงมาจากสูตรยอดผลิต
    values["hours"] = calc_rate_hours(body.rate_target, body.rate_actuals) if body.rate_actuals else calc_hours(start, end)
    values["shift"] = calc_shift(
        start, _minutes_setting(settings, "morning_start"), _minutes_setting(settings, "night_start")
    )
    return values


_EVENT_COLUMNS = ("date", "type", "stop_line", "end_date", "time_from", "time_to", "hours", "shift", "size",
                  "machine", "problem", "corrective", "due_date", "responsible", "status", "rate_target", "rate_actuals",
                  "planned_stop")


def _remember_rate_target(conn, body: EventIn) -> None:
    """เป้าผลิต/ชม. ค้างไว้ใช้ครั้งต่อไป (Speed Line นาน ๆ ทีจะเปลี่ยน) — v1.9."""
    if body.rate_target:
        conn.execute("INSERT INTO settings(key, value) VALUES ('rate_target', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(body.rate_target),))


def _get_event(conn, event_id: int) -> dict:
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not row:
        raise HTTPException(404, "ไม่พบรายการ (อาจถูกลบไปแล้ว)")
    return _sorted_events(conn, [row], db.get_settings(conn))[0]


@app.get("/api/events")
def list_events(d: date = Query(..., alias="date"), conn=Depends(get_conn)):
    rows = conn.execute("SELECT * FROM events WHERE date = ?", (d.isoformat(),)).fetchall()
    return _sorted_events(conn, rows, db.get_settings(conn))


@app.post("/api/events", status_code=201)
def create_event(body: EventIn, conn=Depends(get_conn)):
    values = _event_values(body, db.get_settings(conn))
    cols = ", ".join(_EVENT_COLUMNS)
    marks = ", ".join("?" for _ in _EVENT_COLUMNS)
    with conn:
        cur = conn.execute(f"INSERT INTO events({cols}) VALUES ({marks})", [values[c] for c in _EVENT_COLUMNS])
        _remember_rate_target(conn, body)
    return _get_event(conn, cur.lastrowid)


@app.put("/api/events/{event_id}")
def update_event(event_id: int, body: EventIn, conn=Depends(get_conn)):
    _get_event(conn, event_id)
    values = _event_values(body, db.get_settings(conn))
    sets = ", ".join(f"{c} = ?" for c in _EVENT_COLUMNS)
    with conn:
        conn.execute(
            f"UPDATE events SET {sets}, updated_at = datetime('now','localtime') WHERE id = ?",
            [values[c] for c in _EVENT_COLUMNS] + [event_id],
        )
        _remember_rate_target(conn, body)
    return _get_event(conn, event_id)


@app.delete("/api/events/{event_id}")
def delete_event(event_id: int, conn=Depends(get_conn)):
    _get_event(conn, event_id)
    stored = [r[0] for r in conn.execute("SELECT stored_name FROM attachments WHERE event_id = ?", (event_id,))]
    with conn:
        conn.execute("DELETE FROM events WHERE id = ?", (event_id,))  # แถวไฟล์แนบถูกลบตาม (ON DELETE CASCADE)
    attachments.remove_files(stored)
    return {"deleted": event_id, "attachments_deleted": len(stored)}


# ---------- Attachments ----------

@app.post("/api/events/{event_id}/attachments", status_code=201)
def upload_attachments(event_id: int, files: list[UploadFile] = File(...), conn=Depends(get_conn)):
    _get_event(conn, event_id)
    if attachments.count_for(conn, event_id) + len(files) > attachments.MAX_PER_EVENT:
        raise attachments.AttachmentError(f"แนบได้ไม่เกิน {attachments.MAX_PER_EVENT} ไฟล์ต่อรายการ")
    for f in files:
        attachments.check_name(f.filename or "")
    saved = [attachments.save(conn, event_id, f.filename or "", f.file) for f in files]
    return saved


@app.get("/api/attachments/{attachment_id}")
def open_attachment(attachment_id: int, conn=Depends(get_conn)):
    row = attachments.get(conn, attachment_id)
    path = db.attach_dir() / row["stored_name"] if row else None
    if not row or not path.is_file():
        raise HTTPException(404, "ไม่พบไฟล์แนบ")
    return FileResponse(path, filename=row["orig_name"], content_disposition_type="inline")


@app.delete("/api/attachments/{attachment_id}")
def delete_attachment(attachment_id: int, conn=Depends(get_conn)):
    row = attachments.get(conn, attachment_id)
    if not row:
        raise HTTPException(404, "ไม่พบไฟล์แนบ")
    with conn:
        conn.execute("DELETE FROM attachments WHERE id = ?", (attachment_id,))
    attachments.remove_files([row["stored_name"]])
    return {"deleted": attachment_id}


# ---------- Report / Dashboard ----------

def _check_range(d_from: date, d_to: date) -> None:
    if d_from > d_to:
        raise HTTPException(422, "วันที่เริ่มต้องไม่มากกว่าวันที่สิ้นสุด")


BLANK = "__blank__"  # ค่าตัวกรองสำหรับ "ไม่ระบุ" (ช่องว่าง) — ใช้ตอนคลิกแท่งกราฟ "ไม่ระบุ"
# *_ontime = ยังไม่เกินกำหนด (v1.8: แท่งกราฟงานปรับปรุงไม่นับซ้อนกับ "เกินกำหนด")
# open = ยังไม่เสร็จ (รอ + ระหว่างดำเนินการ) — v1.9 คลิกกล่อง "งานปรับปรุงที่ยังไม่เสร็จ"
STATUS_FILTERS = {"", "pending", "in_progress", "done", "overdue", "pending_ontime", "in_progress_ontime", "open"}


def _filtered_events(conn, d_from: date, d_to: date, type_filter: str = "all", machine: str = "", size: str = "",
                     shift: str = "", status: str = "", include_stopline: bool = True):
    """ตัวกรองรายงาน/Dashboard — กรองเฉพาะค่าที่แสดงจริง (ข้อมูลเดิมที่ซ่อนไว้ต้องไม่ถูกนับ)."""
    sql = "SELECT * FROM events WHERE date BETWEEN ? AND ?"
    params: list = [d_from.isoformat(), d_to.isoformat()]
    sql += {
        "all": "",
        "problem": " AND type = 'problem' AND stop_line = 0 AND planned_stop IS NULL",
        "problem_sl": " AND type = 'problem'",
        "improve": " AND type = 'improve'",
        "stopline": " AND stop_line = 1",
        "cleaning": " AND planned_stop = 'cleaning'",
    }[type_filter]
    if not include_stopline:  # sl=0 (ลิงก์จาก Dashboard): ไม่รวมรายการบันทึกอย่างเดียว (Stop Line + Monday Cleaning)
        sql += " AND stop_line = 0 AND planned_stop IS NULL"
    if machine:
        sql += " AND machine = ?"
        params.append("" if machine == BLANK else machine)
    if size:  # Stop Line ไม่มี Size (Size เดิมซ่อนไว้)
        sql += " AND stop_line = 0 AND size = ?"
        params.append("" if size == BLANK else size)
    if shift:  # Stop Line ไม่มีกะ
        sql += " AND stop_line = 0 AND shift = ?"
        params.append(shift)
    if status == "overdue":  # สถานะมีเฉพาะงานปรับปรุง
        sql += " AND type = 'improve' AND status IN ('pending','in_progress') AND due_date < ?"
        params.append(date.today().isoformat())
    elif status == "open":
        sql += " AND type = 'improve' AND status IN ('pending','in_progress')"
    elif status.endswith("_ontime"):
        sql += " AND type = 'improve' AND status = ? AND (due_date IS NULL OR due_date = '' OR due_date >= ?)"
        params += [status.removesuffix("_ontime"), date.today().isoformat()]
    elif status:
        sql += " AND type = 'improve' AND status = ?"
        params.append(status)
    return _sorted_events(conn, conn.execute(sql, params).fetchall(), db.get_settings(conn))


def _parse_type(type_param: str, allowed: set[str]) -> str:
    type_param = type_param or "all"
    if type_param not in allowed:
        raise HTTPException(422, "ประเภทไม่ถูกต้อง")
    return type_param


def _daily_rows(conn, d_from: date, d_to: date) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT * FROM daily_output WHERE date BETWEEN ? AND ?", (d_from.isoformat(), d_to.isoformat())
    ).fetchall()
    return {r["date"]: _daily_dict(r["date"], r) for r in rows}


def _type_counts(events: list[dict]) -> dict:
    """จำนวนครั้ง: ปัญหา (ไม่รวม Stop Line / Monday Cleaning) / การปรับปรุง / Stop Line."""
    return {
        "problem": sum(1 for e in events if e["type"] == "problem" and not e["record_only"]),
        "improve": sum(1 for e in events if e["type"] == "improve"),
        "stop_line": sum(1 for e in events if e["stop_line"]),
    }


def _sum_hours(events: list[dict]) -> float:
    return round(sum(e["hours"] for e in events), 2)


def report_filters(
    d_from: date = Query(..., alias="from"),
    d_to: date = Query(..., alias="to"),
    type: str = "all",
    machine: str = "",
    size: str = "",
    shift: str = "",
    status: str = "",
    sl: bool = True,  # sl=0: ไม่รวม Stop Line / Monday Cleaning (ลิงก์จาก Dashboard ซึ่งไม่นับรายการบันทึกอย่างเดียว)
) -> dict:
    """ตัวกรองของรายงาน — ใช้ร่วมกันระหว่างหน้ารายงานและ Export Excel."""
    _check_range(d_from, d_to)
    if shift not in ("", "M", "N") or status not in STATUS_FILTERS:
        raise HTTPException(422, "ตัวกรองกะ/สถานะไม่ถูกต้อง")
    return {"from": d_from, "to": d_to, "type": _parse_type(type, REPORT_TYPES), "machine": machine.strip(),
            "size": size.strip(), "shift": shift, "status": status, "sl": sl}


def _build_report(conn, f: dict) -> dict:
    d_from, d_to = f["from"], f["to"]
    events = _filtered_events(conn, d_from, d_to, f["type"], f["machine"], f["size"], f["shift"], f["status"],
                              include_stopline=f["sl"])
    daily = _daily_rows(conn, d_from, d_to)
    today = date.today().isoformat()
    days = []
    for d in _all_days(d_from, d_to):  # ทุกวันในช่วง — วันที่ไม่ได้บันทึกต้องมองเห็นได้ (v1.5 E2)
        info = daily.get(d) or _daily_dict(d, None)
        days.append({**info, "day_name": THAI_DAYS[date.fromisoformat(d).weekday()], "missing": _missing(info, today),
                     "events": [e for e in events if e["date"] == d]})
    complete = [x for x in daily.values() if x["diff"] is not None]
    complete_target = sum(x["target"] for x in complete)
    complete_output = sum(x["output"] for x in complete)
    totals = {
        # แถวรวม = ผลบวกของคอลัมน์ (ทุกวันที่มีตัวเลข)
        "target": sum(x["target"] for x in daily.values() if x["target"] is not None),
        "output": sum(x["output"] for x in daily.values() if x["output"] is not None),
        "diff": sum(x["diff"] for x in complete),
        # เฉพาะวันที่มีทั้งเป้าหมายและยอดผลิต — ตัวเลขเดียวกับ Dashboard (v1.5 E1)
        "complete_days": len(complete),
        "complete_target": complete_target,
        "complete_output": complete_output,
        "complete_pct": round(complete_output / complete_target * 100, 1) if complete_target else None,
        # ชั่วโมงรวมไม่นับ Stop Line / Monday Cleaning (ข้อมูลบันทึกอย่างเดียว)
        "hours": _sum_hours([e for e in events if not e["record_only"]]),
        "count": len(events),
        "by_type": _type_counts(events),
        "stop_line_hours": _sum_hours([e for e in events if e["stop_line"]]),
        "cleaning_count": sum(1 for e in events if e["cleaning"]),
        "cleaning_hours": _sum_hours([e for e in events if e["cleaning"]]),
        "holiday_days": sum(1 for x in days if x["holiday"]),
        "missing_days": sum(1 for x in days if x["missing"]),
    }
    return {"line_name": db.get_settings(conn)["line_name"], "from": d_from.isoformat(),
            "to": d_to.isoformat(), "days": days, "totals": totals,
            "generated_at": datetime.now().isoformat(sep=" ", timespec="minutes")}


@app.get("/api/report")
def report(f: dict = Depends(report_filters), conn=Depends(get_conn)):
    return _build_report(conn, f)


@app.get("/api/report.xlsx")
def report_xlsx(f: dict = Depends(report_filters), conn=Depends(get_conn)):
    data = _build_report(conn, f)
    content = export_xlsx.build(data, f)
    name = export_xlsx.filename(data)
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=\"T14_report.xlsx\"; filename*=UTF-8''{quote(name)}",
                 "Cache-Control": "no-store"},
    )


def _group(events: list[dict], key, labels: dict | None = None, keep: list | None = None) -> list[dict]:
    """รวมชั่วโมง/จำนวนครั้งตาม key (ชื่อฟิลด์ หรือฟังก์ชัน)."""
    get = key if callable(key) else (lambda e: e[key])
    def new(k: str) -> dict:  # key = ค่าจริง (ใช้กรองตอนคลิกแท่งกราฟ), label = ข้อความบนกราฟ
        return {"key": k, "label": (labels or {}).get(k, k) or "ไม่ระบุ", "hours": 0.0, "count": 0,
                # แยกตามประเภท สำหรับกราฟแท่งซ้อนเมื่อเลือก "ทั้งหมด"
                "parts": {t: {"hours": 0.0, "count": 0} for t in TYPE_LABELS}}

    groups: dict[str, dict] = {k: new(k) for k in keep or []}
    for e in events:
        k = get(e) or ""
        g = groups.setdefault(k, new(k))
        g["hours"] += e["hours"]
        g["count"] += 1
        g["parts"][e["type"]]["hours"] += e["hours"]
        g["parts"][e["type"]]["count"] += 1
    items = list(groups.values())
    for g in items:
        g["hours"] = round(g["hours"], 2)
        for part in g["parts"].values():
            part["hours"] = round(part["hours"], 2)
    if keep is None:
        items.sort(key=lambda g: (-g["hours"], -g["count"], g["label"]))
    return items


COMPARE_MODES = {"prev", "yoy", "custom", "none"}
COMPARE_LABELS = {"prev": "ช่วงก่อนหน้า", "yoy": "ช่วงเดียวกันปีก่อน", "custom": "ช่วงที่เลือก"}


def _year_before(d: date) -> date:
    try:
        return d.replace(year=d.year - 1)
    except ValueError:  # 29 ก.พ. → 28 ก.พ.
        return d.replace(year=d.year - 1, day=28)


def _compare_range(mode: str, d_from: date, d_to: date, c_from: date | None, c_to: date | None):
    """ช่วงที่ใช้เปรียบเทียบ: ก่อนหน้าที่ยาวเท่ากัน / ช่วงเดียวกันปีก่อน / กำหนดเอง / ไม่เปรียบเทียบ."""
    if mode == "prev":
        days = (d_to - d_from).days + 1
        return d_from - timedelta(days=days), d_from - timedelta(days=1)
    if mode == "yoy":
        return _year_before(d_from), _year_before(d_to)
    if mode == "custom":
        if not c_from or not c_to:
            raise HTTPException(422, "กรุณาเลือกช่วงวันที่ที่ใช้เปรียบเทียบ")
        _check_range(c_from, c_to)
        return c_from, c_to
    return None


def _kpis(conn, d_from: date, d_to: date, type: str) -> tuple[dict, list[dict], list[dict]]:
    """คืน (กล่องตัวเลข, รายการที่ใช้วาดกราฟ, รายการทั้งหมดในช่วง)."""
    all_events = _filtered_events(conn, d_from, d_to)
    # Stop Line / Monday Cleaning ไม่นับในกราฟและชั่วโมงใด ๆ
    events = [e for e in _filtered_events(conn, d_from, d_to, type) if not e["record_only"]]
    daily_by_date = _daily_rows(conn, d_from, d_to)
    daily = daily_by_date.values()
    today = date.today().isoformat()

    complete = [x for x in daily if x["diff"] is not None]
    target = sum(x["target"] for x in complete)
    output = sum(x["output"] for x in complete)
    outputs = [x["output"] for x in daily if x["output"] is not None]
    targets = [x["target"] for x in daily if x["target"] is not None]
    by_machine = _group(events, "machine")
    # ชั่วโมงสูญเสีย = ปัญหาเครื่องจักรเท่านั้น (ไม่รวมงานปรับปรุงและ Stop Line) ไม่ขึ้นกับประเภทที่เลือก
    losses = [e for e in all_events if e["type"] == "problem" and not e["record_only"]]
    # งานปรับปรุง — นับในช่วงวันที่ ไม่ขึ้นกับประเภทที่เลือกดูกราฟ
    improves = [e for e in all_events if e["type"] == "improve"]
    open_items = [e for e in improves if e["status"] in OPEN_STATUSES]
    pending = sum(1 for e in open_items if e["status"] == "pending")

    kpis = {
        "target": target,
        "output": output,
        "diff": output - target,
        "achievement_pct": round(output / target * 100, 1) if target else None,
        "days_complete": len(complete),
        "days_recorded": len(daily),
        "holiday_days": sum(1 for x in daily if x["holiday"]),
        # วันที่ยังขาดเป้าหมาย/ยอดผลิต (รวมวันที่ไม่ได้บันทึกเลย) ไม่นับวันหยุดและวันในอนาคต
        "missing_days": sum(1 for d in _all_days(d_from, d_to)
                            if _missing(daily_by_date.get(d) or _daily_dict(d, None), today)),
        "hours": _sum_hours(events),
        "count": len(events),
        "loss_hours": _sum_hours(losses),
        "loss_count": len(losses),
        "by_type": _type_counts(all_events),
        "cleaning_count": sum(1 for e in all_events if e["cleaning"]),
        "cleaning_hours": _sum_hours([e for e in all_events if e["cleaning"]]),
        "top_machine": by_machine[0] if by_machine else None,
        "avg_output": round(sum(outputs) / len(outputs)) if outputs else None,
        "avg_target": round(sum(targets) / len(targets)) if targets else None,
        "days_output": len(outputs),
        "improve_count": len(improves),
        "done_count": sum(1 for e in improves if e["status"] == "done"),
        "open_count": len(open_items),
        "pending_count": pending,
        "in_progress_count": len(open_items) - pending,
        "overdue_count": sum(1 for e in open_items if e["due_date"] and e["due_date"] < today),
    }
    return kpis, events, all_events


# กล่องยอดผลิต / กล่องรายการ — ใช้ตัดสินว่าช่วงเปรียบเทียบ "ไม่มีข้อมูล" (v1.5 A1)
PRODUCTION_KPIS = ("target", "output", "diff", "achievement_pct", "avg_output", "avg_target")
RECORD_KPIS = ("hours", "count", "loss_hours", "loss_count", "by_type", "top_machine", "improve_count",
               "done_count", "open_count", "pending_count", "in_progress_count", "overdue_count")


def _blank_missing(k: dict, has_events: bool) -> dict:
    """ช่วงเปรียบเทียบ: ค่าที่ไม่มีข้อมูลให้เทียบ → None (หน้าจอแสดง "ไม่มีข้อมูล" แทนการเทียบกับ 0).
    ยอดผลิต: ไม่มีวันที่มีทั้งเป้าและยอดผลิต / รายการ: ไม่มีการบันทึกใด ๆ เลย (ยอดผลิตและรายการ)."""
    k = dict(k)
    if not k["days_complete"]:
        k.update(dict.fromkeys(PRODUCTION_KPIS))
    if not has_events and not k["days_recorded"]:
        k.update(dict.fromkeys(RECORD_KPIS))
    return k


@app.get("/api/dashboard")
def dashboard(
    d_from: date = Query(..., alias="from"),
    d_to: date = Query(..., alias="to"),
    type: str = "problem",
    compare: str = "prev",
    c_from: date | None = Query(None, alias="cfrom"),
    c_to: date | None = Query(None, alias="cto"),
    conn=Depends(get_conn),
):
    _check_range(d_from, d_to)
    type = _parse_type(type, DASHBOARD_TYPES)
    if compare not in COMPARE_MODES:
        raise HTTPException(422, "รูปแบบการเปรียบเทียบไม่ถูกต้อง")
    kpis, events, all_events = _kpis(conn, d_from, d_to, type)
    cmp_range = _compare_range(compare, d_from, d_to, c_from, c_to)
    comparison = None
    if cmp_range:
        cmp_kpis, _events, cmp_all = _kpis(conn, cmp_range[0], cmp_range[1], type)
        cmp_kpis = _blank_missing(cmp_kpis, bool(cmp_all))
        comparison = {"mode": compare, "label": COMPARE_LABELS[compare],
                      "from": cmp_range[0].isoformat(), "to": cmp_range[1].isoformat(), "kpis": cmp_kpis}
    # งานปรับปรุงในช่วง แบ่ง 4 กลุ่มไม่นับซ้อน (รวม = งานปรับปรุงทั้งหมด = 100%) — v1.8
    today = date.today().isoformat()
    improves = [e for e in all_events if e["type"] == "improve"]
    overdue = [e for e in improves if e["status"] in OPEN_STATUSES and e["due_date"] and e["due_date"] < today]
    ontime = lambda st: sum(1 for e in improves if e["status"] == st and e not in overdue)  # noqa: E731
    return {
        "line_name": db.get_settings(conn)["line_name"],
        "from": d_from.isoformat(), "to": d_to.isoformat(), "type": type,
        "kpis": kpis,
        "compare": comparison,
        "charts": {
            # v1.9: ทุกเครื่องใน Master ตามลำดับ (แม้ไม่มีข้อมูล) + เครื่องอื่นที่มีข้อมูลต่อท้าย
            "machine": _group(events, "machine", keep=[r["name"] for r in conn.execute(
                "SELECT name FROM master_items WHERE kind = 'machine' ORDER BY sort_order, name COLLATE NOCASE")]),
            "size": _group(events, "size"),
            # กะ: เฉพาะปัญหาเสมอ ไม่ขึ้นกับประเภทที่เลือก (v1.8)
            "shift": _group([e for e in all_events if e["type"] == "problem" and not e["record_only"]], "shift",
                            SHIFT_LABELS, keep=["M", "N"]),
            # key = ค่าตัวกรองสถานะของรายงาน (คลิกแท่ง → จำนวนรายการเท่ากับแท่ง)
            "improve": [
                {"key": "done", "label": "เสร็จแล้ว", "count": kpis["done_count"]},
                {"key": "pending_ontime", "label": "รอดำเนินการ", "count": ontime("pending")},
                {"key": "in_progress_ontime", "label": "ระหว่างดำเนินการ", "count": ontime("in_progress")},
                {"key": "overdue", "label": "เกินกำหนด", "count": len(overdue)},
            ],
        },
    }


# ---------- Backup / Restore ----------

@app.get("/api/backups")
def get_backups():
    return backup.list_backups()


@app.post("/api/backups", status_code=201)
def make_backup():
    return backup.create_backup("manual")


@app.get("/api/backups/{name}")
def download_backup(name: str):
    path = backup.resolve_backup(name)
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/backups/{name}/restore")
def restore_backup(name: str):
    return backup.restore_from_zip(backup.resolve_backup(name))


@app.post("/api/restore-upload")
def restore_upload(file: UploadFile = File(...)):
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "upload.zip"
        with open(target, "wb") as out:
            shutil.copyfileobj(file.file, out, length=1024 * 1024)
        if target.stat().st_size > backup.MAX_UPLOAD_BYTES:
            raise backup.BackupError("ไฟล์มีขนาดใหญ่เกินไป")
        return backup.restore_from_zip(target)


# ---------- Pages ----------

_PAGES = {"/": "index.html", "/report": "report.html", "/dashboard": "dashboard.html", "/settings": "settings.html"}


_ASSET_REF = re.compile(r'((?:src|href)="/static/(?:js|css)/[^"?]+\.(?:js|css))"')


def _page_route(filename: str):
    def handler():
        # v1.10.3 ใส่เลขเวอร์ชันท้ายลิงก์ JS/CSS (?v=1.10.3) — หน้า HTML ไม่ถูก cache (no-store) จึงได้ลิงก์ใหม่ทุกครั้งที่อัปเดต
        # Browser ที่จำไฟล์ JS/CSS เวอร์ชันเก่าไว้ต้องโหลดใหม่เอง ไม่ต้องกด Ctrl+F5
        html = (config.STATIC_DIR / filename).read_text(encoding="utf-8")
        html = _ASSET_REF.sub(lambda m: f'{m.group(1)}?v={config.APP_VERSION}"', html)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})
    return handler


for _path, _file in _PAGES.items():
    app.add_api_route(_path, _page_route(_file), methods=["GET"], include_in_schema=False)

class _RevalidatedStatic(StaticFiles):
    """ไฟล์ JS/CSS ตรวจกับ Server ทุกครั้ง (v1.10.2) — เดิมไม่สั่ง Cache ทำให้ Browser จำไฟล์เวอร์ชันเก่าไว้ใช้ต่อหลังอัปเดตโปรแกรม
    (ยังใช้ ETag: ไฟล์ไม่เปลี่ยน = ตอบ 304 ไม่ส่งไฟล์ซ้ำ)"""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/static", _RevalidatedStatic(directory=config.STATIC_DIR), name="static")
