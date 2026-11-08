"""โครงสร้างข้อมูลขาเข้า (ตรวจสอบความถูกต้องก่อนบันทึก)."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.timecalc import format_time, parse_time, rate_slots, stop_line_default_hours

EventType = Literal["problem", "improve"]
Status = Literal["done", "pending", "in_progress"]
PlannedStop = Literal["cleaning"]  # v1.10 หยุดตามแผน (บันทึกอย่างเดียว ไม่นับชั่วโมง/กราฟ) — ตอนนี้มีแบบเดียว
CLEANING_LABEL = "Monday Cleaning"
MasterKind = Literal["machine", "size", "problem", "corrective", "person"]

MAX_QTY = 100_000_000


def _strip(v):
    return v.strip() if isinstance(v, str) else v


class EventIn(BaseModel):
    """รายการ 4 แบบ: ปัญหาเครื่องจักร / Stop Line / Monday Cleaning (อยู่ในกรอบปัญหา) / การปรับปรุง.

    - ปัญหาเครื่องจักร: เวลา + เครื่องจักร บังคับ, ไม่มีกำหนดเสร็จ/ผู้รับผิดชอบ/สถานะ
      (โหมดคิดจากยอดผลิต: เวลา + เป้า/ชม. + ผลิตได้จริงแต่ละชั่วโมง — v1.10 มีเวลา กะคิดจากเวลาเริ่ม)
    - Monday Cleaning (v1.10): เวลาบังคับ, เครื่องจักรไม่บังคับ, ไม่มี Size — บันทึกอย่างเดียวเหมือน Stop Line
    - Stop Line: วันที่เริ่ม-สิ้นสุด + ชั่วโมง (กรอกได้), ไม่มีเวลา/กะ/Size/กำหนดเสร็จ/ผู้รับผิดชอบ/สถานะ
    - การปรับปรุง: เวลา + เครื่องจักร บังคับ, สถานะ 3 ค่า
    """
    date: date  # วันที่ของรายการ (Stop Line = วันที่เริ่ม)
    type: EventType
    stop_line: bool = False
    planned_stop: PlannedStop | None = None  # v1.10 Monday Cleaning
    end_date: date | None = None  # ใช้เฉพาะ Stop Line
    hours: float | None = Field(None, gt=0)  # ใช้เฉพาะ Stop Line (รายการอื่นคำนวณจากเวลา)
    time_from: str | None = None
    time_to: str | None = None
    size: str = Field("", max_length=50)
    machine: str = Field("", max_length=100)
    problem: str = Field(..., min_length=1, max_length=2000)
    corrective: str = Field("", max_length=2000)
    due_date: date | None = None
    responsible: str = Field("", max_length=200)
    status: Status | None = None
    # v1.9 คิดชั่วโมงจากยอดผลิต (เฉพาะปัญหาเครื่องจักร): เป้า/ชม. + ผลิตได้จริงแต่ละชั่วโมง
    # v1.10 ต้องกรอกเวลาเริ่ม-สิ้นสุด → กะคิดจากเวลาเริ่ม (ไม่รับกะจากผู้ใช้แล้ว ส่งมาก็ไม่ใช้)
    rate_target: int | None = Field(None, gt=0, le=MAX_QTY)
    rate_actuals: list[int] | None = Field(None, max_length=48)
    shift: Literal["M", "N"] | None = None

    @model_validator(mode="before")
    @classmethod
    def _cleaning_default_text(cls, data):
        # Monday Cleaning: ช่องรายละเอียดไม่บังคับ — ว่าง = "Monday Cleaning"
        if isinstance(data, dict) and data.get("planned_stop") == "cleaning" and not str(data.get("problem") or "").strip():
            data = {**data, "problem": CLEANING_LABEL}
        return data

    _strip_text = field_validator(
        "size", "machine", "problem", "corrective", "responsible", "time_from", "time_to", mode="before"
    )(_strip)

    @field_validator("size", mode="after")
    @classmethod
    def _plain_size(cls, v: str) -> str:
        # ⌀ เป็นสัญลักษณ์ที่แสดงบนหน้าจอเท่านั้น — เก็บเฉพาะตัวเลข
        return v.lstrip("⌀Øø ").strip()

    @field_validator("due_date", "end_date", "time_from", "time_to", "status", "hours", "rate_target", "shift",
                     "planned_stop", mode="before")
    @classmethod
    def _empty_to_none(cls, v):
        return None if v == "" else v

    @field_validator("time_from", "time_to")
    @classmethod
    def _valid_time(cls, v: str | None) -> str | None:
        return None if v is None else format_time(parse_time(v))

    @field_validator("rate_actuals")
    @classmethod
    def _valid_actuals(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and any(a < 0 or a > MAX_QTY for a in v):
            raise ValueError("ผลิตได้จริง: ต้องเป็นจำนวนเต็มตั้งแต่ 0 ขึ้นไป")
        return v or None  # [] = ไม่ใช้โหมดยอดผลิต

    def _require_times(self) -> None:
        if self.time_from is None:
            raise ValueError("เวลาเริ่ม: กรุณากรอกข้อมูล")
        if self.time_to is None:
            raise ValueError("เวลาสิ้นสุด: กรุณากรอกข้อมูล")

    @model_validator(mode="after")
    def _rules(self):
        self.shift = None  # กะคิดจากเวลาเริ่มเสมอ (v1.10 รวมโหมดยอดผลิต)
        if self.rate_actuals is not None:
            if self.type != "problem" or self.stop_line or self.planned_stop:
                raise ValueError("การคิดชั่วโมงจากยอดผลิต ใช้ได้กับปัญหาเครื่องจักรเท่านั้น")
            if self.rate_target is None:
                raise ValueError("เป้าผลิต/ชม.: กรุณากรอกข้อมูล")
            self._require_times()  # v1.10 ช่วงเวลาบอกตำแหน่งเท่านั้น — ชั่วโมงยังมาจากสูตรยอดผลิต
            slots = len(rate_slots(parse_time(self.time_from), parse_time(self.time_to)))
            if len(self.rate_actuals) > slots:
                raise ValueError(f"ผลิตได้จริง: ช่วงเวลา {self.time_from}–{self.time_to} มี {slots} ชั่วโมง "
                                 f"แต่กรอกยอดผลิต {len(self.rate_actuals)} ชั่วโมง")
            if not self.machine:
                raise ValueError("เครื่องจักร: กรุณากรอกข้อมูล")
            self.end_date = None
            self.hours = None
            self.due_date, self.responsible, self.status = None, "", None
            return self
        self.rate_target = None
        if self.planned_stop:
            if self.type != "problem" or self.stop_line:
                raise ValueError("Monday Cleaning ใช้ได้ในกรอบปัญหาเท่านั้น (ไม่ใช่ Stop Line)")
            self._require_times()
            self.end_date = None
            self.hours = None
            self.size = ""
            self.due_date, self.responsible, self.status = None, "", None
            return self
        if self.stop_line:
            if self.type != "problem":
                raise ValueError("Stop Line ใช้ได้กับประเภทปัญหาเท่านั้น")
            if self.end_date is None:
                raise ValueError("วันที่สิ้นสุด: กรุณาระบุวันที่สิ้นสุดของ Stop Line")
            days = (self.end_date - self.date).days + 1
            if days < 1:
                raise ValueError("วันที่สิ้นสุดของ Stop Line ต้องไม่ก่อนวันที่เริ่ม")
            if self.hours is None:
                self.hours = stop_line_default_hours(self.date, self.end_date)
            if self.hours > days * 24:
                raise ValueError(f"ชั่วโมง: Stop Line {days} วัน มีได้ไม่เกิน {days * 24} ชม.")
            self.time_from = self.time_to = None
            self.size = ""
        else:
            self._require_times()
            if not self.machine:
                raise ValueError("เครื่องจักร: กรุณากรอกข้อมูล")
            self.end_date = None
            self.hours = None
        if self.type == "problem":
            self.due_date, self.responsible, self.status = None, "", None
        elif self.status is None:
            self.status = "pending"
        return self


class DailyMoveIn(BaseModel):
    """v1.10 ย้ายยอดผลิตที่กรอกผิดวันไปวันที่ถูก (ไม่เขียนทับวันที่มียอดผลิตอยู่แล้ว)."""
    to: date
    with_events: bool = False  # ย้ายรายการปัญหา/ปรับปรุงของวันนั้นไปด้วย


class DailyIn(BaseModel):
    target: int | None = Field(None, ge=0, le=MAX_QTY)
    output: int | None = Field(None, ge=0, le=MAX_QTY)
    holiday: bool = False  # v1.5: วันหยุด — เป้าหมาย/ผลิตได้ไม่บังคับ (ถ้ากรอกครบยังนับตามปกติ)


class SettingsIn(BaseModel):
    line_name: str = Field(..., min_length=1, max_length=50)
    default_target: int | None = Field(None, ge=0, le=MAX_QTY)
    morning_start: str
    night_start: str

    _strip_text = field_validator("line_name", "morning_start", "night_start", mode="before")(_strip)

    @field_validator("default_target", mode="before")
    @classmethod
    def _empty_target(cls, v):
        return None if v == "" else v

    @field_validator("morning_start", "night_start")
    @classmethod
    def _valid_time(cls, v: str) -> str:
        minutes = parse_time(v)
        if minutes >= 1440:
            raise ValueError("เวลาเริ่มกะต้องอยู่ระหว่าง 0.00–23.59")
        return format_time(minutes)

    @model_validator(mode="after")
    def _order(self):
        if parse_time(self.morning_start) >= parse_time(self.night_start):
            raise ValueError("เวลาเริ่มกะเช้าต้องน้อยกว่าเวลาเริ่มกะดึก")
        return self


class MasterIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=2000)

    _strip_text = field_validator("name", mode="before")(_strip)
