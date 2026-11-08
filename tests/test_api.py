from conftest import event


def stop(**kw):
    """Stop Line: วันที่เริ่ม-สิ้นสุด + ชั่วโมง (ไม่มีเวลา/กะ/Size)."""
    body = event(stop_line=True, end_date="2026-10-13", machine="", problem="ไม่มี Order",
                 time_from="", time_to="", size="")
    body.update(kw)
    return body


def improve(**kw):
    body = event(type="improve", machine="Inside Coat", problem="เปลี่ยน additive", status="pending")
    body.update(kw)
    return body


def test_seed_master_and_settings(client):
    m = client.get("/api/master").json()
    # v2: MONDAY Cleaning / Change Size ย้ายมาอยู่ในเครื่องจักร, STOP LINE กลายเป็นปุ่ม Stop Line
    # v6 (v1.9): เครื่องจริงของ Line ตามลำดับจริง — ไม่มี Inside Coat / MONDAY Cleaning / Change Size
    assert [x["name"] for x in m["machine"]] == ["Press", "Trim", "Aneal", "Inside", "IBO", "Base", "DO-BC", "Print",
                                                 "DO-PT", "Cap", "Latex", "Accu.", "Pack"]
    assert "stop" not in m
    assert [x["name"] for x in m["size"]] == ["34.92", "28"]
    assert m["person"] == []
    s = client.get("/api/settings").json()
    assert s["line_name"] == "T14" and s["morning_start"] == "06.00" and s["night_start"] == "18.00"


def test_daily_output_diff_sign(client):
    assert client.get("/api/daily/2026-10-06").json()["saved"] is False
    r = client.put("/api/daily/2026-10-06", json={"target": 110000, "output": 102564}).json()
    assert r["diff"] == -7436 and r["saved"] is True
    r = client.put("/api/daily/2026-10-06", json={"target": 100000, "output": 102564}).json()
    assert r["diff"] == 2564
    r = client.put("/api/daily/2026-10-07", json={"target": 100000, "output": None}).json()
    assert r["diff"] is None
    bad = client.put("/api/daily/2026-10-07", json={"target": -1, "output": 5})
    assert bad.status_code == 422 and "เป้าหมาย" in bad.json()["detail"]


def test_event_crud_computes_hours_and_shift(client):
    r = client.post("/api/events", json=event(time_from="19", time_to="3.00"))
    assert r.status_code == 201
    e = r.json()
    assert e["time_from"] == "19.00" and e["time_to"] == "03.00"
    assert e["hours"] == 9 and e["shift"] == "N" and e["shift_label"] == "ดึก"

    e2 = client.put(f"/api/events/{e['id']}", json=event(time_from="7.00", time_to="8.00")).json()
    assert e2["hours"] == 2 and e2["shift"] == "M"

    assert client.delete(f"/api/events/{e['id']}").status_code == 200
    assert client.get("/api/events", params={"date": "2026-10-13"}).json() == []
    assert client.delete(f"/api/events/{e['id']}").status_code == 404


def test_problem_has_no_due_responsible_status(client):
    e = client.post("/api/events", json=event(status="pending", due_date="2026-10-20", responsible="สมชาย")).json()
    assert e["status"] is None and e["due_date"] is None and e["responsible"] == ""


def test_improve_status_three_values(client):
    e = client.post("/api/events", json=improve(status="")).json()
    assert e["status"] == "pending" and e["status_label"] == "รอดำเนินการ"  # ค่าเริ่มต้น
    for code, label in (("in_progress", "ระหว่างดำเนินการ"), ("done", "เสร็จแล้ว")):
        r = client.put(f"/api/events/{e['id']}", json=improve(status=code, due_date="2026-10-30",
                                                              responsible="สมชาย")).json()
        assert r["status"] == code and r["status_label"] == label and r["responsible"] == "สมชาย"
    assert client.post("/api/events", json=improve(status="open")).status_code == 422


def test_event_validation_messages_in_thai(client):
    r = client.post("/api/events", json=event(time_from="25.00", machine="  ", problem=""))
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "เวลาเริ่ม" in detail and "ปัญหา" in detail  # เครื่องจักรตรวจในขั้นถัดไป (ทดสอบด้านล่าง)
    r = client.post("/api/events", json=event(type="stop"))
    assert r.status_code == 422 and "ประเภท" in r.json()["detail"]
    r = client.post("/api/events", json=event(machine=""))
    assert r.status_code == 422 and "เครื่องจักร" in r.json()["detail"]
    r = client.post("/api/events", json=event(time_from=""))
    assert r.status_code == 422 and "เวลาเริ่ม" in r.json()["detail"]


def test_events_sorted_by_production_day(client):
    for t in ("1.00", "19.00", "7.00", "13.00"):
        client.post("/api/events", json=event(time_from=t, time_to=t))
    times = [e["time_from"] for e in client.get("/api/events", params={"date": "2026-10-13"}).json()]
    assert times == ["07.00", "13.00", "19.00", "01.00"]


def test_shift_follows_settings(client):
    s = client.put("/api/settings", json={"line_name": "T14", "default_target": "120000",
                                           "morning_start": "7.00", "night_start": "19.00"})
    assert s.status_code == 200 and s.json()["default_target"] == "120000"
    assert client.post("/api/events", json=event(time_from="6.00", time_to="6.00")).json()["shift"] == "N"
    bad = client.put("/api/settings", json={"line_name": "T14", "default_target": "",
                                             "morning_start": "19.00", "night_start": "7.00"})
    assert bad.status_code == 422


def test_master_add_rename_delete_duplicate(client):
    r = client.post("/api/master/person", json={"name": " สมชาย "})
    assert r.status_code == 201 and r.json()["name"] == "สมชาย"
    assert client.post("/api/master/person", json={"name": "สมชาย"}).status_code == 409
    pid = r.json()["id"]
    assert client.put(f"/api/master/person/{pid}", json={"name": "สมชาย ใจดี"}).status_code == 200
    assert client.delete(f"/api/master/person/{pid}").status_code == 200
    assert client.delete(f"/api/master/person/{pid}").status_code == 404
    assert client.post("/api/master/unknown", json={"name": "x"}).status_code == 422


def test_report_groups_days_and_totals(client):
    client.put("/api/daily/2026-10-12", json={"target": 60000, "output": 58254})
    client.put("/api/daily/2026-10-13", json={"target": 120000, "output": 123200})
    client.post("/api/events", json=event(date="2026-10-12", machine="MONDAY Cleaning",
                                          problem="Cleaning", time_from="7.00", time_to="13.00"))
    client.post("/api/events", json=event(date="2026-10-13"))
    client.post("/api/events", json=event(date="2026-10-14", machine="Print"))  # ไม่มียอดผลิต
    r = client.get("/api/report", params={"from": "2026-10-01", "to": "2026-10-31"}).json()
    # v1.5: แสดงทุกวันในช่วง (วันที่ไม่ได้บันทึกต้องมองเห็นได้)
    assert len(r["days"]) == 31 and r["days"][0]["date"] == "2026-10-01" and r["days"][-1]["date"] == "2026-10-31"
    has_data = [d for d in r["days"] if d["saved"] or d["events"]]
    assert [d["date"] for d in has_data] == ["2026-10-12", "2026-10-13", "2026-10-14"]
    assert has_data[0]["day_name"] == "จันทร์" and has_data[0]["diff"] == -1746
    assert has_data[2]["target"] is None and len(has_data[2]["events"]) == 1
    t = r["totals"]
    assert t["target"] == 180000 and t["output"] == 181454 and t["diff"] == 1454
    assert t["hours"] == 7 + 2 + 2 and t["count"] == 3
    assert t["by_type"] == {"problem": 3, "improve": 0, "stop_line": 0}

    only_print = client.get("/api/report", params={"from": "2026-10-01", "to": "2026-10-31",
                                                   "machine": "Print"}).json()
    assert sum(len(d["events"]) for d in only_print["days"]) == 1
    assert client.get("/api/report", params={"from": "2026-10-31", "to": "2026-10-01"}).status_code == 422


def test_pages_served(client):
    for path in ("/", "/report", "/dashboard", "/settings", "/static/vendor/chart.umd.min.js"):
        assert client.get(path).status_code == 200, path


def test_stop_line_dates_and_hours(client):
    r = client.post("/api/events", json=stop(date="2026-10-23", end_date="2026-10-25", time_from="7.00",
                                             time_to="6.00", size="28"))
    assert r.status_code == 201
    e = r.json()
    # ไม่มีเวลา/กะ/Size — ชั่วโมงเริ่มต้น = จำนวนวัน × 24
    assert e["hours"] == 72 and e["stop_line"] is True and e["type_label"] == "Stop Line"
    assert e["time_from"] is None and e["shift"] is None and e["size"] == "" and e["status"] is None
    edited = client.put(f"/api/events/{e['id']}", json=stop(date="2026-10-23", end_date="2026-10-23", hours=2)).json()
    assert edited["hours"] == 2  # ผู้ใช้แก้ชั่วโมงเองได้
    days = client.get("/api/report", params={"from": "2026-10-23", "to": "2026-10-25"}).json()["days"]
    assert [d["date"] for d in days if d["events"]] == ["2026-10-23"]  # นับที่วันที่เริ่ม


def test_stop_line_validation(client):
    bad = client.post("/api/events", json=stop(end_date=""))
    assert bad.status_code == 422 and "วันที่สิ้นสุด" in bad.json()["detail"]
    back = client.post("/api/events", json=stop(date="2026-10-23", end_date="2026-10-22"))
    assert back.status_code == 422 and "ไม่ก่อน" in back.json()["detail"]
    too_many = client.post("/api/events", json=stop(end_date="2026-10-13", hours=25))
    assert too_many.status_code == 422 and "ไม่เกิน 24" in too_many.json()["detail"]
    assert client.post("/api/events", json=stop(hours=0)).status_code == 422
    assert client.post("/api/events", json=improve(stop_line=True, end_date="2026-10-13")).status_code == 422
    normal = client.post("/api/events", json=event(end_date="2026-10-30")).json()
    assert normal["end_date"] is None and normal["stop_line"] is False


def test_events_sorted_stop_line_first(client):
    client.post("/api/events", json=event(time_from="7.00", time_to="7.00"))
    client.post("/api/events", json=stop())
    assert client.get("/api/events", params={"date": "2026-10-13"}).json()[0]["stop_line"] is True


def test_report_type_filters(client):
    client.post("/api/events", json=event())                 # ปัญหา 2h
    client.post("/api/events", json=stop(hours=5))            # Stop Line 5h
    client.post("/api/events", json=improve())                # ปรับปรุง 2h
    def run(t):
        r = client.get("/api/report", params={"from": "2026-10-01", "to": "2026-10-31", "type": t}).json()
        return r, sorted(e["type_label"] for d in r["days"] for e in d["events"])
    assert run("problem")[1] == ["ปัญหา"]
    assert run("problem_sl")[1] == ["Stop Line", "ปัญหา"]
    assert run("improve")[1] == ["การปรับปรุง"]
    assert run("stopline")[1] == ["Stop Line"]
    r, labels = run("all")
    assert labels == ["Stop Line", "การปรับปรุง", "ปัญหา"]
    t = r["totals"]
    assert t["hours"] == 4 and t["stop_line_hours"] == 5 and t["count"] == 3  # ชม.รวมไม่นับ Stop Line
    assert t["by_type"] == {"problem": 1, "improve": 1, "stop_line": 1}
    assert client.get("/api/report", params={"from": "2026-10-01", "to": "2026-10-31",
                                             "type": "x"}).status_code == 422


def test_dashboard_kpis_and_charts(client):
    client.put("/api/daily/2026-10-13", json={"target": 120000, "output": 123200})
    client.put("/api/daily/2026-10-14", json={"target": 160000, "output": 160468})
    client.put("/api/daily/2026-10-15", json={"target": 100000, "output": None})
    client.post("/api/events", json=event(time_from="7.00", time_to="8.00"))                      # Press 2h M
    client.post("/api/events", json=event(time_from="19.00", time_to="20.00"))                    # Press 2h N
    client.post("/api/events", json=event(machine="Print", size="28", time_from="1.00", time_to="1.00"))  # Print 1h N
    client.post("/api/events", json=stop(end_date="2026-10-14"))                                  # Stop Line 48h
    client.post("/api/events", json=improve(machine="Latex", due_date="2000-01-01"))              # ค้าง + เกินกำหนด
    client.post("/api/events", json=improve(machine="Latex", status="in_progress"))
    client.post("/api/events", json=improve(machine="Cap", status="done", due_date="2000-01-01"))

    d = client.get("/api/dashboard", params={"from": "2026-10-01", "to": "2026-10-31"}).json()
    k = d["kpis"]
    assert k["target"] == 280000 and k["output"] == 283668 and k["diff"] == 3668
    assert k["achievement_pct"] == 101.3 and k["days_complete"] == 2
    # Stop Line ไม่นับชั่วโมง/กราฟใด ๆ
    assert k["hours"] == 5 and k["count"] == 3
    assert k["by_type"] == {"problem": 3, "improve": 3, "stop_line": 1}
    assert {x: k["top_machine"][x] for x in ("key", "label", "hours", "count")} == \
        {"key": "Press", "label": "Press", "hours": 4, "count": 2}
    # v1.9: ทุกเครื่องใน Master ตามลำดับจริง (แม้ไม่มีข้อมูล)
    from app import db
    assert [g["label"] for g in d["charts"]["machine"]] == list(db.V6_MACHINE_ORDER)
    assert [g["label"] for g in d["charts"]["machine"] if g["count"]] == ["Press", "Print"]
    assert {g["label"]: g["count"] for g in d["charts"]["size"]} == {"34.92": 2, "28": 1}
    assert [(g["key"], g["label"], g["hours"], g["count"]) for g in d["charts"]["shift"]] == \
        [("M", "เช้า", 2, 1), ("N", "ดึก", 3, 2)]
    # งานปรับปรุงค้าง (ไม่ขึ้นกับประเภทที่เลือกดูกราฟ)
    assert (k["open_count"], k["pending_count"], k["in_progress_count"], k["overdue_count"]) == (2, 1, 1, 1)
    # v1.8: กราฟงานปรับปรุง 4 กลุ่มไม่นับซ้อน — รวม = งานปรับปรุงทั้งหมด (100%)
    imp = [(b["key"], b["count"]) for b in d["charts"]["improve"]]
    assert imp == [("done", 1), ("pending_ontime", 0), ("in_progress_ontime", 1), ("overdue", 1)], imp
    assert sum(c for _k, c in imp) == k["improve_count"]

    all_types = client.get("/api/dashboard", params={"from": "2026-10-01", "to": "2026-10-31", "type": "all"}).json()
    assert all_types["kpis"]["count"] == 6 and all_types["kpis"]["hours"] == 11
    assert all("Stop Line" != g["label"] for g in all_types["charts"]["machine"])
    for bad in ("stopline", "problem_sl", "stop"):
        assert client.get("/api/dashboard", params={"from": "2026-10-01", "to": "2026-10-31",
                                                    "type": bad}).status_code == 422


def test_old_hidden_fields_kept_in_db(client):
    """ข้อมูลเดิมของช่องที่ไม่แสดงแล้ว ยังอยู่ในฐานข้อมูล (Q3)."""
    from app import db
    e = client.post("/api/events", json=event()).json()
    conn = db.connect()
    conn.execute("UPDATE events SET responsible = 'เก่า', status = 'pending' WHERE id = ?", (e["id"],))
    conn.commit()
    conn.close()
    shown = client.get("/api/events", params={"date": "2026-10-13"}).json()[0]
    assert shown["responsible"] == "" and shown["status"] is None
    conn = db.connect()
    assert conn.execute("SELECT responsible FROM events WHERE id = ?", (e["id"],)).fetchone()[0] == "เก่า"
    conn.close()


def _drill(client, **params):
    """เรียกรายงานแบบเดียวกับที่ Dashboard ใช้ตอนคลิกแท่งกราฟ."""
    base = {"from": "2026-10-01", "to": "2026-10-31"}
    r = client.get("/api/report", params={**base, **params})
    assert r.status_code == 200, r.text
    events = [e for d in r.json()["days"] for e in d["events"]]
    return len(events), round(sum(e["hours"] for e in events), 2)


def test_chart_drilldown_matches_every_bar(client):
    """คลิกแท่งกราฟใด ๆ → จำนวนครั้ง/ชั่วโมงของรายการ ต้องเท่ากับตัวเลขบนแท่ง."""
    from app import db
    client.post("/api/events", json=event(time_from="7.00", time_to="8.00"))
    client.post("/api/events", json=event(time_from="19.00", time_to="20.00", size=""))   # Size ไม่ระบุ
    client.post("/api/events", json=event(machine="Print", size="28", time_from="1.00", time_to="1.00"))
    client.post("/api/events", json=stop(machine="Press", end_date="2026-10-14"))          # ไม่นับในกราฟ
    client.post("/api/events", json=improve(machine="Press", due_date="2000-01-01"))
    client.post("/api/events", json=improve(machine="Latex", status="in_progress", time_from="19", time_to="19"))
    client.post("/api/events", json=improve(machine="Cap", status="done", due_date="2000-01-01"))
    # ข้อมูลเดิมที่ซ่อนไว้ (ปัญหามีสถานะ / Stop Line มีกะ+Size) ต้องไม่ถูกนับ
    conn = db.connect()
    conn.execute("UPDATE events SET status = 'pending', due_date = '2000-01-01' WHERE type = 'problem' AND stop_line = 0")
    conn.execute("UPDATE events SET shift = 'N', size = '34.92' WHERE stop_line = 1")
    conn.commit()
    conn.close()

    for dash_type in ("problem", "improve", "all"):
        d = client.get("/api/dashboard", params={"from": "2026-10-01", "to": "2026-10-31", "type": dash_type}).json()
        # v1.8: แท่งตั้งแยกประเภท (ปัญหา / การปรับปรุง วางคู่กัน) — คลิกแท่งใด = เฉพาะประเภทนั้น
        for chart in ("machine", "size"):
            for bar in d["charts"][chart]:
                for part, val in bar["parts"].items():
                    if val["count"]:
                        got = _drill(client, type=part, sl=0, **{chart: bar["key"] or "__blank__"})
                        assert got == (val["count"], val["hours"]), (dash_type, chart, bar["key"], part)
        # กะ = เฉพาะปัญหาเสมอ
        assert all(b["parts"]["improve"]["count"] == 0 for b in d["charts"]["shift"])
        for bar in d["charts"]["shift"]:
            assert _drill(client, type="problem", sl=0, shift=bar["key"]) == (bar["count"], bar["hours"]), bar
        for bar in d["charts"]["improve"]:
            assert _drill(client, type="improve", status=bar["key"])[0] == bar["count"], bar
        assert sum(b["count"] for b in d["charts"]["improve"]) == d["kpis"]["improve_count"]
    assert client.get("/api/report", params={"from": "2026-10-01", "to": "2026-10-31", "shift": "X"}).status_code == 422
    assert client.get("/api/report", params={"from": "2026-10-01", "to": "2026-10-31", "status": "closed"}).status_code == 422


def test_dashboard_loss_done_and_parts(client):
    client.put("/api/daily/2026-10-13", json={"target": 100, "output": 90})
    client.put("/api/daily/2026-10-14", json={"target": 300, "output": None})
    client.post("/api/events", json=event(time_from="7.00", time_to="8.00"))                 # ปัญหา Press 2h
    client.post("/api/events", json=stop(hours=10))                                          # ไม่นับ
    client.post("/api/events", json=improve(machine="Press", status="done"))                 # ปรับปรุง Press 2h
    client.post("/api/events", json=improve(machine="Latex", status="pending", time_from="9", time_to="9"))
    d = client.get("/api/dashboard", params={"from": "2026-10-01", "to": "2026-10-31", "type": "all",
                                             "compare": "none"}).json()
    k = d["kpis"]
    # ชั่วโมงสูญเสีย = ปัญหาเท่านั้น ไม่ขึ้นกับประเภทที่เลือก
    assert (k["loss_hours"], k["loss_count"]) == (2, 1) and k["hours"] == 5
    assert (k["done_count"], k["improve_count"], k["open_count"]) == (1, 2, 1)
    assert k["avg_target"] == 200 and k["avg_output"] == 90
    assert d["compare"] is None
    press = next(g for g in d["charts"]["machine"] if g["key"] == "Press")
    assert press["hours"] == 4 and press["parts"] == {"problem": {"hours": 2, "count": 1},
                                                      "improve": {"hours": 2, "count": 1}}


def test_dashboard_compare_modes(client):
    client.put("/api/daily/2026-09-15", json={"target": 100, "output": 80})   # เดือนก่อน
    client.put("/api/daily/2025-10-15", json={"target": 100, "output": 70})   # ปีก่อน
    client.put("/api/daily/2026-10-15", json={"target": 100, "output": 120})
    client.post("/api/events", json=event(date="2026-09-20", time_from="7", time_to="9"))   # 3h เดือนก่อน
    base = {"from": "2026-10-01", "to": "2026-10-31"}
    prev = client.get("/api/dashboard", params=base).json()["compare"]       # ค่าเริ่มต้น = ช่วงก่อนหน้า
    assert (prev["mode"], prev["from"], prev["to"]) == ("prev", "2026-08-31", "2026-09-30")
    assert prev["kpis"]["output"] == 80 and prev["kpis"]["loss_hours"] == 3
    yoy = client.get("/api/dashboard", params={**base, "compare": "yoy"}).json()["compare"]
    assert (yoy["from"], yoy["to"], yoy["kpis"]["output"]) == ("2025-10-01", "2025-10-31", 70)
    custom = client.get("/api/dashboard", params={**base, "compare": "custom", "cfrom": "2026-09-01",
                                                  "cto": "2026-09-30"}).json()["compare"]
    assert (custom["label"], custom["kpis"]["output"]) == ("ช่วงที่เลือก", 80)
    leap = client.get("/api/dashboard", params={"from": "2028-02-29", "to": "2028-02-29", "compare": "yoy"}).json()
    assert leap["compare"]["from"] == "2027-02-28"
    assert client.get("/api/dashboard", params={**base, "compare": "custom"}).status_code == 422
    assert client.get("/api/dashboard", params={**base, "compare": "x"}).status_code == 422


def test_size_diameter_symbol_not_stored(client):
    e = client.post("/api/events", json=event(size="⌀34.92")).json()
    assert e["size"] == "34.92"
    r = client.post("/api/master/size", json={"name": "⌀ 30"})
    assert r.status_code == 201 and r.json()["name"] == "30"
    assert client.post("/api/master/size", json={"name": "Ø30"}).status_code == 409
