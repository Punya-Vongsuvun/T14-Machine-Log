"""Export รายงานเป็น Excel (.xlsx) — ใช้ข้อมูลและตัวกรองชุดเดียวกับหน้ารายงาน (v1.5 B).

โครงสร้างไฟล์ (1 แถวต่อ 1 รายการ เพื่อกรอง / Pivot ใน Excel ได้ — ไม่รวมเซลล์):
  Sheet "รายการ"         รายการปัญหา / การปรับปรุง / Stop Line
  Sheet "ยอดผลิตรายวัน"   1 แถวต่อ 1 วัน
  Sheet "สรุป"           ช่วงวันที่ ตัวกรอง ยอดรวม
"""
import re
from datetime import date, datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app import config

TYPE_FILTER_LABELS = {
    "problem": "ปัญหา", "problem_sl": "ปัญหา+Stop Line+Cleaning", "improve": "การปรับปรุง",
    "stopline": "Stop Line", "cleaning": "Monday Cleaning", "all": "ทั้งหมด",
}
TYPE_LABELS = {"problem": "ปัญหา", "improve": "การปรับปรุง"}
SHIFT_FILTER_LABELS = {"M": "เช้า", "N": "ดึก"}
STATUS_FILTER_LABELS = {"pending": "รอดำเนินการ", "in_progress": "ระหว่างดำเนินการ", "done": "เสร็จแล้ว",
                        "overdue": "เกินกำหนด", "pending_ontime": "รอดำเนินการ (ยังไม่เกินกำหนด)",
                        "in_progress_ontime": "ระหว่างดำเนินการ (ยังไม่เกินกำหนด)",
                        "open": "ยังไม่เสร็จ (รอ + ระหว่างดำเนินการ)"}
BLANK = "__blank__"
# ตัวกรองที่เป็นปัญหา/Stop Line ล้วน → ไม่มีคอลัมน์ กำหนดเสร็จ / ผู้รับผิดชอบ / สถานะ (เหมือนหน้ารายงาน)
PROBLEM_ONLY = {"problem", "problem_sl", "stopline", "cleaning"}

DATE_FMT = "dd/mm/yyyy"
INT_FMT = "#,##0"
SIGNED_FMT = "+#,##0;-#,##0;0"
HOURS_FMT = "General"

HEAD_FONT = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="1E293B")
TOTAL_FILL = PatternFill("solid", fgColor="E9EDF4")
THIN = Side(style="thin", color="CBD5E1")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP_TOP = Alignment(wrap_text=True, vertical="top")


def size_label(v: str) -> str:
    """Size พร้อม ⌀ (ข้อมูลเก็บเฉพาะตัวเลข) — ตรงกับ sizeLabel() ใน common.js."""
    t = re.sub(r"^[⌀Øø]\s*", "", str(v or "")).strip()
    return f"⌀{t}" if t else ""


def _iso(v: str | None) -> date | None:
    return date.fromisoformat(v) if v else None


def _hours(h):
    return int(h) if float(h).is_integer() else h


def filter_text(f: dict) -> str:
    """ข้อความตัวกรอง — ตรงกับหัวรายงานบนหน้าจอ."""
    blank = lambda v: "ไม่ระบุ" if v == BLANK else v  # noqa: E731
    parts = [
        f"ประเภท: {TYPE_FILTER_LABELS[f['type']]}",
        f["machine"] and f"เครื่องจักร: {blank(f['machine'])}",
        f["size"] and f"Size: {'ไม่ระบุ' if f['size'] == BLANK else size_label(f['size'])}",
        f["shift"] and f"กะ: {SHIFT_FILTER_LABELS[f['shift']]}",
        f["status"] and f"สถานะ: {STATUS_FILTER_LABELS[f['status']]}",
        not f["sl"] and "ไม่รวม Stop Line / Monday Cleaning",
    ]
    return " · ".join(p for p in parts if p)


def filename(data: dict) -> str:
    line = re.sub(r'[\\/:*?"<>|\s]+', "_", data["line_name"]).strip("_") or "T14"
    return f"{line}_รายงาน_{data['from']}_ถึง_{data['to']}.xlsx"


def _rate_text(e: dict) -> str:
    """"4,500, 3,000 (เป้า 6,000)" — รายการที่คิดชั่วโมงจากยอดผลิต."""
    if not e.get("rate_actuals"):
        return ""
    return f"{', '.join(f'{a:,}' for a in e['rate_actuals'])} (เป้า {e['rate_target']:,})"


def _status_text(e: dict, today: str) -> str:
    if not e["status"]:
        return ""
    overdue = e["status"] != "done" and e["due_date"] and e["due_date"] < today
    return e["status_label"] + (" (เกินกำหนด)" if overdue else "")


def _event_columns(type_filter: str, today: str) -> list[tuple]:
    """[(หัวคอลัมน์, ความกว้าง, ฟังก์ชันค่า, number_format)]"""
    if type_filter == "improve":
        text_heads = ("งานที่ปรับปรุง", "รายละเอียด")
    elif type_filter in PROBLEM_ONLY:
        text_heads = ("ปัญหา", "การแก้ไข")
    else:
        text_heads = ("ปัญหา / งานที่ปรับปรุง", "การแก้ไข / รายละเอียด")
    cols = [
        ("วันที่", 12, lambda e: _iso(e["date"]), DATE_FMT),
        ("วัน", 10, lambda e: e["day_name"], None),
        ("ประเภท", 12, lambda e: TYPE_LABELS.get(e["type"], e["type"]), None),
        ("Stop Line", 10, lambda e: "✓" if e["stop_line"] else "", None),
        ("วันที่สิ้นสุด", 12, lambda e: _iso(e["end_date"]) if e["stop_line"] else None, DATE_FMT),
        ("Monday Cleaning", 10, lambda e: "✓" if e["cleaning"] else "", None),  # v1.10 บันทึกอย่างเดียว
        ("เวลาเริ่ม", 9, lambda e: e["time_from"] or "", None),
        ("เวลาสิ้นสุด", 9, lambda e: e["time_to"] or "", None),
        # v1.9 คิดชั่วโมงจากยอดผลิต (v1.10 มีเวลาเริ่ม-สิ้นสุดด้วย — รายการเก่าไม่มีเวลา)
        ("ยอดผลิต/ชม. (เป้า)", 22, lambda e: _rate_text(e), None),
        ("ชม.", 7, lambda e: _hours(e["hours"]), HOURS_FMT),
        ("กะ", 7, lambda e: e["shift_label"], None),
        ("Size", 9, lambda e: size_label(e["size"]), None),
        ("เครื่องจักร", 18, lambda e: e["machine"], None),
        (text_heads[0], 45, lambda e: e["problem"], None),
        (text_heads[1], 45, lambda e: e["corrective"], None),
    ]
    if type_filter not in PROBLEM_ONLY:
        cols += [
            ("กำหนดเสร็จ", 12, lambda e: _iso(e["due_date"]), DATE_FMT),
            ("ผู้รับผิดชอบ", 16, lambda e: e["responsible"], None),
            ("สถานะ", 24, lambda e: _status_text(e, today), None),
        ]
    cols.append(("ไฟล์แนบ", 30, lambda e: ", ".join(a["name"] for a in e["attachments"]), None))
    return cols


def _header(ws, heads: list[tuple]) -> None:
    for i, (title, width, *_rest) in enumerate(heads, start=1):
        c = ws.cell(row=1, column=i, value=title)
        c.font, c.fill, c.border = HEAD_FONT, HEAD_FILL, BORDER
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"


def _events_sheet(ws, data: dict, type_filter: str) -> int:
    today = date.today().isoformat()
    cols = _event_columns(type_filter, today)
    _header(ws, cols)
    r = 1
    for day in data["days"]:
        for e in day["events"]:
            r += 1
            row = {**e, "day_name": day["day_name"]}
            for i, (_title, _w, get, fmt) in enumerate(cols, start=1):
                c = ws.cell(row=r, column=i, value=get(row))
                c.border, c.alignment = BORDER, WRAP_TOP
                if fmt:
                    c.number_format = fmt
    if r > 1:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{r}"
    return r - 1


MISSING_NOTES = {"target": "ยังไม่บันทึกเป้าหมาย", "output": "ยังไม่บันทึกยอดผลิต",
                 "both": "ยังไม่บันทึกเป้าหมายและยอดผลิต"}
HOLIDAY_FILL = PatternFill("solid", fgColor="EEF0F3")
MISSING_FILL = PatternFill("solid", fgColor="FFF4CC")


def day_note(d: dict) -> str:
    """หมายเหตุของวัน (v1.5 E2-4): วันหยุด / ยังไม่บันทึก..."""
    return "วันหยุด" if d["holiday"] else MISSING_NOTES.get(d["missing"], "")


def _daily_sheet(ws, data: dict) -> None:
    heads = [("วันที่", 12, DATE_FMT), ("วัน", 10, None), ("เป้าหมาย", 12, INT_FMT),
             ("ผลิตได้", 12, INT_FMT), ("ผลต่าง", 12, SIGNED_FMT), ("หมายเหตุ", 30, None)]
    _header(ws, heads)
    r = 1
    for d in data["days"]:
        r += 1
        values = [_iso(d["date"]), d["day_name"], d["target"], d["output"], d["diff"], day_note(d)]
        fill = HOLIDAY_FILL if d["holiday"] else MISSING_FILL if d["missing"] else None
        for i, (v, (_t, _w, fmt)) in enumerate(zip(values, heads), start=1):
            c = ws.cell(row=r, column=i, value=v)
            c.border = BORDER
            if fmt:
                c.number_format = fmt
            if fill:
                c.fill = fill
    t = data["totals"]
    rows = [
        ("รวม (ทุกวันที่มีตัวเลข)", t["target"], t["output"], t["diff"]),
        (f"รวมเฉพาะ {t['complete_days']} วันที่มีครบ (ตรงกับ Dashboard)",
         t["complete_target"], t["complete_output"], t["complete_output"] - t["complete_target"]),
    ]
    for label, target, output, diff in rows:
        r += 1
        ws.cell(row=r, column=1, value=label)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        for i, (v, fmt) in enumerate(((target, INT_FMT), (output, INT_FMT), (diff, SIGNED_FMT)), start=3):
            c = ws.cell(row=r, column=i, value=v)
            c.number_format = fmt
        for i in range(1, len(heads) + 1):
            c = ws.cell(row=r, column=i)
            c.font, c.fill, c.border = Font(bold=True), TOTAL_FILL, BORDER
    if data["days"]:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(heads))}{len(data['days']) + 1}"


def _summary_sheet(ws, data: dict, f: dict, n_events: int) -> None:
    t = data["totals"]
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 22
    ws.column_dimensions["C"].width = 40
    ws.cell(row=1, column=1, value=f"รายงานบันทึกปัญหาและการปรับปรุงเครื่องจักร — Line {data['line_name']}").font = \
        Font(bold=True, size=14)
    pct = t["complete_pct"]
    rows = [
        ("ช่วงวันที่", f"{_dmy(data['from'])} ถึง {_dmy(data['to'])}", None, ""),
        ("ตัวกรอง", filter_text(f), None, ""),
        None,
        ("เป้าหมายรวม (ทุกวันที่มีตัวเลข)", t["target"], INT_FMT, ""),
        ("ผลิตได้รวม (ทุกวันที่มีตัวเลข)", t["output"], INT_FMT, ""),
        ("ผลต่างรวม", t["diff"], SIGNED_FMT, "คิดเฉพาะวันที่มีทั้งเป้าหมายและยอดผลิต"),
        (f"เป้าหมายรวม (เฉพาะ {t['complete_days']} วันที่มีครบ)", t["complete_target"], INT_FMT, "ตรงกับ Dashboard"),
        (f"ผลิตได้รวม (เฉพาะ {t['complete_days']} วันที่มีครบ)", t["complete_output"], INT_FMT, "ตรงกับ Dashboard"),
        ("% บรรลุเป้า", pct / 100 if pct is not None else "—", "0.0%", "ตรงกับ Dashboard"),
        ("วันหยุด (วัน)", t["holiday_days"], INT_FMT, ""),
        ("วันที่ยังขาดข้อมูลยอดผลิต (วัน)", t["missing_days"], INT_FMT, "ไม่นับวันหยุดและวันที่ยังไม่ถึง"),
        None,
        ("จำนวนรายการ", n_events, INT_FMT, ""),
        ("ปัญหา (ครั้ง)", t["by_type"]["problem"], INT_FMT, ""),
        ("การปรับปรุง (ครั้ง)", t["by_type"]["improve"], INT_FMT, ""),
        ("Stop Line (ครั้ง)", t["by_type"]["stop_line"], INT_FMT, "บันทึกอย่างเดียว"),
        ("Monday Cleaning (ครั้ง)", t["cleaning_count"], INT_FMT, "บันทึกอย่างเดียว"),
        ("ชั่วโมงรวม (ไม่รวม Stop Line / Monday Cleaning)", _hours(t["hours"]), HOURS_FMT, ""),
        ("ชั่วโมง Stop Line", _hours(t["stop_line_hours"]), HOURS_FMT, "บันทึกอย่างเดียว ไม่รวมในชั่วโมงรวม"),
        ("ชั่วโมง Monday Cleaning", _hours(t["cleaning_hours"]), HOURS_FMT, "บันทึกอย่างเดียว ไม่รวมในชั่วโมงรวม"),
        None,
        ("ส่งออกเมื่อ", datetime.now(), "dd/mm/yyyy hh:mm", f"{config.APP_NAME} v{config.APP_VERSION}"),
    ]
    r = 2
    for item in rows:
        r += 1
        if item is None:
            continue
        label, value, fmt, note = item
        ws.cell(row=r, column=1, value=label).font = Font(bold=True)
        c = ws.cell(row=r, column=2, value=value)
        c.alignment = Alignment(horizontal="left" if isinstance(value, str) else "right")
        if fmt:
            c.number_format = fmt
        if note:
            ws.cell(row=r, column=3, value=note).font = Font(color="64748B")


def _dmy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def build(data: dict, f: dict) -> bytes:
    """data = ผลของ _build_report(), f = ตัวกรองที่ผ่านการตรวจแล้ว."""
    wb = Workbook()
    ws_events = wb.active
    ws_events.title = "รายการ"
    n_events = _events_sheet(ws_events, data, f["type"])
    _daily_sheet(wb.create_sheet("ยอดผลิตรายวัน"), data)
    _summary_sheet(wb.create_sheet("สรุป"), data, f, n_events)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
