"""สูตรคำนวณเวลา ชั่วโมง และกะ (ต้องตรงกับ app/static/js/common.js เสมอ)."""
import re
from datetime import date

MINUTES_PER_DAY = 24 * 60

_TIME_RE = re.compile(r"^\s*(\d{1,2})(?:\s*[.:]\s*(\d{2}))?\s*$")


def parse_time(text: str) -> int:
    """แปลง "7", "7.00", "07:30", "24.00" เป็นจำนวนนาที (0–1440)."""
    m = _TIME_RE.match(str(text or ""))
    if not m:
        raise ValueError(f"รูปแบบเวลาไม่ถูกต้อง: '{text}' (ใช้ HH.MM เช่น 7.00 หรือ 13.30)")
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if hour > 24 or minute > 59 or (hour == 24 and minute != 0):
        raise ValueError(f"เวลาไม่ถูกต้อง: '{text}' (ช่วง 0.00–24.00)")
    return hour * 60 + minute


def format_time(minutes: int) -> str:
    """แปลงจำนวนนาทีเป็นข้อความ HH.MM (1440 → "24.00")."""
    return f"{minutes // 60:02d}.{minutes % 60:02d}"


def calc_hours(from_min: int, to_min: int) -> float:
    """ชั่วโมงแบบรวมชั่วโมงต้น-ท้าย ตามฟอร์มกระดาษ: (สิ้นสุด − เริ่ม) + 1, ข้ามเที่ยงคืนได้.

    7.00–8.00 = 2, 13.00–13.00 = 1, 19.00–3.00 = 9
    """
    diff = (to_min - from_min) % MINUTES_PER_DAY
    return round(diff / 60 + 1, 2)


def calc_shift(from_min: int, morning_start: int, night_start: int) -> str:
    """'M' (เช้า) ถ้าเวลาเริ่มอยู่ใน [morning_start, night_start) มิฉะนั้น 'N' (ดึก)."""
    m = from_min % MINUTES_PER_DAY
    return "M" if morning_start <= m < night_start else "N"


def production_order(from_min: int, morning_start: int) -> int:
    """ลำดับเวลาภายในวันผลิต (เริ่มนับจากต้นกะเช้า) ใช้เรียงรายการ."""
    return (from_min - morning_start) % MINUTES_PER_DAY


def stop_line_default_hours(start_date: date, end_date: date) -> float:
    """ชั่วโมงเริ่มต้นของ Stop Line (v1.2 ไม่มีเวลา): จำนวนวันรวมวันแรก-วันสุดท้าย × 24.

    23/10 → 23/10 = 24, 23/10 → 25/10 = 72 (ผู้ใช้แก้ตัวเลขเองได้)
    """
    days = (end_date - start_date).days + 1
    if days < 1:
        raise ValueError("วันที่สิ้นสุดของ Stop Line ต้องไม่ก่อนวันที่เริ่ม")
    return float(days * 24)


def calc_rate_hours(target: int, actuals: list[int]) -> float:
    """ชั่วโมงสูญเสียจากยอดผลิต (v1.9 — ใช้เมื่อเครื่องเสียแต่ยังมีงานออกไม่เต็ม 100%):

    เวลาที่สูญเสีย = (เป้า − ผลิตได้จริงเฉลี่ย) ÷ เป้า × จำนวนชั่วโมงที่กรอก = Σ (เป้า − ผลิตได้ชั่วโมงนั้น) ÷ เป้า
    เป้า 6,000/ชม. ผลิตได้ 4,500 + 3,000 + 5,400 → (1,500 + 3,000 + 600) ÷ 6,000 = 0.85 ชม.
    ผลิตได้เกินเป้าในบางชั่วโมงหักกับชั่วโมงอื่นตามสูตร — ผลรวมไม่ติดลบ
    """
    lost = sum(target - a for a in actuals) / target
    return max(0.0, round(lost, 2))


def rate_slots(from_min: int, to_min: int) -> list[int]:
    """ช่องผลิตได้จริงของโหมดยอดผลิต (v1.10): 1 ช่องต่อ 1 ชั่วโมงในช่วงเวลา นับแบบรวมชั่วโมงต้น-ท้าย เหมือน calc_hours.

    9.00–10.00 → [9.00, 10.00], 13.00–13.00 → [13.00], 23.00–1.00 → [23.00, 0.00, 1.00], 9.00–10.30 → [9.00, 10.00]
    คืนค่าเวลาเริ่มของแต่ละช่อง (นาที 0–1439)
    """
    diff = (to_min - from_min) % MINUTES_PER_DAY
    return [(from_min + i * 60) % MINUTES_PER_DAY for i in range(diff // 60 + 1)]
