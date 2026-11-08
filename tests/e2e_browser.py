"""E2E ทดสอบผ่าน Browser (Playwright) — รันแยกจาก pytest:
1) เปิด server ด้วยโฟลเดอร์ข้อมูลทดสอบ: T14_HOME=<โฟลเดอร์ว่าง> python -m uvicorn app.main:app --port 8014
2) python tests/e2e_seed.py   (ข้อมูลตัวอย่างจากฟอร์มกระดาษ ต.ค.)
3) python tests/e2e_browser.py <โฟลเดอร์ผลลัพธ์>   (ภาพหน้าจอ/PDF เก็บใน <โฟลเดอร์>/shots/)
"""
import json
import os
from datetime import date
import sys
import urllib.request

from playwright.sync_api import expect, sync_playwright

OUT = sys.argv[1]
B = "http://127.0.0.1:8014"
CHROME = os.environ.get("CHROME", "/opt/pw-browsers/chromium-1194/chrome-linux/chrome")
SHOTS = os.path.join(OUT, "shots")
os.makedirs(SHOTS, exist_ok=True)
PNG_PATH = os.path.join(OUT, "รูปหน้างาน.png")
with open(PNG_PATH, "wb") as f:
    f.write(b"\x89PNG\r\n\x1a\n" + b"0" * 200)


def api(path):
    return json.load(urllib.request.urlopen(B + path))


errors = []
with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME)
    pg = br.new_page(viewport={"width": 1920, "height": 1080 - 130}, locale="th-TH")  # จอ 1920×1080 หักแถบ Browser/Taskbar
    pg.on("console", lambda m: m.type == "error" and errors.append(m.text))
    pg.on("pageerror", lambda e: errors.append(str(e)))
    P = lambda sel: pg.locator(f"#panel-problem {sel}")  # noqa: E731
    I = lambda sel: pg.locator(f"#panel-improve {sel}")  # noqa: E731

    # ---------- หน้าบันทึกงาน ----------
    pg.goto(B + "/?date=2026-10-13")
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("#dayName")).to_have_text("วันอังคาร")
    expect(pg.locator("#target")).to_have_value("120,000")
    expect(pg.locator("#diffBox")).to_have_text("+3,200")
    pg.fill("#output", "118000")
    expect(pg.locator("#diffBox")).to_have_text("−2,000")
    pg.click("#saveDaily")
    expect(pg.locator("#dailyState")).to_contain_text("บันทึกแล้ว")
    expect(pg.locator("#daySummary")).to_contain_text("3 รายการ")
    expect(pg.locator(".panel")).to_have_count(2)

    # ไม่ต้องเลื่อนหน้าจอ: ทั้ง 2 กรอบอยู่ในจอเดียว
    fits = pg.evaluate("[document.documentElement.scrollHeight, innerHeight]")
    assert fits[0] <= fits[1], f"ต้องเลื่อนหน้าจอ: {fits}"

    # กรอบปัญหา: ไม่มี กำหนดเสร็จ / ผู้รับผิดชอบ / สถานะ และช่องปัญหา/การแก้ไขพิมพ์อิสระ
    for f in ("dueDate", "responsible", "status"):
        expect(P(f"[data-f={f}]")).to_have_count(0)
    expect(P(".combo [data-f=problem]")).to_have_count(0)
    expect(P(".combo [data-f=corrective]")).to_have_count(0)
    expect(I(".combo [data-f=problem]")).to_have_count(0)

    # ปัญหาเครื่องจักร: ข้ามเที่ยงคืน + ไฟล์แนบ
    P("[data-f=timeFrom]").fill("19")
    P("[data-f=timeTo]").fill("3")
    expect(P("[data-f=hours]")).to_contain_text("9")
    expect(P("[data-f=shift]")).to_contain_text("ดึก")
    P("[data-f=machine]").click()
    expect(P(".combo-list:not(.hidden) li")).to_have_count(13)  # v1.9: เครื่องจริง 13 เครื่อง (ไม่มี Inside Coat / MONDAY Cleaning / Change Size)
    assert P(".combo-list:not(.hidden) li").all_inner_texts()[:4] == ["Press", "Trim", "Aneal", "Inside"]
    P(".combo-list:not(.hidden) li").filter(has_text="Print").click()
    P("[data-f=problem]").fill("หมึกพิมพ์เลอะ ทดสอบ E2E")
    P("[data-f=filePick]").set_input_files(PNG_PATH)
    expect(P(".file-chip.new")).to_contain_text("รูปหน้างาน.png")
    pg.screenshot(path=f"{SHOTS}/01-entry-filled.png")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.ok").last).to_contain_text("บันทึกรายการแล้ว")  # ไม่มีค่าใหม่ → ไม่ถาม Master
    expect(pg.locator("#daySummary")).to_contain_text("4 รายการ")
    e2e = [e for e in api("/api/events?date=2026-10-13") if "ทดสอบ E2E" in e["problem"]][0]
    assert e2e["hours"] == 9 and len(e2e["attachments"]) == 1 and e2e["status"] is None

    # Stop Line: วันที่เริ่ม-สิ้นสุด + ชั่วโมง (ไม่มีเวลา/กะ/Size)
    P(".mode button[data-mode=stopline]").click()
    for f in ("timeFrom", "timeTo", "size"):
        expect(P(f"[data-f={f}]")).to_be_hidden()
    expect(P("[data-f=shift]")).to_be_hidden()
    expect(P("[data-f=machineLabel]")).to_have_text("เครื่องจักร (ถ้ามี)")
    expect(P("[data-f=startDate]")).to_have_value("2026-10-13")
    expect(P("[data-f=stopHours]")).to_have_value("24")
    P("[data-f=endDate]").fill("2026-10-15")
    expect(P("[data-f=stopHours]")).to_have_value("72")
    P("[data-f=stopHours]").fill("80")
    P("[data-f=problem]").fill("ไม่มี Order")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.err").last).to_contain_text("ไม่เกิน 72")
    P("[data-f=stopHours]").fill("50")
    pg.screenshot(path=f"{SHOTS}/02-stopline.png")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.ok").last).to_contain_text("บันทึกรายการแล้ว")
    stop = [e for e in api("/api/events?date=2026-10-13") if e["stop_line"]][0]
    assert stop["hours"] == 50 and stop["end_date"] == "2026-10-15" and stop["time_from"] is None and stop["shift"] is None
    expect(pg.locator("#daySummary")).to_contain_text("ไม่รวม Stop Line 1 รายการ")
    # วันที่สิ้นสุดก่อนวันที่เริ่ม → แจ้งเตือน
    P("[data-f=endDate]").fill("2026-10-12")
    P("[data-f=problem]").fill("x")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.err").last).to_contain_text("ไม่ก่อนวันที่เริ่ม")
    P("[data-f=cancel]").click()
    expect(P(".mode button.on")).to_have_attribute("data-mode", "machine")

    # กรอบการปรับปรุง: สถานะ 3 ค่า (ค่าเริ่มต้น รอดำเนินการ)
    expect(I("[data-f=status] option")).to_have_text(["รอดำเนินการ", "ระหว่างดำเนินการ", "เสร็จแล้ว"])
    expect(I("[data-f=status]")).to_have_value("pending")
    I("[data-f=timeFrom]").fill("9")
    I("[data-f=timeTo]").fill("10")
    expect(I("[data-f=shift]")).to_contain_text("เช้า")
    I("[data-f=machine]").fill("Inside")
    I("[data-f=problem]").fill("เปลี่ยน additive 0.5%")
    I("[data-f=dueDate]").fill("2026-10-01")
    I("[data-f=responsible]").fill("สมชาย")
    I("[data-f=save]").click()
    dlg = pg.locator("dialog.modal")
    expect(dlg.locator("input[type=checkbox]")).to_have_count(1)  # เฉพาะผู้รับผิดชอบใหม่
    dlg.locator("[data-act=ok]").click()
    expect(pg.locator("#daySummary")).to_contain_text("6 รายการ")
    imp = [e for e in api("/api/events?date=2026-10-13") if e["type"] == "improve"][0]
    assert imp["status"] == "pending" and imp["responsible"] == "สมชาย"

    # ช่องบังคับ
    I("[data-f=save]").click()
    expect(pg.locator(".toast.err").last).to_contain_text("กรุณากรอก")

    # ---------- หน้าต่าง ดู/แก้ไข ----------
    pg.click("#openDayList")
    day = pg.locator("dialog.modal.wide")
    expect(day.locator("tbody tr")).to_have_count(6)
    expect(day.locator("tbody tr").first).to_contain_text("13/10–15/10")  # Stop Line ขึ้นก่อน
    imp_row = day.locator("tbody tr", has_text="additive")
    expect(imp_row).to_contain_text("รอดำเนินการ")
    expect(imp_row).to_contain_text("เกินกำหนด")
    row = day.locator("tbody tr", has_text="ทดสอบ E2E")
    expect(row.locator("a.file-link")).to_have_attribute("href", f"/api/attachments/{e2e['attachments'][0]['id']}")
    pg.screenshot(path=f"{SHOTS}/03-day-list.png")
    row.locator("[data-act=edit]").click()
    expect(P("[data-f=editPill]")).to_be_visible()
    expect(P("[data-f=machine]")).to_have_value("Print")
    expect(P(".file-chip")).to_have_count(1)
    P(".file-chip button").click()
    expect(P(".file-chip.removed")).to_have_count(1)
    P("[data-f=timeFrom]").fill("7.00")
    P("[data-f=timeTo]").fill("8.00")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.ok").last).to_contain_text("แก้ไขรายการแล้ว")
    e2e = [e for e in api("/api/events?date=2026-10-13") if "ทดสอบ E2E" in e["problem"]][0]
    assert e2e["time_from"] == "07.00" and e2e["attachments"] == []
    # แก้ไข Stop Line: ชั่วโมงที่บันทึกไว้ต้องไม่ถูกคำนวณทับ
    pg.click("#openDayList")
    pg.locator("dialog.modal.wide tbody tr").first.locator("[data-act=edit]").click()
    expect(P("[data-f=stopHours]")).to_have_value("50")
    expect(P("[data-f=endDate]")).to_have_value("2026-10-15")
    P("[data-f=cancel]").click()

    # ลบผ่านหน้าต่าง
    pg.click("#openDayList")
    pg.locator("dialog.modal.wide tbody tr", has_text="ทดสอบ E2E").locator("[data-act=del]").click()
    pg.locator("dialog.modal:not(.wide) [data-act=ok]").click()
    expect(pg.locator("dialog.modal.wide tbody tr", has_text="ทดสอบ E2E")).to_have_count(0)
    pg.locator("dialog.modal.wide [data-act=close]").click()
    expect(pg.locator("#daySummary")).to_contain_text("5 รายการ")

    # เตือนข้อมูลที่ยังไม่บันทึก
    I("[data-f=problem]").fill("ยังไม่บันทึก")
    pg.click("#nextDay")
    expect(pg.locator("dialog.modal")).to_contain_text("ยังไม่ได้บันทึก")
    pg.locator("dialog.modal [data-act=cancel]").click()
    expect(pg.locator("#datePick")).to_have_value("2026-10-13")
    I("[data-f=cancel]").click()
    expect(I(".invalid")).to_have_count(0)
    assert pg.locator("#toasts .toast").count() <= 3
    pg.wait_for_timeout(300)  # รอ transition ของกรอบสีแดงจางหาย
    pg.screenshot(path=f"{SHOTS}/04-entry.png")

    # ---------- v1.5 E2: วันหยุด (หน้าบันทึกงาน) ----------
    def put_json(path, body):
        req = urllib.request.Request(B + path, data=json.dumps(body).encode(), method="PUT",
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))
    old_settings = api("/api/settings")
    put_json("/api/settings", {**old_settings, "default_target": 110000})
    pg.goto(B + "/?date=2026-10-11")
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("#target")).to_have_value("110,000")      # วันใหม่ = เติมเป้าหมายเริ่มต้น
    expect(pg.locator("#holiday")).not_to_be_checked()
    pg.check("#holiday")
    expect(pg.locator("#target")).to_have_value("")              # วันหยุด → ไม่เติมเป้าหมายเริ่มต้น
    expect(pg.locator("#dailyState")).to_contain_text("ยังไม่บันทึก")
    pg.uncheck("#holiday")
    expect(pg.locator("#target")).to_have_value("110,000")
    pg.check("#holiday")
    pg.click("#saveDaily")
    expect(pg.locator("#dailyState")).to_contain_text("บันทึกแล้ว")
    assert api("/api/daily/2026-10-11") == {"date": "2026-10-11", "target": None, "output": None, "diff": None,
                                           "saved": True, "holiday": True}
    pg.reload()
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("#holiday")).to_be_checked()
    expect(pg.locator("#target")).to_have_value("")
    # ค่าที่ผู้ใช้พิมพ์เองไม่ถูกล้างเมื่อติ๊กวันหยุด (วันหยุดทำ OT)
    pg.goto(B + "/?date=2026-10-18")
    pg.wait_for_load_state("networkidle")
    pg.fill("#target", "50000")
    pg.fill("#output", "52000")
    pg.check("#holiday")
    expect(pg.locator("#target")).to_have_value("50,000")
    pg.click("#saveDaily")
    expect(pg.locator("#dailyState")).to_contain_text("บันทึกแล้ว")
    assert api("/api/daily/2026-10-18")["holiday"] is True
    assert pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), "หน้าบันทึกงานต้องไม่ต้องเลื่อนจอ"
    pg.screenshot(path=f"{SHOTS}/04b-entry-holiday.png")
    put_json("/api/settings", old_settings)

    # ---------- v1.9 / v1.10: หัวเมนู + คิดชั่วโมงจากยอดผลิต (มีช่วงเวลา) (05/05/2025 แยกจากข้อมูล ต.ค.) ----------
    expect(pg.locator("header a.brand")).to_have_attribute("href", "/")
    assert pg.evaluate("getComputedStyle(document.querySelector('.brand .app-name')).fontWeight") == "400"
    pg.goto(B + "/?date=2025-05-05")
    pg.wait_for_load_state("networkidle")
    P("[data-mode=rate]").click()
    expect(P("[data-f=timeFrom]")).to_be_visible()                                 # v1.10 มีช่วงเวลา
    expect(P("[data-f=shiftSel]")).to_have_count(0)                                # กะคิดจากเวลาเริ่ม
    expect(P("[data-f=rateHint]")).to_contain_text("กรอกเวลาเริ่ม")
    P("[data-f=rateTarget]").fill("6000")
    P("[data-f=timeFrom]").fill("19")
    P("[data-f=timeTo]").fill("21")
    expect(P(".rate-item .rate-h")).to_have_text(["19.00", "20.00", "21.00"])     # ช่องขึ้นตามชั่วโมงจริง
    expect(P("[data-f=shift]")).to_contain_text("ดึก")
    P(".rate-item input").nth(0).fill("4500")
    P(".rate-item input").nth(1).fill("3000")
    P(".rate-item input").nth(2).fill("5400")
    expect(P("[data-f=hours]")).to_contain_text("0.85")
    expect(P("[data-f=hours]")).to_contain_text("51 นาที")
    # ย่อช่วงเวลาแล้วขยายกลับ → ค่าที่พิมพ์ไว้ไม่หาย
    P("[data-f=timeTo]").fill("19")
    expect(P(".rate-item input")).to_have_count(1)
    expect(P("[data-f=hours]")).to_contain_text("0.25")
    P("[data-f=timeTo]").fill("21")
    expect(P(".rate-item input")).to_have_count(3)
    expect(P(".rate-item input").nth(2)).to_have_value("5400")
    P("[data-f=machine]").fill("Latex")
    P("[data-f=problem]").fill("กาวไม่ออก งานออกไม่เต็ม ทดสอบ E2E")
    assert pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), "หน้าบันทึกงานต้องไม่ต้องเลื่อนจอ (โหมดยอดผลิต)"
    pg.screenshot(path=f"{SHOTS}/05-rate-time.png")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.ok").last).to_contain_text("บันทึกรายการแล้ว")
    # หลังบันทึก: ยังอยู่โหมดยอดผลิต, เป้าค้างไว้, เวลา/ผลิตได้จริงล้าง
    expect(P("[data-mode=rate]")).to_have_class("on")
    expect(P("[data-f=rateTarget]")).to_have_value("6,000")
    expect(P("[data-f=timeFrom]")).to_have_value("")
    expect(P(".rate-item input")).to_have_count(1)
    expect(P(".rate-item input")).to_have_value("")
    assert api("/api/settings")["rate_target"] == "6000"
    ev = api("/api/events?date=2025-05-05")[0]
    assert (ev["hours"], ev["shift"], ev["rate_actuals"], ev["time_from"], ev["time_to"]) == \
        (0.85, "N", [4500, 3000, 5400], "19.00", "21.00"), ev
    # ช่องเวลาใช้ร่วมกัน: สลับโหมดแล้วเวลาที่พิมพ์ไว้ไม่หาย
    P("[data-f=timeFrom]").fill("8")
    P("[data-mode=machine]").click()
    expect(P("[data-f=timeFrom]")).to_have_value("08.00")
    P("[data-f=cancel]").click()
    # เปิดหน้าใหม่ → เป้าค้างไว้
    pg.reload()
    pg.wait_for_load_state("networkidle")
    P("[data-mode=rate]").click()
    expect(P("[data-f=rateTarget]")).to_have_value("6,000")
    P("[data-f=cancel]").click()                                                   # ล้างฟอร์มก่อนเปิดรายการ (ไม่ให้ถามยืนยันทิ้งข้อมูล)
    # หน้าต่างรายการ: เวลา + ยอดผลิตแบบจาง, แก้ไขโหลดกลับครบ
    pg.click("#openDayList")
    dlg = pg.locator("dialog.modal.wide")
    expect(dlg.locator("tbody tr").first).to_contain_text("19.00–21.00")
    expect(dlg.locator(".rate-note")).to_have_text("ผลิต 4,500 · 3,000 · 5,400 / เป้า 6,000")
    dlg.locator("[data-act=edit]").first.click()
    expect(P(".rate-item input")).to_have_count(3)
    expect(P(".rate-item input").nth(1)).to_have_value("3,000")
    expect(P("[data-f=timeFrom]")).to_have_value("19.00")
    expect(P("[data-f=shift]")).to_contain_text("ดึก")
    expect(P("[data-f=hours]")).to_contain_text("0.85")
    P("[data-f=cancel]").click()
    # รายงาน: เวลาเริ่ม/สิ้นสุดตามจริง, ยอดผลิตจาง ๆ ใต้ปัญหา, ชั่วโมง = 0.85 (จากยอดผลิต)
    pg.goto(B + "/report?from=2025-05-05&to=2025-05-05&type=all")
    pg.wait_for_load_state("networkidle")
    row = pg.locator("table.report tbody tr", has_text="กาวไม่ออก")
    expect(row.locator("td.mark")).to_have_text("19.00")
    expect(row.locator("td.mark + td")).to_have_text("21.00")
    expect(row.locator("td.mark + td + td")).to_have_text("0.85")
    expect(row.locator("td.txt .rate-note")).to_have_text("ผลิต 4,500 · 3,000 · 5,400 / เป้า 6,000")
    expect(pg.locator("table.report td.rate-cell")).to_have_count(0)
    assert pg.evaluate("getComputedStyle(document.querySelector('.rate-note')).fontWeight") == "400"
    pg.screenshot(path=f"{SHOTS}/05b-report-rate-time.png")

    # ---------- v1.10: Monday Cleaning (12/05/2025 วันจันทร์) ----------
    pg.goto(B + "/?date=2025-05-12")
    pg.wait_for_load_state("networkidle")
    P("[data-mode=cleaning]").click()
    expect(P("[data-f=size]")).to_be_hidden()
    expect(P("[data-f=machineLabel]")).to_have_text("เครื่องจักร (ถ้ามี)")
    expect(P("[data-f=hoursLabel]")).to_have_text("ชั่วโมง (ไม่นับ)")
    expect(P("[data-f=problemLabel]")).to_have_text("รายละเอียด")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.err").last).to_contain_text("เวลาเริ่ม")
    P("[data-f=timeFrom]").fill("7")
    P("[data-f=timeTo]").fill("10")
    expect(P("[data-f=hours]")).to_contain_text("4")
    expect(P("[data-f=shift]")).to_contain_text("เช้า")
    assert pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), "หน้าบันทึกงานต้องไม่ต้องเลื่อนจอ (Monday Cleaning)"
    pg.screenshot(path=f"{SHOTS}/06-cleaning.png")
    P("[data-f=save]").click()                                                     # เครื่องจักร / รายละเอียด ไม่บังคับ
    expect(pg.locator(".toast.ok").last).to_contain_text("บันทึกรายการแล้ว")
    expect(P("[data-mode=cleaning]")).to_have_class("on")
    expect(pg.locator("#daySummary")).to_contain_text("1 รายการ · 0 ชม.")
    expect(pg.locator("#daySummary .note")).to_have_text("ไม่รวม Monday Cleaning 1 รายการ")
    cl = api("/api/events?date=2025-05-12")[0]
    assert (cl["cleaning"], cl["hours"], cl["problem"], cl["machine"]) == (True, 4, "Monday Cleaning", ""), cl
    P("[data-mode=machine]").click()
    P("[data-f=timeFrom]").fill("11")
    P("[data-f=timeTo]").fill("11")
    P("[data-f=machine]").fill("Press")
    P("[data-f=problem]").fill("หลอดติด ทดสอบย้ายวัน")
    P("[data-f=save]").click()
    expect(pg.locator("#daySummary")).to_contain_text("2 รายการ · 1 ชม.")
    expect(pg.locator("#daySummary .note")).to_have_text("ไม่รวม Monday Cleaning 1 รายการ")
    expect(pg.locator("#moveDay")).to_be_visible()
    assert pg.evaluate("document.querySelector('.daybar').offsetHeight") < 80, "แถบวันที่ต้องอยู่บรรทัดเดียว (มีปุ่มย้ายวัน)"
    # รายงาน: ป้าย Monday Cleaning + ชั่วโมงจาง + สรุปแยก, ชั่วโมงรวมไม่นับ
    pg.goto(B + "/report?from=2025-05-12&to=2025-05-12&type=all")
    pg.wait_for_load_state("networkidle")
    crow = pg.locator("table.report tbody tr.type-cleaning")
    expect(crow.locator(".pill.cleaning")).to_have_text("Monday Cleaning")
    expect(crow.locator("td.not-counted")).to_have_text("4")
    expect(pg.locator(".report-summary")).to_contain_text("Monday Cleaning: 1 ครั้ง · 4 ชม.")
    expect(pg.locator(".report-summary")).to_contain_text("ชั่วโมงรวม (ไม่รวม Stop Line / Monday Cleaning): 1 ชม.")
    expect(pg.locator(".legend .l-cleaning")).to_be_visible()
    pg.select_option("#fType", "cleaning")
    expect(pg.locator("table.report tbody tr.type-cleaning")).to_have_count(1)
    expect(pg.locator("table.report tbody tr.type-problem")).to_have_count(0)
    pg.select_option("#fType", "problem")
    expect(pg.locator("table.report tbody tr.type-cleaning")).to_have_count(0)
    pg.select_option("#fType", "all")
    expect(crow).to_have_count(1)
    pg.screenshot(path=f"{SHOTS}/06b-report-cleaning.png")
    # Dashboard: ไม่ลงกราฟ / ชั่วโมงสูญเสีย, แสดงจำนวนในกล่อง "ปัญหา / การปรับปรุง"
    d = api("/api/dashboard?from=2025-05-12&to=2025-05-12&type=all")
    assert (d["kpis"]["loss_hours"], d["kpis"]["cleaning_count"]) == (1, 1), d["kpis"]
    pg.goto(B + "/dashboard")
    pg.wait_for_load_state("networkidle")
    pg.fill("#fFrom", "2025-05-12")
    pg.fill("#fTo", "2025-05-12")
    pg.locator("#fTo").dispatch_event("change")
    expect(pg.locator(".kpi", has_text="ปัญหา / การปรับปรุง")).to_contain_text("Cleaning 1")
    expect(pg.locator(".kpi", has_text="ชั่วโมงสูญเสียรวม")).to_contain_text("1")
    pg.screenshot(path=f"{SHOTS}/06c-dashboard-cleaning.png")

    # ---------- v1.10.1: มีตัวกรอง → พิมพ์เฉพาะวันที่มีรายการตรงตัวกรอง ----------
    pg.goto(B + "/report?from=2025-05-05&to=2025-05-15&type=cleaning")
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("table.report tbody tr.no-events").first).to_be_visible()    # บนจอเห็นครบทุกวัน
    pg.emulate_media(media="print")
    expect(pg.locator("table.report tbody tr.no-events").first).to_be_hidden()      # ตอนพิมพ์ซ่อนวันว่าง
    expect(pg.locator("table.report tbody tr.type-cleaning")).to_be_visible()
    expect(pg.locator(".missing-note")).to_be_hidden()
    # v1.10.2 เลือกประเภท → ตอนพิมพ์ไม่มีคอลัมน์ยอดผลิต / แถวสรุปยอดผลิต; บนจอยังเห็น
    expect(pg.locator("table.report th", has_text="เป้าหมาย")).to_be_hidden()
    expect(pg.locator("table.report th", has_text="ผลต่าง")).to_be_hidden()
    expect(pg.locator("table.report tr.complete-row")).to_be_hidden()
    expect(pg.locator("table.report th", has_text="เวลาเริ่ม")).to_be_visible()
    expect(pg.locator("table.report th", has_text="วันที่")).to_be_visible()
    pg.emulate_media(media="screen")
    expect(pg.locator("table.report th", has_text="เป้าหมาย")).to_be_visible()
    expect(pg.locator("table.report tr.complete-row")).to_be_visible()
    pg.goto(B + "/report?from=2025-05-05&to=2025-05-15&type=all")                   # ไม่มีตัวกรอง → พิมพ์ครบเหมือนเดิม
    pg.wait_for_load_state("networkidle")
    pg.emulate_media(media="print")
    expect(pg.locator("table.report tbody tr.no-events").first).to_be_visible()
    expect(pg.locator("table.report th", has_text="เป้าหมาย")).to_be_visible()     # ทั้งหมด → พิมพ์ยอดผลิตเหมือนเดิม
    pg.emulate_media(media="screen")

    # ---------- v1.10: แก้วันที่ของรายการ (เดิมเปลี่ยนวันที่ด้านบนแล้วฟอร์มถูกล้าง) ----------
    pg.goto(B + "/?date=2025-05-12")
    pg.wait_for_load_state("networkidle")
    expect(P("[data-f=evDateBox]")).to_be_hidden()                                # บันทึกใหม่: ไม่มีช่องวันที่ในกรอบ
    pg.click("#openDayList")
    pg.locator("dialog.modal.wide tbody tr", has_text="ทดสอบย้ายวัน").locator("[data-act=edit]").click()
    expect(P("[data-f=evDateBox]")).to_be_visible()
    expect(P("[data-f=evDate]")).to_have_value("2025-05-12")
    P("[data-f=corrective]").fill("แก้ไขก่อนย้ายวัน")                              # แก้ไว้แล้วยังไม่บันทึก
    assert pg.evaluate("document.documentElement.scrollHeight <= innerHeight + 1"), "หน้าบันทึกงานต้องไม่ต้องเลื่อนจอ (กำลังแก้ไข)"
    pg.click("#nextDay")
    choice = pg.locator("dialog.modal", has_text="กำลังแก้ไขรายการอยู่")
    expect(choice).to_contain_text("ย้ายรายการนี้ไปวันที่ 13/05/2025")
    pg.screenshot(path=f"{SHOTS}/07-edit-move-dialog.png")
    choice.locator("button", has_text="ย้ายไปวันที่ 13/05/2025").click()
    expect(pg.locator("#datePick")).to_have_value("2025-05-13")
    expect(P("[data-f=editPill]")).to_be_visible()                                # ยังแก้ไขอยู่ ข้อมูลไม่หาย
    expect(P("[data-f=evDate]")).to_have_value("2025-05-13")
    expect(P("[data-f=corrective]")).to_have_value("แก้ไขก่อนย้ายวัน")
    expect(P("[data-f=machine]")).to_have_value("Press")
    P("[data-f=save]").click()
    expect(pg.locator(".toast.ok").last).to_contain_text("แก้ไขรายการแล้ว")
    moved = [e for e in api("/api/events?date=2025-05-13") if "ทดสอบย้ายวัน" in e["problem"]]
    assert len(moved) == 1 and moved[0]["corrective"] == "แก้ไขก่อนย้ายวัน", moved
    assert [e["problem"] for e in api("/api/events?date=2025-05-12")] == ["Monday Cleaning"]  # ไม่มีรายการซ้ำ
    expect(pg.locator("#daySummary")).to_contain_text("1 รายการ")
    # ทิ้งการแก้ไข
    pg.click("#openDayList")
    pg.locator("dialog.modal.wide [data-act=edit]").first.click()
    pg.click("#prevDay")
    pg.locator("dialog.modal", has_text="กำลังแก้ไขรายการอยู่").locator("button", has_text="ทิ้งการแก้ไข").click()
    expect(pg.locator("#datePick")).to_have_value("2025-05-12")
    expect(P("[data-f=editPill]")).to_be_hidden()
    # ยกเลิก → อยู่วันเดิม ยังแก้ไขอยู่
    pg.click("#openDayList")
    pg.locator("dialog.modal.wide [data-act=edit]").first.click()
    pg.click("#nextDay")
    pg.locator("dialog.modal", has_text="กำลังแก้ไขรายการอยู่").locator("button", has_text="ยกเลิก").click()
    expect(pg.locator("#datePick")).to_have_value("2025-05-12")
    expect(P("[data-f=editPill]")).to_be_visible()
    P("[data-f=cancel]").click()
    # แก้วันที่ในกรอบโดยตรง → ปุ่ม "ไปที่วันที่ …" ในข้อความ
    pg.goto(B + "/?date=2025-05-13")
    pg.wait_for_load_state("networkidle")
    pg.click("#openDayList")
    pg.locator("dialog.modal.wide [data-act=edit]").first.click()
    P("[data-f=evDate]").fill("2025-05-14")
    P("[data-f=save]").click()
    t = pg.locator(".toast.ok", has_text="บันทึกไว้ที่วันที่ 14/05/2025")
    expect(t).to_be_visible()
    t.locator(".toast-act").click()
    expect(pg.locator("#datePick")).to_have_value("2025-05-14")
    expect(pg.locator("#daySummary")).to_contain_text("1 รายการ")

    # ---------- v1.10: ย้ายยอดผลิตที่กรอกผิดวัน ----------
    expect(pg.locator("#moveDay")).to_be_visible()                                 # มีรายการ → ย้ายได้
    pg.fill("#target", "7000")
    pg.fill("#output", "6500")
    pg.click("#saveDaily")
    expect(pg.locator("#dailyState")).to_contain_text("บันทึกแล้ว")
    pg.click("#moveDay")
    mv = pg.locator("dialog.modal", has_text="ย้ายข้อมูลของวันที่ 14/05/2025")
    expect(mv).to_contain_text("เป้าหมาย 7,000")
    expect(mv.locator("[data-f=withEvents]")).to_be_checked()
    mv.locator("[data-f=to]").fill("2025-05-15")
    pg.screenshot(path=f"{SHOTS}/08-move-day.png")
    mv.locator("[data-act=ok]").click()
    expect(pg.locator("#datePick")).to_have_value("2025-05-15")
    expect(pg.locator("#target")).to_have_value("7,000")
    expect(pg.locator("#daySummary")).to_contain_text("1 รายการ")
    expect(pg.locator(".toast.ok").last).to_contain_text("ย้ายยอดผลิต + 1 รายการไปวันที่ 15/05/2025")
    assert api("/api/daily/2025-05-14")["saved"] is False and api("/api/events?date=2025-05-14") == []
    # ปลายทางมียอดผลิตแล้ว → ไม่เขียนทับ
    put_json("/api/daily/2025-05-16", {"target": 1, "output": 1})
    pg.click("#moveDay")
    mv = pg.locator("dialog.modal", has_text="ย้ายข้อมูลของวันที่ 15/05/2025")
    mv.locator("[data-f=to]").fill("2025-05-16")
    mv.locator("[data-act=ok]").click()
    expect(pg.locator(".toast.err").last).to_contain_text("ไม่เขียนทับ")
    expect(pg.locator("#datePick")).to_have_value("2025-05-15")
    assert api("/api/daily/2025-05-16")["target"] == 1
    # 409 ที่ตั้งใจทดสอบ (Browser บันทึกเป็น Console Error ของการโหลด) — ไม่นับเป็นข้อผิดพลาด
    errors[:] = [e for e in errors if "status of 409" not in e]

    # ---------- รายงาน: ตัวกรอง 5 แบบ ----------
    def report(t):
        pg.goto(B + f"/report?from=2026-10-01&to=2026-10-31&type={t}")
        pg.wait_for_load_state("networkidle")
        heads = pg.locator("table.report thead th").all_inner_texts()
        kinds = {k: pg.locator(f"table.report tbody tr.type-{k}").count() for k in ("problem", "improve", "stopline")}
        return heads, kinds
    heads, kinds = report("problem")
    assert "ผู้รับผิดชอบ" not in heads and "สถานะ" not in heads and kinds["stopline"] == 0 and kinds["improve"] == 0
    heads, kinds = report("problem_sl")
    assert "กำหนดเสร็จ" not in heads and kinds["stopline"] == 2 and kinds["problem"] > 0 and kinds["improve"] == 0
    expect(pg.locator("table.report tr.type-stopline", has_text="ไม่มี Order").first).to_be_visible()
    pg.screenshot(path=f"{SHOTS}/05a-report-problem.png", full_page=True)
    heads, kinds = report("improve")
    assert heads[-3:] == ["กำหนดเสร็จ", "ผู้รับผิดชอบ", "สถานะ"] and "งานที่ปรับปรุง" in heads
    assert kinds == {"problem": 0, "improve": 4, "stopline": 0}
    expect(pg.locator("table.report")).to_contain_text("ระหว่างดำเนินการ")
    heads, kinds = report("stopline")
    assert kinds == {"problem": 0, "improve": 0, "stopline": 2}
    expect(pg.locator("table.report tr.type-stopline", has_text="13/10–15/10")).to_have_count(1)
    heads, kinds = report("all")
    # v1.5: ป้ายสถานะต้องไม่ล้นขอบเซลล์ (บนจอและตอนพิมพ์)
    pill_overflow = """[...document.querySelectorAll('table.report td.due .pill')].filter(p => {
        const c = p.closest('td').getBoundingClientRect(), r = p.getBoundingClientRect();
        return r.right > c.right + 0.5 || r.left < c.left - 0.5; }).map(p => p.textContent)"""
    assert pg.locator("table.report td.due .pill").count() > 0
    assert pg.evaluate(pill_overflow) == [], pg.evaluate(pill_overflow)
    pg.emulate_media(media="print")
    pg.set_viewport_size({"width": 1123, "height": 794})          # A4 แนวนอน
    assert pg.evaluate(pill_overflow) == [], pg.evaluate(pill_overflow)
    pg.emulate_media(media="screen")
    pg.set_viewport_size({"width": 1920, "height": 1080 - 130})
    assert "สถานะ" in heads and all(kinds.values())
    expect(pg.locator(".report-summary")).to_contain_text("ไม่รวมในชั่วโมงรวม")
    # v1.5 E1: แถวรวมเฉพาะวันที่มีครบ = ตัวเลขเดียวกับ Dashboard (19/10 มีเป้าแต่ยังไม่มียอดผลิต)
    foot = pg.locator("table.report tfoot tr")
    expect(foot).to_have_count(2)
    # (รวม 18/10 วันหยุดที่ทำ OT 50,000 / 52,000 — วันหยุดที่กรอกครบยังนับตามปกติ)
    expect(foot.nth(0)).to_contain_text("1,540,000")
    expect(foot.nth(1)).to_contain_text("เฉพาะ 13 วันที่มีครบ")
    expect(foot.nth(1)).to_contain_text("1,430,000")
    expect(foot.nth(1)).to_contain_text("1,356,212")
    expect(foot.nth(1)).to_contain_text("บรรลุเป้า 94.8%")
    # v1.5 E2: ทุกวันในช่วง, วันหยุด = เทา, ขาดข้อมูล = "—" เหลือง (ไม่นับวันในอนาคต)
    rep = api("/api/report?from=2026-10-01&to=2026-10-31")
    assert len(rep["days"]) == 31
    def day_row(dmy):
        return pg.locator("table.report tbody tr", has=pg.locator("td.day-cell", has_text=dmy)).first
    expect(day_row("11/10/2026").locator("td.holiday-cell")).to_have_count(2)
    expect(day_row("18/10/2026").locator(".pill.holiday")).to_have_count(1)        # วันหยุดที่มีตัวเลข
    expect(day_row("18/10/2026")).to_contain_text("52,000")
    expect(day_row("01/10/2026").locator("td.missing-cell")).to_have_count(2)
    expect(day_row("19/10/2026").locator("td.missing-cell")).to_have_count(1)       # มีเป้า ไม่มียอดผลิต
    expect(day_row("19/10/2026").locator("td.missing-cell")).to_have_attribute("title", "ยังไม่บันทึกยอดผลิต")
    expect(pg.locator(".report-summary")).to_contain_text(f"ยังไม่บันทึกเป้าหมาย/ยอดผลิต: {rep['totals']['missing_days']} วัน")
    expect(pg.locator(".report-summary")).to_contain_text("วันหยุด: 2 วัน")
    future = [d for d in rep["days"] if d["date"] > date.today().isoformat()]  # v1.10: เดิมฝังวันที่ 23/10/2026 ไว้
    assert all(not d["missing"] for d in future)  # ถ้ารันหลังสิ้นเดือน ช่วงนี้ไม่มีวันอนาคต → ว่างเปล่าก็ผ่าน
    pg.screenshot(path=f"{SHOTS}/05-report.png", full_page=True)

    # v1.5 B: Export Excel ของรายงานที่แสดงอยู่ (ประเภท "ทั้งหมด")
    shown_rows = pg.locator("table.report tbody tr[class^=type-]").count()
    pg.select_option("#fType", "improve")          # เปลี่ยนตัวกรองแล้วรายงานแสดงใหม่ → Excel ตามที่แสดง
    expect(pg.locator("table.report thead")).to_contain_text("งานที่ปรับปรุง")
    improve_rows = pg.locator("table.report tbody tr[class^=type-]").count()
    with pg.expect_download() as dl:
        pg.click("#xlsxBtn")
    xlsx_path = os.path.join(OUT, dl.value.suggested_filename)
    dl.value.save_as(xlsx_path)
    assert dl.value.suggested_filename == "T14_รายงาน_2026-10-01_ถึง_2026-10-31.xlsx", dl.value.suggested_filename
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path)
    assert wb.sheetnames == ["รายการ", "ยอดผลิตรายวัน", "สรุป"]
    assert wb["รายการ"].max_row - 1 == improve_rows < shown_rows, (wb["รายการ"].max_row, improve_rows, shown_rows)
    # v1.10 เพิ่มคอลัมน์ Monday Cleaning (F) → คอลัมน์ถัดไปเลื่อน 1 ช่อง
    assert wb["รายการ"]["F1"].value == "Monday Cleaning"
    assert wb["รายการ"]["I1"].value == "ยอดผลิต/ชม. (เป้า)" and wb["รายการ"]["N1"].value == "งานที่ปรับปรุง"
    notes = {r[0].strftime("%d"): r[5] for r in wb["ยอดผลิตรายวัน"].iter_rows(min_row=2, max_row=32, values_only=True)}
    assert notes["11"] == "วันหยุด" and notes["19"] == "ยังไม่บันทึกยอดผลิต" and notes["06"] is None, notes

    # ---------- Dashboard ----------
    pg.set_viewport_size({"width": 1920, "height": 1080})
    pg.goto(B + "/dashboard?preset=custom&from=2026-10-01&to=2026-10-31&type=problem")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(600)
    expect(pg.locator(".kpi")).to_have_count(10)
    # ลำดับกล่องใหม่ + สีแถบตามผล (เขียว = ดี, ส้ม = ไม่ดี)
    kpi_labels = pg.locator(".kpi .k-label").all_inner_texts()
    assert kpi_labels == ["เป้าหมายรวม", "ผลิตได้รวม", "ผลต่างรวม", "% บรรลุเป้า", "ยอดผลิตเฉลี่ย / วัน",
                          "ชั่วโมงสูญเสียรวม", "เครื่องจักรที่ใช้เวลามากที่สุด", "ปัญหา / การปรับปรุง",
                          "งานที่ปรับปรุงแล้วเสร็จ", "งานปรับปรุงที่ยังไม่เสร็จ"], kpi_labels
    def tone(label):
        return pg.locator(".kpi", has=pg.locator(".k-label", has_text=label)).first.get_attribute("class")
    assert "accent" in tone("เป้าหมายรวม")
    assert "bad" in tone("ผลิตได้รวม") and "bad" in tone("ผลต่างรวม") and "bad" in tone("% บรรลุเป้า")
    assert "good" in tone("งานที่ปรับปรุงแล้วเสร็จ") and "bad" in tone("งานปรับปรุงที่ยังไม่เสร็จ")
    border = pg.evaluate("getComputedStyle(document.querySelector('.kpi.bad')).borderLeftColor")
    assert border == "rgb(224, 112, 13)", border  # ส้ม
    # เปรียบเทียบ: ค่าเริ่มต้น = ช่วงก่อนหน้า
    expect(pg.locator("#dashPeriod")).to_contain_text("เทียบกับช่วงก่อนหน้า (31/08/2026 – 30/09/2026)")
    expect(pg.locator(".kpi .k-cmp")).to_have_count(10)
    # v1.5 A: ช่วงก่อนหน้า (ก.ย.) ไม่มีข้อมูลเลย → ทุกกล่อง "ไม่มีข้อมูล" (ไม่เทียบกับ 0) และไม่มี ▲▼
    cmp_texts = pg.locator(".kpi .k-cmp").all_inner_texts()
    assert all("ไม่มีข้อมูล" in t and "▲" not in t and "▼" not in t for t in cmp_texts), cmp_texts
    # v1.5 E2-5: ข้อความย่อยกล่องเป้าหมาย
    dk = api("/api/dashboard?from=2026-10-01&to=2026-10-31&type=problem")["kpis"]
    expect(pg.locator(".kpi", has=pg.locator(".k-label", has_text="เป้าหมายรวม")).locator(".k-sub")).to_have_text(
        f"คิดจาก {dk['days_complete']} วัน · วันหยุด 2 วัน · ขาดข้อมูล {dk['missing_days']} วัน")
    # กล่องที่สีขึ้นกับการเปรียบเทียบ → สีกลาง
    for label in ("ชั่วโมงสูญเสียรวม", "ปัญหา / การปรับปรุง"):
        assert "good" not in tone(label) and "bad" not in tone(label), (label, tone(label))
    # ---------- v1.8: กราฟแท่งตั้ง ----------
    def kpi(label):
        return pg.locator(".kpi", has=pg.locator(".k-label", has_text=label)).first
    def chart_info(canvas):
        return pg.evaluate(f"""(() => {{ const c = Chart.getChart('{canvas}');
            return {{ labels: c.data.labels, types: c.data.datasets.map(d => d.$type || null), tops: c.data.datasets.map(d => d.$tops),
                      data: c.data.datasets.map(d => d.data), colors: c.data.datasets.map(d => d.backgroundColor),
                      vertical: c.options.indexAxis !== 'y', legend: c.options.plugins.legend.display }}; }})()""")
    # ทุกกราฟ: ชื่อใต้แท่งครบ (ไม่ถูกซ่อน), ป้ายบนแท่งไม่ล้นขอบบน/ไม่ทับแท่งข้าง ๆ
    labels_ok = """Object.entries(charts).flatMap(([k, c]) => { const out = [];
        if (c.scales.x.ticks.length !== c.data.labels.length) out.push(k + ': x labels skipped');
        if ((c.$overflow || []).length) out.push(k + ': overflow ' + c.$overflow.join(','));
        c.data.datasets.forEach((d, di) => c.getDatasetMeta(di).data.forEach((b, i) => {
          if (d.$tops?.[i] && b.y - 3 - 2 * (c.$compact ? 10.5 : 12) < -0.5) out.push(k + ': top clipped ' + i); }));
        return out; })"""
    expect(pg.locator("#pctTog button.on")).to_have_text("เปิด")
    m = chart_info("cMachine")
    assert m["vertical"] and m["types"] == ["problem"] and m["legend"] is False, m
    assert set(m["colors"][0]) == {"#e6774f"}, m["colors"]                          # กราฟเครื่องจักร: สีเดียว (ไม่ไล่โทน)
    # v1.9: ทุกเครื่องตามลำดับจริง (แม้ไม่มีข้อมูล) + ชื่อเดิมที่มีข้อมูลต่อท้าย
    REAL = ["Press", "Trim", "Aneal", "Inside", "IBO", "Base", "DO-BC", "Print", "DO-PT", "Cap", "Latex", "Accu.", "Pack"]
    assert m["labels"][:13] == REAL, m["labels"]
    assert "Stop Line" not in m["labels"] and ["MONDAY", "Cleaning"] in m["labels"][13:], m["labels"]
    expect(pg.locator('[data-chart="machine"] [data-sort] button.on')).to_have_text("ตามเครื่อง")
    assert m["tops"][0][0] == ["19 (6)", "32%"], m["tops"]                          # ตัวหาร = 59 ชม.
    assert m["tops"][0][1] == ["0", "", True], m["tops"]                            # Trim ไม่มีข้อมูล → "0" สีเทา
    assert all(str(l).startswith("⌀") for l in chart_info("cSize")["labels"])
    sh = chart_info("cShift")                                                       # กะ = เฉพาะปัญหา
    assert sh["types"] == ["problem"] and sh["labels"] == ["ดึก", "เช้า"], sh
    assert sh["tops"][0] == [["32 (9)", "54%"], ["27 (7)", "46%"]], sh["tops"]
    assert sh["colors"] == [["#e6774f", "#f3bba7"]], sh["colors"]                  # ดึก = เข้ม, เช้า = อ่อน (โทนเดียวกัน)
    sz = chart_info("cSize")
    assert sz["colors"][0][0] == "#e6774f" and sz["colors"][0][1] != "#e6774f", sz["colors"]   # Size ไล่โทน
    imp = chart_info("cImprove")                                                    # เสร็จ = เขียว, ไม่เสร็จ = ส้มไล่โทน
    assert imp["labels"] == ["เสร็จแล้ว", "รอดำเนินการ", ["ระหว่าง", "ดำเนินการ"], "เกินกำหนด"], imp
    assert imp["data"] == [[1, 0, 0, 3]] and imp["colors"] == [["#3f9d64", "#f7c48e", "#ef9a4f", "#d2661c"]], imp
    assert [t[1] for t in imp["tops"][0]] == ["25%", "0%", "0%", "75%"], imp["tops"]        # รวม 4 แท่ง = 100%
    expect(pg.locator('[data-chart="improve"] [data-note]')).to_contain_text("งานปรับปรุงทั้งหมด 4 งาน (รวม 4 แท่ง = 100%)")
    pg.wait_for_timeout(400)
    assert pg.evaluate(labels_ok) == [], pg.evaluate(labels_ok)
    # กล่องตัวเลข (v1.6) ไม่เปลี่ยน
    expect(kpi("ผลต่างรวม").locator(".k-sub")).to_contain_text("−5.2% ของเป้า")
    expect(kpi("เครื่องจักรที่ใช้เวลามากที่สุด").locator(".k-sub")).to_contain_text("19 ชม. (6 ครั้ง) · 32% ของทั้งหมด")
    # v1.8.1: กล่องงานปรับปรุงสอดคล้องกับกราฟ — % ของงานปรับปรุงทั้งหมด, รอ/ระหว่าง = ยังไม่เกินกำหนด
    expect(kpi("งานปรับปรุงที่ยังไม่เสร็จ").locator(".k-value")).to_contain_text("(75% / 75%)")
    expect(kpi("งานปรับปรุงที่ยังไม่เสร็จ").locator(".k-sub")).to_have_text("ยังไม่เสร็จ / เกินกำหนด · รอ 0 · ระหว่าง 0")
    expect(kpi("งานที่ปรับปรุงแล้วเสร็จ").locator(".k-sub")).to_have_text("จาก 4 งาน (25%)")
    # % หลายกลุ่มรวม 100% พอดี (ปัดเศษหลายกลุ่ม)
    assert pg.evaluate("pctSplit([1, 1, 1], 3)") == [34, 33, 33]
    assert pg.evaluate("pctSplit([1, 1, 1, 0], 3)") == [34, 33, 33, 0]
    assert pg.evaluate("pctSplit([1, 1, 1, 1, 1, 1, 1], 7)") == [15, 15, 14, 14, 14, 14, 14]
    assert all(sum(pg.evaluate(f"pctSplit({v}, {sum(v)})")) == 100 for v in ([1, 2, 3, 1], [5, 3, 3, 0], [2, 2, 2, 1], [1, 6]))
    # % ตามปุ่มเรียง (ครั้ง → Press 6/16 = 38%); ไม่มีปุ่ม Top N แล้ว
    card = pg.locator('[data-chart="machine"]')
    expect(card.locator("[data-top]")).to_have_count(0)
    expect(card.locator("[data-sort] button")).to_have_text(["ตามเครื่อง", "ชม.", "ครั้ง"])
    card.locator("[data-sort] button[data-v=count]").click()
    assert chart_info("cMachine")["tops"][0][0] == ["19 (6)", "38%"]
    card.locator("[data-sort] button[data-v=machine]").click()
    # แกนตั้งไม่เกิน 4 เส้น
    assert all(n <= 4 for n in pg.evaluate("Object.values(charts).map(c => c.scales.y.ticks.length)"))

    # v1.9: คลิกกล่องตัวเลข → ข้อมูลเบื้องหลัง (จำนวนรายการเท่ากับตัวเลขในกล่อง)
    def kpi_list(label):
        kpi(label).click()
        d = pg.locator("dialog.modal.wide")
        expect(d).to_have_count(1)
        n = d.locator("tbody tr:not(:has(.empty-state))").count()
        d.locator("[data-act=close]").click()
        return n
    dk = api("/api/dashboard?from=2026-10-01&to=2026-10-31&type=problem")["kpis"]
    assert kpi_list("ชั่วโมงสูญเสียรวม") == dk["loss_count"]
    assert kpi_list("เครื่องจักรที่ใช้เวลามากที่สุด") == dk["top_machine"]["count"]
    assert kpi_list("ปัญหา / การปรับปรุง") == sum(dk["by_type"].values())
    assert kpi_list("งานที่ปรับปรุงแล้วเสร็จ") == dk["done_count"]
    assert kpi_list("งานปรับปรุงที่ยังไม่เสร็จ") == dk["open_count"]
    assert pg.evaluate("getComputedStyle(document.querySelector('.kpi.link')).cursor") == "pointer"
    kpi("เป้าหมายรวม").click()                                                         # กล่องยอดผลิต → หน้ารายงาน
    pg.wait_for_url("**/report?**")
    assert "from=2026-10-01" in pg.url and "to=2026-10-31" in pg.url
    pg.go_back()
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(600)

    # คลิกแท่ง (แท่งตั้ง) → หน้าต่างรายการ: จำนวน + % เดียวกับแท่ง
    def click_bar(canvas_id, index, dataset=0):
        pg.locator(f"#{canvas_id}").scroll_into_view_if_needed()   # แถวล่างอาจอยู่นอกจอ
        pg.wait_for_timeout(100)
        box = pg.locator(f"#{canvas_id}").bounding_box()
        x, y = pg.evaluate(f"(() => {{ const b = Chart.getChart('{canvas_id}').getDatasetMeta({dataset}).data[{index}]; "
                           f"return [b.x, (b.y + b.base) / 2]; }})()")
        pg.mouse.click(box["x"] + x, box["y"] + y)
        return pg.locator("dialog.modal.wide")
    pg.wait_for_timeout(400)
    bar0 = pg.evaluate("lastData.charts.machine[0]")
    drill = click_bar("cMachine", 0)
    expect(drill.locator(".modal-head")).to_contain_text(f"เครื่องจักร: {bar0['label']}")
    expect(drill.locator(".modal-head")).to_contain_text("6 รายการ · 19 ชม. · 32% ของปัญหาทั้งหมด")
    expect(drill.locator("tbody tr")).to_have_count(bar0["count"])
    pg.screenshot(path=f"{SHOTS}/07-drilldown.png")
    drill.locator("[data-act=close]").click()
    expect(pg.locator("dialog.modal.wide")).to_have_count(0)
    drill = click_bar("cShift", 1)                                                  # เช้า
    expect(drill.locator("tbody tr")).to_have_count(7)
    expect(drill.locator("tbody .pill.improve")).to_have_count(0)
    drill.locator("[data-act=close]").click()
    drill = click_bar("cImprove", 3)                                                # เกินกำหนด
    expect(drill.locator(".modal-head")).to_contain_text("งานปรับปรุง: เกินกำหนด")
    expect(drill.locator(".modal-head")).to_contain_text("3 งาน · 75% ของงานปรับปรุงทั้งหมด")
    expect(drill.locator("tbody tr")).to_have_count(3)
    expect(drill.locator("tbody .pill.overdue")).to_have_count(3)
    drill.locator("[data-act=close]").click()
    drill = click_bar("cImprove", 0)                                                # เสร็จแล้ว
    expect(drill.locator("tbody tr")).to_have_count(1)
    expect(drill.locator("tbody .pill.done")).to_have_count(1)
    drill.locator("[data-act=close]").click()

    # ปิด % → ไม่มี % บนแท่ง/กล่อง/หน้าต่าง และจำค่าหลัง reload
    pg.locator("#pctTog button[data-v=off]").click()
    all_tops = [t for cid in ("cMachine", "cSize", "cShift", "cImprove") for ds in chart_info(cid)["tops"] for t in ds if t]
    assert all(t[1] == "" for t in all_tops), all_tops
    expect(kpi("ผลต่างรวม").locator(".k-sub")).to_have_text("ผลิตได้ − เป้าหมาย")
    expect(kpi("งานปรับปรุงที่ยังไม่เสร็จ").locator(".k-value")).not_to_contain_text("%")
    pg.wait_for_timeout(400)
    drill = click_bar("cMachine", 0)
    expect(drill.locator(".modal-head")).not_to_contain_text("%")
    drill.locator("[data-act=close]").click()
    pg.reload()
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(600)
    expect(pg.locator("#pctTog button.on")).to_have_text("ปิด")
    assert chart_info("cMachine")["tops"][0][0] == ["19 (6)", ""]
    pg.locator("#pctTog button[data-v=on]").click()
    assert chart_info("cMachine")["tops"][0][0] == ["19 (6)", "32%"]

    # เปรียบเทียบกับช่วงที่เลือกเอง / ไม่เปรียบเทียบ
    pg.select_option("#fCompare", "custom")
    expect(pg.locator("#cmpRange")).to_be_visible()
    pg.fill("#fCFrom", "2026-10-01")
    pg.fill("#fCTo", "2026-10-15")
    pg.locator("#fCTo").dispatch_event("change")
    expect(pg.locator("#dashPeriod")).to_contain_text("เทียบกับช่วงที่เลือก (01/10/2026 – 15/10/2026)")
    expect(pg.locator(".kpi", has=pg.locator(".k-label", has_text="ผลิตได้รวม"))).to_contain_text("▲")
    pg.select_option("#fCompare", "none")
    expect(pg.locator(".kpi .k-cmp")).to_have_count(0)
    pg.select_option("#fCompare", "prev")
    expect(pg.locator(".kpi .k-cmp").first).to_be_visible()

    # ประเภท "ทั้งหมด" → ปัญหา / การปรับปรุง วางคู่กัน (ไม่ซ้อน), % แยกตามประเภท
    pg.select_option("#fType", "all")
    pg.wait_for_timeout(700)
    m = chart_info("cMachine")
    assert m["types"] == ["problem", "improve"] and m["legend"] is True, m
    assert set(m["colors"][0]) == {"#e6774f"} and set(m["colors"][1]) == {"#4a82d4"}, m["colors"]
    assert pg.evaluate("Chart.getChart('cMachine').options.scales.x.stacked") in (None, False)
    d_all = pg.evaluate("lastData.charts.machine")
    imp_total = sum(g["parts"]["improve"]["hours"] for g in d_all)
    order = d_all                                                                    # เรียงตามเครื่อง (ลำดับจาก Server)
    for i, g in enumerate(order):
        v = g["parts"]["improve"]
        assert m["tops"][1][i] == ([f"{v['hours']:g} ({v['count']})", f"{round(v['hours'] / imp_total * 100)}%"] if v["count"] else ["0", "", True]), (g["label"], m["tops"][1][i])
    # Size: คู่เทียบปัญหา/ปรับปรุงของหมวดเดียวกันใช้ระดับโทนเดียวกัน (อ่อนตามกัน)
    sz = chart_info("cSize")
    assert [c == "#e6774f" for c in sz["colors"][0]] == [c == "#4a82d4" for c in sz["colors"][1]], sz["colors"]
    assert chart_info("cShift")["types"] == ["problem"]                              # กะ = ปัญหาเสมอ
    pg.wait_for_timeout(400)
    assert pg.evaluate(labels_ok) == [], pg.evaluate(labels_ok)
    pg.screenshot(path=f"{SHOTS}/06b-dashboard-all.png", full_page=True)
    # คลิกแท่งสีน้ำเงิน (การปรับปรุง) → เฉพาะงานปรับปรุงของเครื่องนั้น
    i = next(i for i, g in enumerate(order) if g["parts"]["improve"]["count"])
    drill = click_bar("cMachine", i, dataset=1)
    expect(drill.locator(".modal-head")).to_contain_text(f"เครื่องจักร: {order[i]['label']}")
    expect(drill.locator(".modal-head")).to_contain_text("ของการปรับปรุงทั้งหมด")
    expect(drill.locator("tbody tr")).to_have_count(order[i]["parts"]["improve"]["count"])
    expect(drill.locator("tbody .pill.problem")).to_have_count(0)
    drill.locator("[data-act=close]").click()
    pg.select_option("#fType", "problem")
    pg.wait_for_timeout(600)

    # เปิดในหน้ารายงาน → ตัวกรองตรงกัน
    drill = click_bar("cMachine", 0)
    drill.locator("[data-act=report]").click()
    pg.wait_for_url("**/report?**")
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("#fMachine")).to_have_value(bar0["key"])
    expect(pg.locator(".sheet-head")).to_contain_text("ไม่รวม Stop Line")
    expect(pg.locator("table.report tbody tr[class^=type-]")).to_have_count(bar0["count"])
    pg.go_back()
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(500)
    # แท่ง "รอดำเนินการ (ยังไม่เกินกำหนด)" → เปิดในหน้ารายงาน ตัวกรองสถานะใหม่
    pg.evaluate("openDrill('improve', lastData.charts.improve[1], null, '0%')")   # 0 งาน (แท่งสูง 0 คลิกไม่ได้)
    drill = pg.locator("dialog.modal.wide")
    expect(drill.locator(".empty-state")).to_have_count(1)
    drill.locator("[data-act=report]").click()
    pg.wait_for_url("**/report?**")
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("#fStatus")).to_have_value("pending_ontime")
    expect(pg.locator(".sheet-head")).to_contain_text("สถานะ: รอดำเนินการ (ยังไม่เกินกำหนด)")
    pg.go_back()
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(500)
    heights = pg.evaluate("[...document.querySelectorAll('.kpi')].map(k => Math.round(k.getBoundingClientRect().height))")
    assert len(set(heights)) == 1, f"กล่องสูงไม่เท่ากัน {heights}"
    # การจัดหน้า: เครื่องจักรเต็มความกว้าง, Size / กะ / งานปรับปรุง แถวเดียวกัน
    lay = pg.evaluate("""['machine','size','shift','improve'].map(k => { const b = document.querySelector(`[data-chart=${k}]`).getBoundingClientRect();
        return [Math.round(b.top), Math.round(b.width)]; })""")
    grid_w = pg.evaluate("Math.round(document.querySelector('.chart-grid').getBoundingClientRect().width)")
    assert lay[0][1] == grid_w and lay[1][0] == lay[2][0] == lay[3][0] > lay[0][0], (lay, grid_w)
    m = pg.locator('[data-chart="machine"]')
    m.locator("[data-sort] button[data-v='count']").click()
    expect(m.locator("[data-note]")).to_contain_text("เรียงตาม ครั้ง")
    counts = chart_info("cMachine")["data"][0]
    assert counts == sorted(counts, reverse=True), counts
    pg.screenshot(path=f"{SHOTS}/06-dashboard.png", full_page=True)
    pg.reload()
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(400)
    expect(m.locator("[data-sort] button.on")).to_have_attribute("data-v", "count")  # จำค่าที่เลือก
    m.locator("[data-sort] button[data-v='machine']").click()

    # พิมพ์ A4 แนวนอน 1 หน้า
    def print_pdf(name):
        pg.wait_for_timeout(500)  # ให้กราฟวาดเสร็จก่อนสั่งพิมพ์ (ผู้ใช้จริงกดพิมพ์ทีหลัง)
        pg.evaluate("window.dispatchEvent(new Event('beforeprint'))")
        problems = pg.evaluate(labels_ok)
        pg.emulate_media(media="print")
        # v1.9: สีแถบหน้ากล่องต้องขึ้นตอนพิมพ์ (เดิมเส้นขอบเทาทับ)
        bad = pg.evaluate("[...document.querySelectorAll('.kpi.bad')].map(k => getComputedStyle(k).borderLeftColor)")
        good = pg.evaluate("[...document.querySelectorAll('.kpi.good')].map(k => getComputedStyle(k).borderLeftColor)")
        assert all(c == "rgb(224, 112, 13)" for c in bad) and all(c != "rgb(205, 211, 223)" for c in good), (bad, good)
        pg.pdf(path=f"{SHOTS}/{name}.pdf", prefer_css_page_size=True, print_background=True)
        pg.emulate_media(media="screen")
        pg.evaluate("window.dispatchEvent(new Event('afterprint'))")
        assert problems == [], (name, problems)
    print_pdf("dashboard")

    # ---------- เครื่องจริง 13 เครื่อง (ข้อมูล มิ.ย. 2025 แยกจากข้อมูลตัวอย่าง ต.ค.) ----------
    REAL = ["Press", "Trim", "Aneal", "Inside", "IBO", "Base", "DO-BC", "Print", "DO-PT", "Cap", "Latex", "Accu.", "Pack"]
    def post_json(path, body):
        req = urllib.request.Request(B + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req))
    def ev(date, machine, type_="problem", to="9.00"):
        return {"date": date, "type": type_, "time_from": "7.00", "time_to": to, "size": "34.92", "machine": machine,
                "problem": "x", "corrective": "", "due_date": "", "responsible": "", "status": "done"}
    for i, mc in enumerate(REAL):
        for k in range(1 + (13 - i) % 3):
            post_json("/api/events", ev(f"2025-06-{1 + (i + k) % 28:02d}", mc, "improve" if k == 1 else "problem", f"{7 + (i + k) % 6}.00"))
    # ชื่อยาว — ก.ค. 2025
    for mc in ("MONDAY Cleaning", "Change Size", *REAL[:10]):
        post_json("/api/events", ev("2025-07-07", mc))
    # 17 เครื่อง (เกิน 15) — ส.ค. 2025
    for mc in (*REAL, "MONDAY Cleaning", "Change Size", "X-Line 1", "X-Line 2"):
        post_json("/api/events", ev("2025-08-08", mc, to="12.00" if mc == "Press" else "8.00"))
    assert [x["name"] for x in api("/api/master")["machine"]] == REAL

    pg.goto(B + "/dashboard?preset=custom&from=2025-06-01&to=2025-06-30&type=all&compare=none")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(800)
    assert len(chart_info("cMachine")["labels"]) == 13
    assert pg.evaluate(labels_ok) == [], pg.evaluate(labels_ok)
    pg.evaluate("sizeChartsForPrint()")                                              # พิมพ์: 13 เครื่องครบ (ไม่รวมเป็นอื่น ๆ)
    assert len(chart_info("cMachine")["labels"]) == 13
    expect(pg.locator('[data-chart="machine"] [data-note]')).not_to_contain_text("พิมพ์")
    assert pg.evaluate("[charts.machine.width, charts.size.width, charts.machine.height, charts.size.height]") == [1045, 330, 174, 189]
    pg.evaluate("restoreChartsAfterPrint()")
    pg.wait_for_timeout(400)
    assert pg.evaluate("charts.machine.options.responsive") is True                  # กลับเป็นขนาดตามจอ
    print_pdf("dashboard-13-all")
    pg.select_option("#fType", "problem")
    pg.wait_for_timeout(600)
    print_pdf("dashboard-13-problem")
    pg.goto(B + "/dashboard?preset=custom&from=2025-07-01&to=2025-07-31&type=problem&compare=none")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(800)
    assert ["MONDAY", "Cleaning"] in chart_info("cMachine")["labels"]
    print_pdf("dashboard-long-names")
    # เกิน 15 เครื่อง → พิมพ์ 14 อันดับแรก + อื่น ๆ (ผลรวมเท่าเดิม); บนจอยังครบ 17
    pg.goto(B + "/dashboard?preset=custom&from=2025-08-01&to=2025-08-31&type=problem&compare=none")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(800)
    assert len(chart_info("cMachine")["labels"]) == 17
    total_h = pg.evaluate("lastData.kpis.hours")
    pg.evaluate("sizeChartsForPrint()")
    lab = chart_info("cMachine")["labels"]
    assert len(lab) == 15 and lab[-1] == ["อื่น ๆ", "(3 เครื่อง)"], lab
    assert sum(chart_info("cMachine")["data"][0]) == total_h
    expect(pg.locator('[data-chart="machine"] [data-note]')).to_contain_text("พิมพ์ 14 รายการแรก + อื่น ๆ")
    pg.evaluate("restoreChartsAfterPrint()")
    assert len(chart_info("cMachine")["labels"]) == 17
    print_pdf("dashboard-17")

    # ---------- ตั้งค่า ----------
    pg.goto(B + "/settings")
    pg.wait_for_load_state("networkidle")
    expect(pg.locator("#masterTabs button")).to_have_count(3)
    # v1.9: เลื่อนลำดับเครื่องจักร ▲▼
    names = lambda: pg.locator("#masterList li .name").all_inner_texts()  # noqa: E731
    assert names()[:3] == ["Press", "Trim", "Aneal"]
    expect(pg.locator("#masterList li").first.locator("[data-act=up]")).to_be_disabled()
    pg.locator("#masterList li").first.locator("[data-act=down]").click()
    expect(pg.locator("#masterList li .name").first).to_have_text("Trim")
    assert [x["name"] for x in api("/api/master")["machine"]][:2] == ["Trim", "Press"]
    pg.locator("#masterList li").nth(1).locator("[data-act=up]").click()
    expect(pg.locator("#masterList li .name").first).to_have_text("Press")
    pg.click("#backupNow")
    expect(pg.locator(".toast.ok").last).to_contain_text("Backup")
    pg.wait_for_timeout(300)
    pg.locator("#backupRows tr", has_text="สร้างเอง").first.locator("[data-act=restore]").click()
    pg.locator("dialog.modal [data-act=ok]").click()
    expect(pg.locator(".toast.ok").last).to_contain_text("Restore สำเร็จ")
    br.close()

print("CONSOLE ERRORS:", errors)
assert not errors
print("E2E PASSED")
