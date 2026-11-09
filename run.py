"""ตัวเปิดโปรแกรม T14 Machine Log — เรียกจาก Start.bat."""
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402

URL = f"http://localhost:{config.PORT}/"
CHECK_HOST = "127.0.0.1"  # เช็กตัวเอง (config.HOST = 0.0.0.0 ใช้เป็นปลายทางเชื่อมต่อบน Windows ไม่ได้)


def _port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((CHECK_HOST, config.PORT)) == 0


def _is_our_app() -> bool:
    try:
        with urllib.request.urlopen(f"http://{CHECK_HOST}:{config.PORT}/api/health", timeout=2) as r:
            return config.APP_NAME.encode() in r.read()
    except OSError:
        return False


def _open_browser_when_ready() -> None:
    for _ in range(60):
        if _port_in_use():
            webbrowser.open(URL)
            return
        time.sleep(0.5)


def main() -> int:
    if _port_in_use():
        if _is_our_app():
            print("โปรแกรมเปิดอยู่แล้ว — กำลังเปิด Browser ...")
            webbrowser.open(URL)
            return 0
        print(f"[ผิดพลาด] Port {config.PORT} ถูกโปรแกรมอื่นใช้งานอยู่")
        return 1

    import uvicorn

    print("=" * 60)
    print(f" {config.APP_NAME} v{config.APP_VERSION}")
    print(f" เปิดใช้งานที่: {URL}")
    print(f" ข้อมูล:  {config.DB_PATH}")
    print(f" Backup:  {config.BACKUP_DIR}")
    print(" ** ห้ามปิดหน้าต่างนี้ระหว่างใช้งาน (ย่อหน้าต่างได้) **")
    print(" ** ปิดโปรแกรม: กด Ctrl + C หรือปิดหน้าต่างนี้ **")
    print("=" * 60)
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
