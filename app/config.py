"""ตำแหน่งไฟล์และค่าคงที่ของโปรแกรม."""
import os
from pathlib import Path

APP_NAME = "T14 Machine Log"
APP_VERSION = "1.10.3"

# โฟลเดอร์หลักของโปรแกรม (ที่มี Start.bat) — ตั้ง T14_HOME เพื่อใช้ที่อื่น (เช่น ตอนทดสอบ)
ROOT = Path(os.environ.get("T14_HOME") or Path(__file__).resolve().parent.parent)
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "t14.db"
BACKUP_DIR = ROOT / "backups"
STATIC_DIR = Path(__file__).resolve().parent / "static"

HOST = "0.0.0.0"   # รับการเชื่อมต่อจากเครื่องอื่นใน LAN ด้วย
PORT = int(os.environ.get("T14_PORT", "8014"))

AUTO_BACKUP_KEEP = 30
