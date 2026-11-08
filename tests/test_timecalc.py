import pytest

from app.timecalc import calc_hours, calc_shift, format_time, parse_time

M, N = 6 * 60, 18 * 60


@pytest.mark.parametrize("text,minutes", [
    ("7", 420), ("7.00", 420), ("07:30", 450), ("13.30", 810), ("0.00", 0), ("24.00", 1440), (" 1.05 ", 65),
])
def test_parse_time_valid(text, minutes):
    assert parse_time(text) == minutes


@pytest.mark.parametrize("text", ["", "abc", "25.00", "24.30", "7.60", "7.5", "-1", "12.345", None])
def test_parse_time_invalid(text):
    with pytest.raises(ValueError):
        parse_time(text)


def test_format_time():
    assert format_time(420) == "07.00"
    assert format_time(1440) == "24.00"


# ตัวอย่างจริงจากฟอร์มกระดาษ T14 (เดือน ต.ค.)
@pytest.mark.parametrize("start,end,hours", [
    ("2.00", "3.00", 2),     # 05-Oct
    ("7.00", "8.00", 2),     # 06-Oct
    ("21.00", "21.00", 1),   # 06-Oct
    ("1.00", "6.00", 6),     # 06-Oct
    ("19.00", "3.00", 9),    # 08-Oct ChangeSize ข้ามเที่ยงคืน
    ("4.00", "6.00", 3),     # 08-Oct
    ("7.00", "13.00", 7),    # 12-Oct MONDAY Cleaning
    ("14.00", "18.00", 5),   # 15-Oct
    ("24.00", "3.00", 4),    # 08-Oct (กระดาษเขียน 5 — สูตรได้ 4)
    ("24.00", "5.00", 6),    # 19-Oct ChangeSize
])
def test_calc_hours_matches_paper(start, end, hours):
    assert calc_hours(parse_time(start), parse_time(end)) == hours


def test_calc_hours_with_minutes():
    assert calc_hours(parse_time("7.30"), parse_time("8.00")) == 1.5


@pytest.mark.parametrize("start,shift", [
    ("6.00", "M"), ("7.00", "M"), ("17.59", "M"), ("18.00", "N"), ("19.00", "N"),
    ("24.00", "N"), ("0.00", "N"), ("1.00", "N"), ("5.00", "N"), ("5.59", "N"),
])
def test_calc_shift(start, shift):
    assert calc_shift(parse_time(start), M, N) == shift


def test_stop_line_default_hours():
    from datetime import date

    from app.timecalc import stop_line_default_hours
    assert stop_line_default_hours(date(2026, 10, 23), date(2026, 10, 23)) == 24
    assert stop_line_default_hours(date(2026, 10, 23), date(2026, 10, 25)) == 72
    with pytest.raises(ValueError):
        stop_line_default_hours(date(2026, 10, 24), date(2026, 10, 23))
