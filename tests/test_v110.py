"""v1.10: Monday Cleaning (บันทึกอย่างเดียว), แก้วันที่ของรายการ + ย้ายยอดผลิตที่กรอกผิดวัน, โหมดยอดผลิตมีช่วงเวลา."""
import sqlite3
from io import BytesIO

import pytest

from app import backup, config, db
from app.timecalc import format_time, parse_time, rate_slots
from conftest import event

MONTH = {"from": "2026-10-01", "to": "2026-10-31"}


def cleaning(**kw):
    body = event(date="2026-10-12", time_from="7.00", time_to="10.00", machine="", size="34.92",
                 problem="", corrective="", planned_stop="cleaning")
    body.update(kw)
    return body


def rate(**kw):
    body = event(time_from="9.00", time_to="10.00", rate_target=7000, rate_actuals=[3500], machine="Latex")
    body.update(kw)
    return body


def _events(client, **params):
    days = client.get("/api/report", params={**MONTH, **params}).json()["days"]
    return [e for d in days for e in d["events"]]


# ---------- 1. Monday Cleaning ----------

def test_cleaning_saved_as_record_only(client):
    r = client.post("/api/events", json=cleaning())
    assert r.status_code == 201, r.text
    e = r.json()
    # 7.00–10.00 = 4 ชม. (สูตรรวมต้น-ท้ายเหมือนเดิม), กะคิดจากเวลา, ไม่มี Size, รายละเอียดว่าง = Monday Cleaning
    assert (e["hours"], e["shift"], e["size"], e["machine"], e["problem"]) == (4, "M", "", "", "Monday Cleaning")
    assert (e["cleaning"], e["record_only"], e["stop_line"], e["type_label"]) == (True, True, False, "Monday Cleaning")
    assert (e["due_date"], e["responsible"], e["status"]) == (None, "", None)
    # เครื่องจักรระบุได้ (ไม่บังคับ)
    e2 = client.post("/api/events", json=cleaning(machine="Press", problem="ล้างแม่พิมพ์")).json()
    assert (e2["machine"], e2["problem"]) == ("Press", "ล้างแม่พิมพ์")


def test_cleaning_not_counted_in_hours_or_charts(client):
    client.post("/api/events", json=event(date="2026-10-12", time_from="11", time_to="11"))   # ปัญหา 1 ชม.
    client.post("/api/events", json=cleaning())                                                 # Cleaning 4 ชม.
    client.post("/api/events", json=cleaning(machine="Press", time_from="13", time_to="14"))   # Cleaning 2 ชม. ระบุเครื่อง
    t = client.get("/api/report", params=MONTH).json()["totals"]
    assert (t["hours"], t["count"], t["cleaning_count"], t["cleaning_hours"]) == (1, 3, 2, 6)
    assert t["by_type"] == {"problem": 1, "improve": 0, "stop_line": 0}
    d = client.get("/api/dashboard", params={**MONTH, "type": "all"}).json()
    k = d["kpis"]
    assert (k["hours"], k["count"], k["loss_hours"], k["loss_count"]) == (1, 1, 1, 1)
    assert (k["cleaning_count"], k["cleaning_hours"]) == (2, 6)
    press = next(g for g in d["charts"]["machine"] if g["label"] == "Press")
    assert (press["hours"], press["count"]) == (1, 1)                         # Cleaning ของ Press ไม่ลงกราฟ
    assert sum(g["hours"] for g in d["charts"]["shift"]) == 1
    assert all(g["label"] != "Monday Cleaning" for g in d["charts"]["machine"])


def test_cleaning_report_filters(client):
    client.post("/api/events", json=event(date="2026-10-12"))
    client.post("/api/events", json=cleaning())
    client.post("/api/events", json=event(stop_line=True, end_date="2026-10-12", date="2026-10-12", machine="",
                                          problem="ไม่มี Order"))
    kinds = lambda **p: sorted(e["type_label"] for e in _events(client, **p))  # noqa: E731
    assert kinds(type="problem") == ["ปัญหา"]
    assert kinds(type="cleaning") == ["Monday Cleaning"]
    assert kinds(type="problem_sl") == ["Monday Cleaning", "Stop Line", "ปัญหา"]
    assert kinds(type="all", sl=0) == ["ปัญหา"]                                 # ลิงก์จาก Dashboard
    assert kinds(type="stopline") == ["Stop Line"]


def test_cleaning_validation(client):
    def err(**kw):
        r = client.post("/api/events", json=cleaning(**kw))
        assert r.status_code == 422, r.text
        return r.json()["detail"]
    assert "เวลาเริ่ม" in err(time_from="")
    assert "เวลาสิ้นสุด" in err(time_to="")
    assert "กรอบปัญหา" in err(type="improve", status="pending")
    assert "กรอบปัญหา" in err(stop_line=True, end_date="2026-10-12")
    assert "ยอดผลิต" in err(rate_target=6000, rate_actuals=[3000])
    assert client.post("/api/events", json=cleaning(planned_stop="other")).status_code == 422
    # แก้ไขกลับเป็นปัญหาเครื่องจักรได้ (เครื่องจักรบังคับอีกครั้ง)
    eid = client.post("/api/events", json=cleaning()).json()["id"]
    assert client.put(f"/api/events/{eid}", json=event(date="2026-10-12", machine="")).status_code == 422
    back = client.put(f"/api/events/{eid}", json=event(date="2026-10-12")).json()
    assert (back["cleaning"], back["record_only"], back["machine"]) == (False, False, "Press")


def test_cleaning_in_excel(client):
    from openpyxl import load_workbook
    client.post("/api/events", json=cleaning())
    wb = load_workbook(BytesIO(client.get("/api/report.xlsx", params=MONTH).content))
    head, row = [list(r) for r in wb["รายการ"].iter_rows(values_only=True)][:2]
    col = {h: i for i, h in enumerate(head)}
    assert (row[col["Monday Cleaning"]], row[col["ชม."]], row[col["เวลาเริ่ม"]]) == ("✓", 4, "07.00")
    summary = {r[0]: r[1] for r in wb["สรุป"].iter_rows(values_only=True) if r[0]}
    assert summary["Monday Cleaning (ครั้ง)"] == 1 and summary["ชั่วโมง Monday Cleaning"] == 4
    assert summary["ชั่วโมงรวม (ไม่รวม Stop Line / Monday Cleaning)"] == 0


def test_upgrade_v6_to_v7_converts_monday_cleaning(home):
    config.DATA_DIR.mkdir(parents=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    for v in range(1, 7):
        conn.execute("BEGIN")
        db._MIGRATIONS[v](conn)
        conn.execute(f"PRAGMA user_version = {v}")
        conn.commit()
    rows = [  # (date, type, stop_line, from, to, hours, shift, machine, problem, rate_actuals)
        ("2026-10-12", "problem", 0, "07.00", "13.00", 7, "M", "MONDAY Cleaning", "Cleaning", None),
        ("2026-10-19", "problem", 0, "07.00", "12.00", 6, "M", " monday cleaning ", "ล้างเครื่อง", None),
        ("2026-10-13", "problem", 0, "07.00", "08.00", 2, "M", "Press", "หลอดติด", None),
        ("2026-10-14", "improve", 0, "07.00", "08.00", 2, "M", "MONDAY Cleaning", "งานปรับปรุง", None),
        ("2026-10-15", "problem", 1, None, None, 24, None, "MONDAY Cleaning", "Stop Line", None),
        ("2026-10-16", "problem", 0, None, None, 0.5, "M", "MONDAY Cleaning", "ยอดผลิต", "[3500]"),
    ]
    conn.executemany("INSERT INTO events(date, type, stop_line, time_from, time_to, hours, shift, machine, problem, "
                     "rate_actuals) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    from app.main import app  # lifespan: Backup ก่อนอัปเกรด แล้วแปลงเป็น v7
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        assert "pre-upgrade" in {b["kind"] for b in backup.list_backups()}
        evs = {e["problem"]: e for e in _events(c, type="all")}
    assert db.current_version() == db.SCHEMA_VERSION
    for p, hours in (("Cleaning", 7), ("ล้างเครื่อง", 6)):
        assert (evs[p]["cleaning"], evs[p]["machine"], evs[p]["hours"], evs[p]["time_from"]) == (True, "", hours, "07.00")
    for p in ("หลอดติด", "งานปรับปรุง", "Stop Line", "ยอดผลิต"):                   # ไม่แปลง
        assert not evs[p]["cleaning"], p
    assert evs["งานปรับปรุง"]["machine"] == "MONDAY Cleaning"


# ---------- 2. แก้วันที่ของรายการ / ย้ายยอดผลิตที่กรอกผิดวัน ----------

def test_edit_event_date_moves_it(client):
    e = client.post("/api/events", json=event(date="2026-10-12")).json()
    moved = client.put(f"/api/events/{e['id']}", json=event(date="2026-10-14", problem="แก้ข้อความด้วย")).json()
    assert (moved["id"], moved["date"], moved["problem"]) == (e["id"], "2026-10-14", "แก้ข้อความด้วย")
    assert client.get("/api/events", params={"date": "2026-10-12"}).json() == []
    assert [x["id"] for x in client.get("/api/events", params={"date": "2026-10-14"}).json()] == [e["id"]]


def test_move_daily_with_events(client):
    client.put("/api/daily/2026-10-12", json={"target": 7000, "output": 6500, "holiday": True})
    a = client.post("/api/events", json=event(date="2026-10-12")).json()
    sl = client.post("/api/events", json=event(date="2026-10-12", stop_line=True, end_date="2026-10-13",
                                               machine="", problem="ไม่มี Order")).json()
    other = client.post("/api/events", json=event(date="2026-10-11")).json()
    r = client.post("/api/daily/2026-10-12/move", json={"to": "2026-10-15", "with_events": True})
    assert r.status_code == 200, r.text
    assert r.json()["events_moved"] == 2
    d = r.json()["daily"]
    assert (d["date"], d["target"], d["output"], d["holiday"], d["saved"]) == ("2026-10-15", 7000, 6500, True, True)
    assert client.get("/api/daily/2026-10-12").json()["saved"] is False
    evs = {e["id"]: e for e in client.get("/api/events", params={"date": "2026-10-15"}).json()}
    assert set(evs) == {a["id"], sl["id"]}
    assert (evs[sl["id"]]["end_date"], evs[sl["id"]]["hours"]) == ("2026-10-16", 48)    # Stop Line 2 วันเท่าเดิม
    assert client.get("/api/events", params={"date": "2026-10-11"}).json()[0]["id"] == other["id"]  # วันอื่นไม่ยุ่ง


def test_move_daily_only_and_rules(client):
    client.put("/api/daily/2026-10-12", json={"target": 7000, "output": 6500})
    client.put("/api/daily/2026-10-13", json={"target": 1, "output": 1})
    client.post("/api/events", json=event(date="2026-10-12"))
    # ไม่เขียนทับวันที่มียอดผลิตอยู่แล้ว — ข้อมูลทั้งสองวันไม่เปลี่ยน
    r = client.post("/api/daily/2026-10-12/move", json={"to": "2026-10-13", "with_events": True})
    assert r.status_code == 409 and "ไม่เขียนทับ" in r.json()["detail"]
    assert client.get("/api/daily/2026-10-12").json()["output"] == 6500
    assert len(client.get("/api/events", params={"date": "2026-10-12"}).json()) == 1
    assert client.post("/api/daily/2026-10-12/move", json={"to": "2026-10-12"}).status_code == 422
    assert client.post("/api/daily/2026-10-20/move", json={"to": "2026-10-21"}).status_code == 404
    # ย้ายเฉพาะยอดผลิต (รายการอยู่ที่เดิม)
    r = client.post("/api/daily/2026-10-12/move", json={"to": "2026-10-14"}).json()
    assert r["events_moved"] == 0 and r["daily"]["output"] == 6500
    assert len(client.get("/api/events", params={"date": "2026-10-12"}).json()) == 1
    # ไม่มียอดผลิตแต่มีรายการ → ย้ายเฉพาะรายการได้ (ไม่ตรวจยอดผลิตปลายทาง)
    r = client.post("/api/daily/2026-10-12/move", json={"to": "2026-10-13", "with_events": True}).json()
    assert r["events_moved"] == 1 and r["daily"]["output"] == 1


# ---------- 3. โหมดยอดผลิตมีช่วงเวลา ----------

@pytest.mark.parametrize("t_from, t_to, slots", [
    ("9.00", "9.00", ["09.00"]),
    ("9.00", "10.00", ["09.00", "10.00"]),
    ("9.00", "10.30", ["09.00", "10.00"]),
    ("23.00", "1.00", ["23.00", "00.00", "01.00"]),
    ("19.00", "3.00", ["19.00", "20.00", "21.00", "22.00", "23.00", "00.00", "01.00", "02.00", "03.00"]),
])
def test_rate_slots(t_from, t_to, slots):
    assert [format_time(m) for m in rate_slots(parse_time(t_from), parse_time(t_to))] == slots


def test_rate_with_time_range(client):
    # ตัวอย่างของผู้ใช้: เป้า 7,000 ผลิต 3,500 = 0.5 ชม. — ช่วงเวลาบอกตำแหน่งเท่านั้น
    e = client.post("/api/events", json=rate(time_from="9.00", time_to="9.00")).json()
    assert (e["hours"], e["time_from"], e["time_to"], e["shift"]) == (0.5, "09.00", "09.00", "M")
    e = client.post("/api/events", json=rate(time_from="19.00", time_to="20.00", rate_actuals=[3500, 7000])).json()
    assert (e["hours"], e["shift"]) == (0.5, "N")                                 # กะจากเวลาเริ่ม
    # ส่งกะมาเอง → ไม่ใช้ (คิดจากเวลา)
    assert client.post("/api/events", json=rate(shift="N")).json()["shift"] == "M"
    # ช่องว่างไม่นับ → กรอก 1 ชั่วโมงจาก 2 ได้
    assert client.post("/api/events", json=rate(time_to="10.00", rate_actuals=[3500])).status_code == 201
    r = client.post("/api/events", json=rate(time_from="9.00", time_to="9.00", rate_actuals=[1, 2]))
    assert r.status_code == 422 and "1 ชั่วโมง" in r.json()["detail"]
    # รายงาน: เวลาเรียงตามจริง, ชั่วโมงรวมนับตามปกติ
    t = client.get("/api/report", params=MONTH).json()["totals"]
    assert t["hours"] == 2


def test_old_rate_event_without_time_still_listed_and_needs_time_on_edit(client):
    conn = db.connect()
    with conn:
        cur = conn.execute("INSERT INTO events(date, type, hours, shift, machine, problem, rate_target, rate_actuals) "
                           "VALUES ('2026-10-13', 'problem', 0.85, 'N', 'Latex', 'เก่า', 6000, '[4500, 3000, 5400]')")
    conn.close()
    e = client.get("/api/events", params={"date": "2026-10-13"}).json()[0]
    assert (e["time_from"], e["shift"], e["hours"], e["rate_actuals"]) == (None, "N", 0.85, [4500, 3000, 5400])
    r = client.put(f"/api/events/{cur.lastrowid}", json=rate(time_from="", time_to="", rate_actuals=[4500, 3000, 5400]))
    assert r.status_code == 422 and "เวลาเริ่ม" in r.json()["detail"]
    ok = client.put(f"/api/events/{cur.lastrowid}", json=rate(time_from="19", time_to="21", rate_target=6000,
                                                              rate_actuals=[4500, 3000, 5400])).json()
    assert (ok["hours"], ok["time_from"], ok["shift"]) == (0.85, "19.00", "N")


# ---------- v1.10.2: ไฟล์หน้าเว็บต้องไม่ถูก Browser จำเวอร์ชันเก่าไว้ ----------

def test_static_files_are_revalidated(client):
    r = client.get("/static/js/report.js")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers.get("etag")
    # ไฟล์ไม่เปลี่ยน → 304 (ไม่ส่งซ้ำ)
    assert client.get("/static/js/report.js", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    assert client.get("/report").headers["cache-control"] == "no-store"


def test_page_links_carry_version_so_stale_assets_are_not_reused(client):
    from app import config
    for page, js in (("/", "entry.js"), ("/report", "report.js"), ("/dashboard", "dashboard.js"), ("/settings", "settings.js")):
        r = client.get(page)
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        assert f'/static/js/{js}?v={config.APP_VERSION}"' in r.text, page
        assert f'/static/css/app.css?v={config.APP_VERSION}"' in r.text, page
        assert 'src="/static/js/common.js?v=' in r.text
    assert "/static/vendor/chart.umd.min.js" in client.get("/dashboard").text  # ไลบรารีภายนอก ไม่เปลี่ยนลิงก์ก็ได้
