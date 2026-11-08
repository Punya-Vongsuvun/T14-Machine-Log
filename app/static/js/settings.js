/* หน้าตั้งค่า */
"use strict";

const $ = (id) => document.getElementById(id);
// ปัญหา / การแก้ไข เป็นช่องพิมพ์อิสระตั้งแต่ v1.2 — ซ่อนแท็บ (ข้อมูลเดิมยังเก็บไว้)
const TABS = ["machine", "size", "person"];
const HINTS = {
  machine: "ลำดับในรายการนี้ = ลำดับในช่องเลือกและกราฟเครื่องจักร (กด ▲▼ เพื่อเลื่อน) · Stop Line เลือกจากปุ่มในกรอบปัญหา",
  size: "", problem: "ข้อความปัญหาที่พบบ่อย", corrective: "ข้อความการแก้ไขที่พบบ่อย", person: "",
};
const state = { master: null, tab: "machine" };

// ---------- ข้อมูลทั่วไป ----------
function fillGeneral(s) {
  $("sLine").value = s.line_name;
  $("sTarget").value = s.default_target ? fmtInt(Number(s.default_target)) : "";
  $("sMorning").value = s.morning_start;
  $("sNight").value = s.night_start;
  $("pathData").textContent = s.data_dir;
  $("pathBackup").textContent = s.backup_dir;
  $("appVersion").textContent = `T14 Machine Log v${s.app_version}`;
}

async function saveGeneral(e) {
  e.preventDefault();
  const target = parseQty($("sTarget").value);
  if (Number.isNaN(target)) { toast("เป้าหมายเริ่มต้นต้องเป็นตัวเลขจำนวนเต็ม", "err"); return; }
  try {
    const s = await api("/api/settings", { method: "PUT", body: {
      line_name: $("sLine").value, default_target: target,
      morning_start: $("sMorning").value, night_start: $("sNight").value,
    } });
    fillGeneral(s);
    await loadSettings(true);
    renderTopbar();
    toast("บันทึกการตั้งค่าแล้ว", "ok");
  } catch (err) { toast(err.message, "err"); }
}

// ---------- Master ----------
function renderTabs() {
  $("masterTabs").innerHTML = TABS.map((k) =>
    `<button type="button" data-kind="${k}" class="${k === state.tab ? "on" : ""}">${MASTER_LABELS[k]} <span class="count">(${state.master[k].length})</span></button>`
  ).join("");
  $("masterHint").textContent = HINTS[state.tab];
  $("addName").placeholder = `เพิ่ม${MASTER_LABELS[state.tab]}ใหม่ ...`;
}

function renderList() {
  const items = state.master[state.tab];
  $("masterList").innerHTML = items.length ? items.map((x, i) => `
    <li data-id="${x.id}">
      <span class="order-btns">
        <button class="btn sm icon" data-act="up" title="เลื่อนขึ้น" ${i === 0 ? "disabled" : ""}>▲</button>
        <button class="btn sm icon" data-act="down" title="เลื่อนลง" ${i === items.length - 1 ? "disabled" : ""}>▼</button>
      </span>
      <span class="name">${esc(state.tab === "size" ? sizeLabel(x.name) : x.name)}</span>
      <button class="btn sm" data-act="edit">แก้ไข</button>
      <button class="btn sm danger" data-act="del">ลบ</button>
    </li>`).join("") : '<li class="empty-state" style="justify-content:center">ยังไม่มีรายการ</li>';
}

async function reloadMaster() {
  state.master = await api("/api/master");
  renderTabs();
  renderList();
}

async function addItem(e) {
  e.preventDefault();
  const name = $("addName").value.trim();
  if (!name) return;
  try {
    await api(`/api/master/${state.tab}`, { method: "POST", body: { name } });
    $("addName").value = "";
    await reloadMaster();
    toast(`เพิ่ม "${name}" แล้ว`, "ok");
  } catch (err) { toast(err.message, "err"); }
}

function editItem(li) {
  const id = Number(li.dataset.id);
  const item = state.master[state.tab].find((x) => x.id === id);
  li.innerHTML = `<input class="input grow" value="${esc(item.name)}">
    <button class="btn sm primary" data-act="save">บันทึก</button>
    <button class="btn sm" data-act="cancel">ยกเลิก</button>`;
  const input = li.querySelector("input");
  input.focus();
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveItem(li);
    if (e.key === "Escape") renderList();
  });
}

async function saveItem(li) {
  const name = li.querySelector("input").value.trim();
  if (!name) { toast("กรุณากรอกชื่อ", "err"); return; }
  try {
    await api(`/api/master/${state.tab}/${li.dataset.id}`, { method: "PUT", body: { name } });
    await reloadMaster();
    toast("แก้ไขแล้ว — รายการที่บันทึกไว้ก่อนหน้าไม่เปลี่ยนตาม", "ok");
  } catch (err) { toast(err.message, "err"); }
}

/** เลื่อนลำดับ (v1.9) — ลำดับนี้ใช้ในช่องเลือกและกราฟเครื่องจักรใน Dashboard */
async function moveItem(li, dir) {
  try {
    state.master = await api(`/api/master/${state.tab}/${li.dataset.id}/move?dir=${dir}`, { method: "POST" });
    renderList();
    $("masterList").querySelector(`li[data-id="${li.dataset.id}"] [data-act="${dir}"]`)?.focus();
  } catch (err) { toast(err.message, "err"); }
}

async function deleteItem(li) {
  const item = state.master[state.tab].find((x) => x.id === Number(li.dataset.id));
  const ok = await confirmBox("ลบรายการตัวเลือก",
    `ลบ "<b>${esc(item.name)}</b>" ออกจากรายการ${MASTER_LABELS[state.tab]}?<br><span class="small">ข้อมูลที่บันทึกไว้แล้วจะไม่ถูกลบหรือเปลี่ยนแปลง</span>`, "ลบ", true);
  if (!ok) return;
  try {
    await api(`/api/master/${state.tab}/${item.id}`, { method: "DELETE" });
    await reloadMaster();
    toast("ลบแล้ว", "ok");
  } catch (err) { toast(err.message, "err"); }
}

// ---------- Backup ----------
async function loadBackups() {
  try {
    const list = await api("/api/backups");
    $("backupRows").innerHTML = list.length ? list.map((b) => `
      <tr data-name="${esc(b.name)}">
        <td class="num">${fmtDate(b.created_at.slice(0, 10))} ${b.created_at.slice(11, 16)} น.</td>
        <td><span class="pill">${esc(b.kind_label)}</span></td>
        <td class="small">${esc(b.name)}</td>
        <td class="r num">${fmtSize(b.size_bytes)}</td>
        <td class="c" style="white-space:nowrap">
          <a class="btn sm" href="/api/backups/${encodeURIComponent(b.name)}" download>ดาวน์โหลด</a>
          <button class="btn sm danger" data-act="restore">Restore</button>
        </td>
      </tr>`).join("") : '<tr><td colspan="5" class="empty-state">ยังไม่มีไฟล์ Backup</td></tr>';
  } catch (err) { toast(err.message, "err"); }
}

async function backupNow() {
  try {
    const b = await api("/api/backups", { method: "POST" });
    toast(`สร้าง Backup แล้ว: ${b.name}`, "ok");
    loadBackups();
  } catch (err) { toast(err.message, "err"); }
}

const RESTORE_WARNING = `ข้อมูลปัจจุบัน<b>ทั้งหมด</b>จะถูกแทนที่ด้วยข้อมูลจากไฟล์ Backup<br><br>
  ระบบจะสร้าง Backup "ก่อน Restore" ของข้อมูลปัจจุบันให้อัตโนมัติ — หากผิดพลาดสามารถ Restore กลับได้`;

function restoreDone(r) {
  const c = r.restored.counts;
  toast(`Restore สำเร็จ — รายการ ${c.events}, ยอดผลิต ${c.daily_output} วัน (Backup ก่อน Restore: ${r.safety_backup})`, "ok");
  loadBackups();
  reloadMaster();
  loadSettings(true).then((s) => { fillGeneral(s); renderTopbar(); });
}

async function restoreNamed(name) {
  const ok = await confirmBox("ยืนยันการ Restore", `จากไฟล์ <b>${esc(name)}</b><br><br>${RESTORE_WARNING}`, "Restore", true);
  if (!ok) return;
  try { restoreDone(await api(`/api/backups/${encodeURIComponent(name)}/restore`, { method: "POST" })); }
  catch (err) { toast(err.message, "err"); }
}

async function restoreUpload() {
  const file = $("restoreFile").files[0];
  if (!file) { toast("กรุณาเลือกไฟล์ .zip ก่อน", "err"); return; }
  const ok = await confirmBox("ยืนยันการ Restore", `จากไฟล์ <b>${esc(file.name)}</b><br><br>${RESTORE_WARNING}`, "Restore", true);
  if (!ok) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    restoreDone(await api("/api/restore-upload", { method: "POST", body: fd }));
    $("restoreFile").value = "";
  } catch (err) { toast(err.message, "err"); }
}

// ---------- เริ่มต้น ----------
async function init() {
  try {
    fillGeneral(await loadSettings(true));
    await reloadMaster();
  } catch (err) { toast(err.message, "err"); }
  loadBackups();

  $("generalForm").addEventListener("submit", saveGeneral);
  $("sTarget").addEventListener("blur", (e) => { const v = parseQty(e.target.value); if (v !== null && !Number.isNaN(v)) e.target.value = fmtInt(v); });
  ["sMorning", "sNight"].forEach((id) => $(id).addEventListener("blur", (e) => {
    const m = parseTime(e.target.value); if (m !== null) e.target.value = formatTime(m);
  }));
  $("masterTabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-kind]");
    if (!b) return;
    state.tab = b.dataset.kind;
    renderTabs();
    renderList();
  });
  $("addForm").addEventListener("submit", addItem);
  $("masterList").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    const li = b.closest("li");
    ({ edit: editItem, del: deleteItem, save: saveItem, cancel: () => renderList(),
       up: (x) => moveItem(x, "up"), down: (x) => moveItem(x, "down") })[b.dataset.act](li);
  });
  $("backupNow").addEventListener("click", backupNow);
  $("backupRows").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-act=restore]");
    if (b) restoreNamed(b.closest("tr").dataset.name);
  });
  $("restoreUpload").addEventListener("click", restoreUpload);
}

document.addEventListener("DOMContentLoaded", init);
