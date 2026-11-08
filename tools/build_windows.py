"""สร้างชุดโปรแกรม Portable สำหรับ Windows 64-bit (รันบน Linux หรือ Windows ก็ได้).

ผลลัพธ์: dist/T14-Machine-Log-v<version>-win64.zip
  - python/  : CPython สำหรับ Windows (แพ็กเกจ "python" จาก nuget.org — ไม่ต้องติดตั้ง)
  - app/, run.py, Start.bat, คู่มือ
"""
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.config import APP_VERSION  # noqa: E402

PYTHON_VERSION = "3.13.16"
PYTHON_URL = f"https://api.nuget.org/v3-flatcontainer/python/{PYTHON_VERSION}/python.{PYTHON_VERSION}.nupkg"
BUILD = ROOT / "build"
DIST = ROOT / "dist"
NAME = "T14-Machine-Log"
COPY_FILES = ["run.py", "requirements.txt", "README_TH.md", "WINDOWS_TEST_CHECKLIST.md",
              "PROJECT_RULES.md", "progress.md", "progress-history.md"]


def download_python() -> Path:
    cache = BUILD / "cache" / f"python.{PYTHON_VERSION}.nupkg"
    if not cache.exists():
        cache.parent.mkdir(parents=True, exist_ok=True)
        print(f"ดาวน์โหลด Python {PYTHON_VERSION} (Windows x64) ...")
        urllib.request.urlretrieve(PYTHON_URL, cache)
    return cache


def extract_python(nupkg: Path, target: Path) -> None:
    with zipfile.ZipFile(nupkg) as zf:
        for info in zf.infolist():
            if not info.filename.startswith("tools/") or info.is_dir():
                continue
            rel = info.filename[len("tools/"):]
            # ไม่ต้องใช้: ชุดทดสอบของ Python, ไฟล์สำหรับคอมไพล์
            if rel.startswith(("Lib/test/", "Lib/idlelib/", "Lib/tkinter/", "Lib/turtledemo/", "include/", "libs/")):
                continue
            out = target / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


def install_packages(site_packages: Path) -> None:
    print("ติดตั้งไลบรารี (win_amd64 wheels) ...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "--quiet", "--no-compile",
        "--target", str(site_packages),
        "--platform", "win_amd64", "--python-version", PYTHON_VERSION.rsplit(".", 1)[0],
        "--implementation", "cp", "--only-binary=:all:",
        "-r", str(ROOT / "requirements.txt"),
    ])
    for junk in site_packages.glob("bin"):
        shutil.rmtree(junk)


def copy_app(target: Path) -> None:
    shutil.copytree(ROOT / "app", target / "app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for name in COPY_FILES:
        shutil.copy2(ROOT / name, target / name)
    # Start.bat ต้องเป็น CRLF สำหรับ cmd.exe
    bat = (ROOT / "Start.bat").read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n")
    (target / "Start.bat").write_bytes(bat.encode("ascii"))


def main() -> None:
    staging = BUILD / NAME
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    extract_python(download_python(), staging / "python")
    install_packages(staging / "python" / "Lib" / "site-packages")
    copy_app(staging)

    DIST.mkdir(exist_ok=True)
    out = DIST / f"{NAME}-v{APP_VERSION}-win64.zip"
    out.unlink(missing_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                zf.write(path, Path(NAME) / path.relative_to(staging))
    print(f"สร้างเสร็จ: {out}  ({out.stat().st_size / 1048576:.1f} MB)")


if __name__ == "__main__":
    main()
