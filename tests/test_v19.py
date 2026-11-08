"""v1.9: คิดชั่วโมงจากยอดผลิต, เป้าผลิต/ชม. ค้างไว้, เลื่อนลำดับ Master, ตัวกรองสถานะ "ยังไม่เสร็จ"."""
import pytest

from app.timecalc import calc_rate_hours
from conftest import event

MONTH = {"from": "2026-10-01", "to": "2026-10-31"}


def rate(**kw):
    # v1.10: โหมดยอดผลิตต้องมีเวลา (19.00–21.00 = 3 ชั่วโมง) — กะคิดจากเวลาเริ่ม
    body = event(time_from="19.00", time_to="21.00", rate_target=6000, rate_actuals=[4500, 3000, 5400], machine="Latex")
    body.update(kw)
    return body


@pytest.mark.parametrize("target, actuals, hours", [
    (6000, [4500], 0.25),                 # 1 ชม. ผลิตได้ 75% → เสีย 15 นาที
    (6000, [4500, 3000, 5400], 0.85),     # (1500 + 3000 + 600) ÷ 6000
    (6000, [0, 0], 2.0),                  # หยุดทั้ง 2 ชม.
    (6000, [6000], 0.0),
    (6000, [7000, 4000], 0.17),           # ชั่วโมงที่เกินเป้าหักกับชั่วโมงที่ขาด: (−1000 + 2000) ÷ 6000
    (6000, [7000], 0.0),                  # เกินเป้าทั้งหมด → 0 (ไม่ติดลบ, ไม่เตือน)
])
def test_rate_hours_formula(target, actuals, hours):
    assert calc_rate_hours(target, actuals) == hours


def test_rate_event_saved_and_counted(client):
    r = client.post("/api/events", json=rate())
    assert r.status_code == 201, r.text
    e = r.json()
    assert (e["hours"], e["shift"], e["shift_label"], e["time_from"], e["time_to"]) == (0.85, "N", "ดึก", "19.00", "21.00")
    assert (e["rate_target"], e["rate_actuals"]) == (6000, [4500, 3000, 5400])
    # เป้าผลิต/ชม. ค้างไว้ใช้ครั้งต่อไป
    assert client.get("/api/settings").json()["rate_target"] == "6000"
    # นับในชั่วโมงสูญเสียและกราฟตามปกติ
    k = client.get("/api/dashboard", params=MONTH).json()["kpis"]
    assert (k["loss_hours"], k["loss_count"]) == (0.85, 1)
    shift = {g["key"]: g["hours"] for g in client.get("/api/dashboard", params=MONTH).json()["charts"]["shift"]}
    assert shift == {"M": 0, "N": 0.85}
    # แก้ไข: เป้าใหม่ค้างไว้แทน, กลับเป็นโหมดเวลาได้
    e2 = client.put(f"/api/events/{e['id']}", json=rate(rate_target=5000, rate_actuals=[4000])).json()
    assert e2["hours"] == 0.2 and client.get("/api/settings").json()["rate_target"] == "5000"
    e3 = client.put(f"/api/events/{e['id']}", json=event(time_from="7", time_to="8", rate_actuals=[])).json()
    assert (e3["hours"], e3["rate_actuals"], e3["rate_target"], e3["shift"]) == (2, None, None, "M")


def test_rate_event_validation(client):
    def err(**kw):
        r = client.post("/api/events", json=rate(**kw))
        assert r.status_code == 422, r.text
        return r.json()["detail"]
    assert "เป้าผลิต" in err(rate_target="")
    assert "เวลาเริ่ม" in err(time_from="")                                  # v1.10 เวลาบังคับ
    assert "3 ชั่วโมง" in err(rate_actuals=[1, 2, 3, 4])                       # เกินจำนวนชั่วโมงในช่วงเวลา
    assert "เครื่องจักร" in err(machine="")
    assert "ปัญหาเครื่องจักร" in err(type="improve", status="pending")
    assert "ปัญหาเครื่องจักร" in err(stop_line=True, end_date="2026-10-13")
    assert client.post("/api/events", json=rate(rate_actuals=[-1])).status_code == 422
    assert client.post("/api/events", json=rate(rate_target=0)).status_code == 422
    # ผลิตได้มากกว่าเป้า → บันทึกได้ ไม่เตือน
    assert client.post("/api/events", json=rate(rate_actuals=[6500])).json()["hours"] == 0


def test_rate_event_sorted_by_shift_and_in_report(client):
    client.post("/api/events", json=event(time_from="7", time_to="8"))           # เช้า 7.00
    client.post("/api/events", json=event(time_from="19", time_to="20"))         # ดึก 19.00
    client.post("/api/events", json=rate(time_from="18", time_to="18", rate_actuals=[3000]))  # v1.10 เรียงตามเวลา
    client.post("/api/events", json=rate(time_from="6", time_to="6", rate_actuals=[3000]))
    evs = client.get("/api/events", params={"date": "2026-10-13"}).json()
    assert [(e["shift"], e["time_from"]) for e in evs] == [("M", "06.00"), ("M", "07.00"), ("N", "18.00"), ("N", "19.00")]
    days = client.get("/api/report", params={**MONTH, "shift": "N"}).json()["days"]
    assert sum(len(d["events"]) for d in days) == 2


def test_master_move(client):
    m = client.get("/api/master").json()["machine"]
    trim = next(x for x in m if x["name"] == "Trim")
    after = client.post(f"/api/master/machine/{trim['id']}/move", params={"dir": "up"}).json()["machine"]
    assert [x["name"] for x in after][:3] == ["Trim", "Press", "Aneal"]
    first = client.post(f"/api/master/machine/{trim['id']}/move", params={"dir": "up"}).json()["machine"]
    assert first[0]["name"] == "Trim"                                       # บนสุดแล้ว ไม่เปลี่ยน
    back = client.post(f"/api/master/machine/{trim['id']}/move", params={"dir": "down"}).json()["machine"]
    assert [x["name"] for x in back][:2] == ["Press", "Trim"]
    # กราฟเครื่องจักรใช้ลำดับนี้
    labels = [g["label"] for g in client.get("/api/dashboard", params=MONTH).json()["charts"]["machine"]]
    assert labels[:2] == ["Press", "Trim"]
    assert client.post(f"/api/master/machine/{trim['id']}/move", params={"dir": "x"}).status_code == 422
    assert client.post("/api/master/machine/99999/move", params={"dir": "up"}).status_code == 404


def test_machine_chart_has_all_master_plus_extra(client):
    client.post("/api/events", json=event(machine="Inside Coat"))                 # ชื่อเดิมที่ไม่อยู่ใน Master แล้ว
    labels = [g["label"] for g in client.get("/api/dashboard", params=MONTH).json()["charts"]["machine"]]
    assert labels[:13][0] == "Press" and len(labels) == 14 and labels[-1] == "Inside Coat"


def test_status_open_filter(client):
    client.post("/api/events", json=event(type="improve", status="pending", machine="Cap"))
    client.post("/api/events", json=event(type="improve", status="in_progress", machine="Cap"))
    client.post("/api/events", json=event(type="improve", status="done", machine="Cap"))
    days = client.get("/api/report", params={**MONTH, "status": "open"}).json()["days"]
    assert sorted(e["status"] for d in days for e in d["events"]) == ["in_progress", "pending"]
    assert client.get("/api/dashboard", params=MONTH).json()["kpis"]["open_count"] == 2


def test_rate_event_in_excel(client):
    from io import BytesIO
    from openpyxl import load_workbook
    client.post("/api/events", json=rate())
    wb = load_workbook(BytesIO(client.get("/api/report.xlsx", params=MONTH).content))
    head, row = [list(r) for r in wb["รายการ"].iter_rows(values_only=True)][:2]
    col = {h: i for i, h in enumerate(head)}
    assert row[col["ยอดผลิต/ชม. (เป้า)"]] == "4,500, 3,000, 5,400 (เป้า 6,000)"
    assert (row[col["ชม."]], row[col["กะ"]], row[col["เวลาเริ่ม"]]) == (0.85, "ดึก", "19.00")
