import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402


@pytest.fixture()
def home(tmp_path, monkeypatch):
    """ใช้โฟลเดอร์ชั่วคราวแยกต่อการทดสอบ — ไม่แตะข้อมูลจริง."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "data" / "t14.db")
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    return tmp_path


@pytest.fixture()
def client(home):
    from app.main import app

    with TestClient(app) as c:
        yield c


def event(**overrides):
    body = {
        "date": "2026-10-13", "type": "problem", "time_from": "19.00", "time_to": "20.00",
        "size": "34.92", "machine": "Press", "problem": "แก้ไขท้ายพับทางออกเตาอบนิ่ม",
        "corrective": "ปรับดอร์นกลึง No.5", "due_date": "", "responsible": "", "status": "done",
    }
    body.update(overrides)
    return body
