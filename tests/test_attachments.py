import zipfile

from conftest import event

from app import config, db

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def _new_event(client, **kw):
    return client.post("/api/events", json=event(**kw)).json()["id"]


def test_upload_open_delete(client):
    eid = _new_event(client)
    r = client.post(f"/api/events/{eid}/attachments",
                    files=[("files", ("รูปหน้างาน.png", PNG, "image/png")),
                           ("files", ("report.pdf", b"%PDF-1.4 test", "application/pdf"))])
    assert r.status_code == 201
    saved = r.json()
    assert [a["name"] for a in saved] == ["รูปหน้างาน.png", "report.pdf"]
    ev = client.get("/api/events", params={"date": "2026-10-13"}).json()[0]
    assert [a["name"] for a in ev["attachments"]] == ["รูปหน้างาน.png", "report.pdf"]

    got = client.get(f"/api/attachments/{saved[0]['id']}")
    assert got.status_code == 200 and got.content == PNG
    assert got.headers["content-disposition"].startswith("inline")

    assert client.delete(f"/api/attachments/{saved[0]['id']}").status_code == 200
    assert client.get(f"/api/attachments/{saved[0]['id']}").status_code == 404
    assert len(list(db.attach_dir().iterdir())) == 1


def test_rejects_bad_type_size_and_count(client, monkeypatch):
    eid = _new_event(client)
    bad = client.post(f"/api/events/{eid}/attachments", files=[("files", ("virus.exe", b"MZ", "x"))])
    assert bad.status_code == 400 and "ไม่รองรับ" in bad.json()["detail"]
    empty = client.post(f"/api/events/{eid}/attachments", files=[("files", ("a.png", b"", "image/png"))])
    assert empty.status_code == 400

    from app import attachments
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 50)
    big = client.post(f"/api/events/{eid}/attachments", files=[("files", ("big.png", PNG, "image/png"))])
    assert big.status_code == 400 and "ใหญ่เกิน" in big.json()["detail"]
    monkeypatch.setattr(attachments, "MAX_FILE_BYTES", 20 * 1024 * 1024)

    six = [("files", (f"{i}.png", PNG, "image/png")) for i in range(6)]
    assert client.post(f"/api/events/{eid}/attachments", files=six).status_code == 400
    assert list(db.attach_dir().iterdir()) == []  # ไม่มีไฟล์ค้างจากการอัปโหลดที่ไม่ผ่าน
    assert client.post(f"/api/events/999/attachments", files=[("files", ("a.png", PNG, "image/png"))]).status_code == 404


def test_delete_event_removes_files(client):
    eid = _new_event(client)
    client.post(f"/api/events/{eid}/attachments", files=[("files", ("a.png", PNG, "image/png"))])
    r = client.delete(f"/api/events/{eid}").json()
    assert r["attachments_deleted"] == 1
    assert list(db.attach_dir().iterdir()) == []


def test_backup_and_restore_include_attachments(client):
    eid = _new_event(client)
    client.post(f"/api/events/{eid}/attachments", files=[("files", ("a.png", PNG, "image/png"))])
    name = client.post("/api/backups").json()["name"]
    with zipfile.ZipFile(config.BACKUP_DIR / name) as zf:
        assert sum(n.startswith("attachments/") for n in zf.namelist()) == 1

    client.delete(f"/api/events/{eid}")
    assert list(db.attach_dir().iterdir()) == []
    client.post(f"/api/backups/{name}/restore")
    ev = client.get("/api/events", params={"date": "2026-10-13"}).json()[0]
    assert client.get(f"/api/attachments/{ev['attachments'][0]['id']}").content == PNG
