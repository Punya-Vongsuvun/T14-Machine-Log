"""v1.5: A ช่วงเปรียบเทียบไม่มีข้อมูล, E1 ยอดรวมเฉพาะวันที่มีครบ, B Export Excel."""
from datetime import date
from io import BytesIO
from urllib.parse import unquote

from openpyxl import load_workbook

from conftest import event
from test_api import improve, stop

MONTH = {"from": "2026-10-01", "to": "2026-10-31"}


# ---------- A: ช่วงเปรียบเทียบไม่มีข้อมูล ----------

def test_compare_period_without_any_data_is_null(client):
    client.put("/api/daily/2026-10-15", json={"target": 100, "output": 120})
    client.post("/api/events", json=event(date="2026-10-15", time_from="7", time_to="8"))
    c = client.get("/api/dashboard", params=MONTH).json()["compare"]["kpis"]   # ก.ย. ไม่มีอะไรเลย
    for key in ("target", "output", "diff", "achievement_pct", "avg_output", "avg_target",
                "loss_hours", "loss_count", "by_type", "top_machine", "done_count", "open_count"):
        assert c[key] is None, key
    # ช่วงปัจจุบันไม่เปลี่ยน
    k = client.get("/api/dashboard", params=MONTH).json()["kpis"]
    assert (k["target"], k["loss_hours"], k["by_type"]["problem"]) == (100, 2, 1)


def test_compare_zero_problems_is_real_value(client):
    """ช่วงเปรียบเทียบมียอดผลิตแต่ไม่มีปัญหา → 0 เป็นค่าจริง (ยังเทียบตามปกติ)."""
    client.put("/api/daily/2026-09-15", json={"target": 100, "output": 80})
    c = client.get("/api/dashboard", params=MONTH).json()["compare"]["kpis"]
    assert (c["output"], c["loss_hours"], c["by_type"]["problem"], c["done_count"]) == (80, 0, 0, 0)


def test_compare_events_only_blanks_production(client):
    """มีรายการแต่ไม่มีวันที่มีทั้งเป้าและยอดผลิต → กล่องยอดผลิต = ไม่มีข้อมูล, กล่องรายการเทียบได้."""
    client.put("/api/daily/2026-09-14", json={"target": 100, "output": None})
    client.put("/api/daily/2026-09-15", json={"target": None, "output": 90})
    client.post("/api/events", json=event(date="2026-09-20", time_from="7", time_to="9"))
    c = client.get("/api/dashboard", params=MONTH).json()["compare"]["kpis"]
    assert c["target"] is None and c["output"] is None and c["avg_output"] is None
    assert (c["loss_hours"], c["by_type"]["problem"]) == (3, 1)


def test_compare_stopline_only_counts_as_record(client):
    client.post("/api/events", json=stop(date="2026-09-20", end_date="2026-09-20", hours=5))
    c = client.get("/api/dashboard", params=MONTH).json()["compare"]["kpis"]
    assert c["target"] is None
    assert (c["loss_hours"], c["by_type"]["stop_line"]) == (0, 1)


# ---------- E1: ยอดรวมเฉพาะวันที่มีครบ ----------

def _seed_days(client):
    client.put("/api/daily/2026-10-13", json={"target": 100, "output": 90})
    client.put("/api/daily/2026-10-14", json={"target": 300, "output": None})   # ยังไม่บันทึกยอดผลิต
    client.put("/api/daily/2026-10-15", json={"target": 200, "output": 230})
    client.put("/api/daily/2026-10-16", json={"target": None, "output": 50})


def test_report_complete_totals_match_dashboard(client):
    _seed_days(client)
    t = client.get("/api/report", params=MONTH).json()["totals"]
    assert (t["target"], t["output"], t["diff"]) == (600, 370, 20)                     # ผลบวกคอลัมน์ (เดิม)
    assert (t["complete_days"], t["complete_target"], t["complete_output"]) == (2, 300, 320)
    assert t["complete_pct"] == round(320 / 300 * 100, 1)
    k = client.get("/api/dashboard", params=MONTH).json()["kpis"]
    assert (k["target"], k["output"], k["diff"], k["achievement_pct"]) == \
           (t["complete_target"], t["complete_output"], t["diff"], t["complete_pct"])


def test_report_complete_totals_empty(client):
    t = client.get("/api/report", params=MONTH).json()["totals"]
    assert (t["complete_days"], t["complete_target"], t["complete_pct"]) == (0, 0, None)


# ---------- B: Export Excel ----------

def _xlsx(client, **params):
    r = client.get("/api/report.xlsx", params={**MONTH, **params})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml")
    return r, load_workbook(BytesIO(r.content))


def _rows(ws):
    return [list(r) for r in ws.iter_rows(values_only=True)]


def _seed_events(client):
    _seed_days(client)
    p = client.post("/api/events", json=event(date="2026-10-13", time_from="7.00", time_to="8.00")).json()
    client.post(f"/api/events/{p['id']}/attachments",
                files=[("files", ("รูป.png", b"\x89PNG\r\n\x1a\n" + b"0" * 50, "image/png"))])
    client.post("/api/events", json=stop(date="2026-10-14", end_date="2026-10-15", hours=30))
    client.post("/api/events", json=improve(date="2026-10-15", due_date="2026-10-01", responsible="สมชาย"))


def test_export_sheets_and_filename(client):
    _seed_events(client)
    r, wb = _xlsx(client)
    assert wb.sheetnames == ["รายการ", "ยอดผลิตรายวัน", "สรุป"]
    cd = r.headers["content-disposition"]
    assert unquote(cd.split("filename*=UTF-8''")[1]) == "T14_รายงาน_2026-10-01_ถึง_2026-10-31.xlsx"


def test_export_events_match_report(client):
    _seed_events(client)
    _r, wb = _xlsx(client)
    rows = _rows(wb["รายการ"])
    head, body = rows[0], rows[1:]
    assert head[:5] == ["วันที่", "วัน", "ประเภท", "Stop Line", "วันที่สิ้นสุด"]
    assert head[-4:] == ["กำหนดเสร็จ", "ผู้รับผิดชอบ", "สถานะ", "ไฟล์แนบ"]
    report = client.get("/api/report", params=MONTH).json()
    assert len(body) == report["totals"]["count"] == 3
    col = {h: i for i, h in enumerate(head)}
    problem, stopline, imp = body
    # ชนิดข้อมูล: วันที่เป็นวันที่จริง, ชั่วโมงเป็นตัวเลข, Size มี ⌀
    assert problem[col["วันที่"]].date() == date(2026, 10, 13) and problem[col["วัน"]] == "อังคาร"
    assert problem[col["ชม."]] == 2 and problem[col["Size"]] == "⌀34.92" and problem[col["ไฟล์แนบ"]] == "รูป.png"
    assert (problem[col["ประเภท"]], problem[col["Stop Line"]], problem[col["สถานะ"]]) == ("ปัญหา", None, None)
    assert stopline[col["Stop Line"]] == "✓" and stopline[col["วันที่สิ้นสุด"]].date() == date(2026, 10, 15)
    assert stopline[col["ชม."]] == 30 and stopline[col["เวลาเริ่ม"]] is None and stopline[col["Size"]] is None
    assert imp[col["ประเภท"]] == "การปรับปรุง" and imp[col["ผู้รับผิดชอบ"]] == "สมชาย"
    assert imp[col["สถานะ"]] == "รอดำเนินการ (เกินกำหนด)"


def test_export_columns_follow_type_filter(client):
    _seed_events(client)
    for type_, n, text_head in (("problem", 1, "ปัญหา"), ("problem_sl", 2, "ปัญหา"), ("stopline", 1, "ปัญหา"),
                                ("improve", 1, "งานที่ปรับปรุง")):
        _r, wb = _xlsx(client, type=type_)
        head, *body = _rows(wb["รายการ"])
        assert len(body) == n, type_
        assert text_head in head
        assert ("สถานะ" in head) == (type_ == "improve"), type_
    # ตัวกรองอื่นใช้ชุดเดียวกับรายงาน
    _r, wb = _xlsx(client, type="all", status="overdue")
    assert len(_rows(wb["รายการ"])) == 2
    _r, wb = _xlsx(client, sl=0)
    assert all(r[3] != "✓" for r in _rows(wb["รายการ"])[1:])


def test_export_daily_and_summary(client):
    _seed_events(client)
    _r, wb = _xlsx(client, type="problem", machine="Press")
    daily = _rows(wb["ยอดผลิตรายวัน"])
    assert daily[0] == ["วันที่", "วัน", "เป้าหมาย", "ผลิตได้", "ผลต่าง", "หมายเหตุ"]
    assert len(daily) == 1 + 31 + 2                                   # ทุกวันในช่วง + แถวรวม 2 แถว
    assert [r[2:] for r in daily[13:17]] == [[100, 90, -10, None], [300, None, None, "ยังไม่บันทึกยอดผลิต"],
                                             [200, 230, 30, None], [None, 50, None, "ยังไม่บันทึกเป้าหมาย"]]
    assert daily[32][0].startswith("รวม (ทุกวัน") and daily[32][2:5] == [600, 370, 20]
    assert daily[33][0].startswith("รวมเฉพาะ 2 วัน") and daily[33][2:5] == [300, 320, 20]
    summary = {r[0]: r[1] for r in _rows(wb["สรุป"]) if r[0]}
    assert summary["ช่วงวันที่"] == "01/10/2026 ถึง 31/10/2026"
    assert summary["ตัวกรอง"] == "ประเภท: ปัญหา · เครื่องจักร: Press"
    assert summary["% บรรลุเป้า"] == round(320 / 300 * 100, 1) / 100
    assert summary["จำนวนรายการ"] == 1


def test_export_empty_and_invalid(client):
    _r, wb = _xlsx(client)
    assert len(_rows(wb["รายการ"])) == 1          # หัวตารางอย่างเดียว
    bad = {"from": "2026-10-31", "to": "2026-10-01"}
    assert client.get("/api/report.xlsx", params=bad).status_code == 422
    assert client.get("/api/report.xlsx", params={**MONTH, "type": "x"}).status_code == 422
    assert client.get("/api/report.xlsx", params={**MONTH, "shift": "X"}).status_code == 422


# ---------- E2: วันที่ขาดข้อมูล + วันหยุด ----------

def test_daily_holiday_saved_and_optional_values(client):
    assert client.get("/api/daily/2026-10-11").json()["holiday"] is False
    r = client.put("/api/daily/2026-10-11", json={"target": None, "output": None, "holiday": True})
    assert r.status_code == 200 and r.json()["holiday"] is True and r.json()["saved"] is True
    # ยกเลิกวันหยุดได้; ไม่ส่ง holiday = ไม่ใช่วันหยุด (client เดิม)
    assert client.put("/api/daily/2026-10-11", json={"target": 100, "output": 90}).json()["holiday"] is False


def test_report_missing_and_holiday_flags(client):
    client.put("/api/daily/2026-10-10", json={"target": 100, "output": 90})
    client.put("/api/daily/2026-10-11", json={"target": None, "output": None, "holiday": True})
    client.put("/api/daily/2026-10-12", json={"target": 100, "output": None})
    client.put("/api/daily/2026-10-13", json={"target": 50, "output": 60, "holiday": True})   # วันหยุดที่ทำ OT
    r = client.get("/api/report", params={"from": "2026-10-09", "to": "2026-10-13"}).json()
    flags = {d["date"]: (d["holiday"], d["missing"]) for d in r["days"]}
    assert flags == {"2026-10-09": (False, "both"),       # ไม่ได้บันทึกเลย
                     "2026-10-10": (False, ""),
                     "2026-10-11": (True, ""),            # วันหยุดไม่ถือว่าขาด
                     "2026-10-12": (False, "output"),
                     "2026-10-13": (True, "")}
    t = r["totals"]
    assert (t["holiday_days"], t["missing_days"]) == (2, 2)
    # วันหยุดที่กรอกครบยังนับตามปกติ (สูตรไม่เปลี่ยน)
    assert (t["complete_days"], t["complete_target"], t["complete_output"]) == (2, 150, 150)


def test_future_days_not_missing(client):
    r = client.get("/api/report", params={"from": "2099-01-01", "to": "2099-01-03"}).json()
    assert len(r["days"]) == 3 and all(d["missing"] == "" for d in r["days"])
    assert r["totals"]["missing_days"] == 0


def test_dashboard_holiday_and_missing_days(client):
    client.put("/api/daily/2026-10-10", json={"target": 100, "output": 90})
    client.put("/api/daily/2026-10-11", json={"target": None, "output": None, "holiday": True})
    client.put("/api/daily/2026-10-12", json={"target": 100, "output": None})
    k = client.get("/api/dashboard", params={"from": "2026-10-09", "to": "2026-10-12"}).json()["kpis"]
    assert (k["days_complete"], k["holiday_days"], k["missing_days"]) == (1, 1, 2)
    assert (k["target"], k["output"]) == (100, 90)                       # สูตรเดิม


def test_export_holiday_note(client):
    client.put("/api/daily/2026-10-11", json={"target": None, "output": None, "holiday": True})
    _r, wb = _xlsx(client)
    daily = _rows(wb["ยอดผลิตรายวัน"])
    assert daily[11][5] == "วันหยุด" and daily[1][5] == "ยังไม่บันทึกเป้าหมายและยอดผลิต"
    summary = {r[0]: r[1] for r in _rows(wb["สรุป"]) if r[0]}
    assert summary["วันหยุด (วัน)"] == 1
