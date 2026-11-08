/* T14 Machine Log — ฟังก์ชันที่ใช้ร่วมกันทุกหน้า */
"use strict";

const THAI_DAYS = ["อาทิตย์", "จันทร์", "อังคาร", "พุธ", "พฤหัสบดี", "ศุกร์", "เสาร์"];
const TYPE_LABELS = { problem: "ปัญหา", improve: "การปรับปรุง" };
const STATUS_LABELS = { pending: "รอดำเนินการ", in_progress: "ระหว่างดำเนินการ", done: "เสร็จแล้ว" };
const MASTER_LABELS = {
  machine: "เครื่องจักร", size: "Size",
  problem: "ปัญหา", corrective: "การแก้ไข", person: "ผู้รับผิดชอบ",
};

// ---------- API ----------
async function api(path, options = {}) {
  const opts = { ...options, headers: { ...(options.headers || {}) } };
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (err) {
    throw new Error("ติดต่อโปรแกรมไม่ได้ — ตรวจสอบว่าหน้าต่างโปรแกรม (Start.bat) ยังเปิดอยู่");
  }
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch (_) { data = null; }
  if (!res.ok) {
    const detail = data && data.detail;
    throw new Error(typeof detail === "string" ? detail : `เกิดข้อผิดพลาด (${res.status})`);
  }
  return data;
}

// ---------- Format ----------
const nf = new Intl.NumberFormat("en-US");
function fmtInt(n) { return n === null || n === undefined || n === "" ? "" : nf.format(n); }
function fmtSigned(n) {
  if (n === null || n === undefined) return "";
  return (n > 0 ? "+" : n < 0 ? "−" : "") + nf.format(Math.abs(n));
}
function signClass(n) { return n > 0 ? "pos" : n < 0 ? "neg" : ""; }
function fmtHours(h) { return Number.isInteger(h) ? String(h) : String(Math.round(h * 100) / 100); }
/** Size แสดงพร้อมสัญลักษณ์เส้นผ่านศูนย์กลาง ⌀ (ข้อมูลเก็บเฉพาะตัวเลข) */
function sizeLabel(v) {
  const t = String(v ?? "").replace(/^[⌀Øø]\s*/, "").trim();
  return t ? `⌀${t}` : "";
}
function hoursCount(h, c) { return `${fmtHours(h)} ชม. (${c} ครั้ง)`; }
function parseQty(text) {
  const clean = String(text || "").replace(/[,\s]/g, "");
  if (clean === "") return null;
  if (!/^\d+$/.test(clean)) return NaN;
  return Number(clean);
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// ---------- Dates (ใช้เวลาท้องถิ่นของเครื่อง) ----------
function isoDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function parseIso(iso) { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d); }
function todayIso() { return isoDate(new Date()); }
function addDays(iso, n) { const d = parseIso(iso); d.setDate(d.getDate() + n); return isoDate(d); }
function fmtDate(iso) { if (!iso) return ""; const [y, m, d] = iso.split("-"); return `${d}/${m}/${y}`; }
function thaiDay(iso) { return THAI_DAYS[parseIso(iso).getDay()]; }

// ---------- เวลา / ชั่วโมง / กะ (ต้องตรงกับ app/timecalc.py) ----------
const MINUTES_PER_DAY = 1440;
function parseTime(text) {
  const m = /^\s*(\d{1,2})(?:\s*[.:]\s*(\d{2}))?\s*$/.exec(String(text || ""));
  if (!m) return null;
  const h = Number(m[1]), min = Number(m[2] || 0);
  if (h > 24 || min > 59 || (h === 24 && min !== 0)) return null;
  return h * 60 + min;
}
function formatTime(minutes) {
  return `${String(Math.floor(minutes / 60)).padStart(2, "0")}.${String(minutes % 60).padStart(2, "0")}`;
}
function calcHours(fromMin, toMin) {
  const diff = (((toMin - fromMin) % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  return Math.round((diff / 60 + 1) * 100) / 100;
}
/** ชั่วโมงเริ่มต้นของ Stop Line = จำนวนวัน (รวมวันแรก-วันสุดท้าย) × 24 — null ถ้าสิ้นสุดก่อนเริ่ม (ตรงกับ stop_line_default_hours) */
function stopLineDays(startIso, endIso) {
  const days = Math.round((parseIso(endIso) - parseIso(startIso)) / 86400000) + 1;
  return days >= 1 ? days : null;
}
/** ชั่วโมงสูญเสียจากยอดผลิต: Σ (เป้า − ผลิตได้ชั่วโมงนั้น) ÷ เป้า, ไม่ติดลบ (ตรงกับ calc_rate_hours) */
function calcRateHours(target, actuals) {
  const lost = actuals.reduce((s, a) => s + (target - a), 0) / target;
  return Math.max(0, Math.round(lost * 100) / 100);
}
/** ช่องผลิตได้จริง 1 ช่องต่อ 1 ชั่วโมงในช่วงเวลา (นับรวมต้น-ท้ายเหมือน calcHours) — คืนเวลาเริ่มของแต่ละช่อง (ตรงกับ rate_slots)
 *  9.00–10.00 → [9.00, 10.00], 23.00–1.00 → [23.00, 0.00, 1.00] */
function rateSlots(fromMin, toMin) {
  const diff = (((toMin - fromMin) % MINUTES_PER_DAY) + MINUTES_PER_DAY) % MINUTES_PER_DAY;
  return Array.from({ length: Math.floor(diff / 60) + 1 }, (_, i) => (fromMin + i * 60) % MINUTES_PER_DAY);
}
/** ข้อความยอดผลิต (จาง ๆ ในรายงาน/หน้าต่างรายการ): "ผลิต 4,500 · 3,000 / เป้า 6,000" */
function rateNote(e) {
  return e.rate_actuals ? `ผลิต ${e.rate_actuals.map(fmtInt).join(" · ")} / เป้า ${fmtInt(e.rate_target)}` : "";
}
/** ช่องเวลาในหน้าต่างรายการ: Stop Line = วันที่, รายการเวลา = HH.MM–HH.MM (+ ยอดผลิตแบบจางใต้เวลา), ยอดผลิตเก่าไม่มีเวลา = ยอดผลิต */
function eventTimeText(e) {
  if (e.stop_line) return `${fmtDate(e.date).slice(0, 5)}–${fmtDate(e.end_date).slice(0, 5)}`;
  const note = e.rate_actuals ? `<span class="rate-note">${esc(rateNote(e))}</span>` : "";
  if (!e.time_from) return note;
  return `${esc(e.time_from)}–${esc(e.time_to)}${note ? `<br>${note}` : ""}`;
}
function calcShift(fromMin, morningStart, nightStart) {
  const m = fromMin % MINUTES_PER_DAY;
  return m >= morningStart && m < nightStart ? "M" : "N";
}

// ---------- ไฟล์แนบ (ตรงกับ app/attachments.py) ----------
const ATTACH_EXT = [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".pdf", ".xls", ".xlsx", ".xlsm", ".csv", ".doc", ".docx"];
const ATTACH_MAX_MB = 20;
const ATTACH_MAX_FILES = 5;
function fileExt(name) { const i = name.lastIndexOf("."); return i < 0 ? "" : name.slice(i).toLowerCase(); }
function fmtSize(bytes) {
  return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}
/** ป้ายสถานะงานปรับปรุง (รอดำเนินการ / ระหว่างดำเนินการ / เสร็จแล้ว / เกินกำหนด) */
function statusPill(e, today = todayIso()) {
  if (!e.status) return "";
  const overdue = e.status !== "done" && e.due_date && e.due_date < today;
  return `<span class="pill ${e.status}">${STATUS_LABELS[e.status]}</span>${overdue ? ' <span class="pill overdue">เกินกำหนด</span>' : ""}`;
}
function attachLinks(list) {
  return (list || []).map((a) => `<a class="file-link" href="/api/attachments/${a.id}" target="_blank" rel="noopener" title="${esc(a.name)}">📎 ${esc(a.name)}</a>`).join(" ");
}

// ---------- Toast ----------
/** action = { label, onClick } — ปุ่มในข้อความ (v1.10 เช่น "ไปที่วันที่ …") ข้อความที่มีปุ่มแสดงนานขึ้น */
function toast(message, kind = "", action = null) {
  let box = document.getElementById("toasts");
  if (!box) { box = document.createElement("div"); box.id = "toasts"; document.body.appendChild(box); }
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  if (action) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "toast-act";
    b.textContent = action.label;
    b.addEventListener("click", () => { el.remove(); action.onClick(); });
    el.appendChild(b);
  }
  box.appendChild(el);
  while (box.children.length > 3) box.firstChild.remove(); // ไม่ให้ซ้อนจนบังหน้าจอ
  setTimeout(() => el.remove(), action ? 9000 : kind === "err" ? 7000 : 3500);
}

// ---------- Modal ----------
/** แสดงกล่องยืนยัน — คืนค่า false เมื่อยกเลิก, ถ้ามี collect(dlg) คืนค่าจาก collect เมื่อกดตกลง */
function modal({ title, html, okText = "ตกลง", cancelText = "ยกเลิก", danger = false, collect, wide = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = wide ? "modal wide" : "modal";
    dlg.innerHTML = `
      <div class="modal-head">${esc(title)}</div>
      <div class="modal-body">${html || ""}</div>
      <div class="modal-foot">
        ${cancelText ? `<button type="button" class="btn" data-act="cancel">${esc(cancelText)}</button>` : ""}
        <button type="button" class="btn ${danger ? "danger solid" : "primary"}" data-act="ok">${esc(okText)}</button>
      </div>`;
    document.body.appendChild(dlg);
    const close = (val) => { dlg.close(); dlg.remove(); resolve(val); };
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(false); });
    dlg.querySelector('[data-act="ok"]').addEventListener("click", () => close(collect ? collect(dlg) : true));
    const cancel = dlg.querySelector('[data-act="cancel"]');
    if (cancel) cancel.addEventListener("click", () => close(false));
    dlg.showModal();
    dlg.querySelector('[data-act="ok"]').focus();
  });
}
function confirmBox(title, html, okText = "ยืนยัน", danger = false) {
  return modal({ title, html, okText, danger });
}
/** กล่องเลือกหลายทาง (v1.10) — choices = [{ value, label, kind: "primary" | "danger" | "" }] คืน value หรือ false (ยกเลิก/Esc) */
function choiceBox(title, html, choices) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "modal";
    dlg.innerHTML = `
      <div class="modal-head">${esc(title)}</div>
      <div class="modal-body">${html || ""}</div>
      <div class="modal-foot">
        <button type="button" class="btn" data-i="-1">ยกเลิก</button>
        ${choices.map((c, i) => `<button type="button" class="btn ${c.kind === "danger" ? "danger" : c.kind || ""}" data-i="${i}">${esc(c.label)}</button>`).join("")}
      </div>`;
    document.body.appendChild(dlg);
    const close = (val) => { dlg.close(); dlg.remove(); resolve(val); };
    dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(false); });
    dlg.querySelectorAll("button[data-i]").forEach((b) => b.addEventListener("click", () => {
      const i = Number(b.dataset.i);
      close(i < 0 ? false : choices[i].value);
    }));
    dlg.showModal();
    (dlg.querySelector(".btn.primary") || dlg.querySelector("button[data-i]")).focus();
  });
}

// ---------- Combobox: พิมพ์เองหรือเลือกจากรายการ ----------
class Combo {
  /** format: แปลงข้อความที่แสดงในรายการ (ค่าที่เลือกยังเป็นค่าเดิม) เช่น Size → ⌀34.92 */
  constructor(input, getItems, { format } = {}) {
    this.input = input;
    this.getItems = getItems;
    this.format = format || ((n) => n);
    this.activeIndex = -1;
    this.isTextarea = input.tagName === "TEXTAREA";

    const wrap = document.createElement("div");
    wrap.className = "combo";
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    this.toggle = document.createElement("button");
    this.toggle.type = "button";
    this.toggle.className = "combo-toggle";
    this.toggle.tabIndex = -1;
    this.toggle.title = "เลือกจากรายการ";
    this.toggle.textContent = "▼";
    wrap.appendChild(this.toggle);
    this.list = document.createElement("ul");
    this.list.className = "combo-list hidden";
    wrap.appendChild(this.list);
    this.wrap = wrap;

    this.toggle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      if (this.isOpen()) this.close(); else { this.input.focus(); this.open(""); }
    });
    input.addEventListener("input", () => this.open(input.value));
    if (!this.isTextarea) input.addEventListener("focus", () => this.open(""));
    input.addEventListener("blur", () => setTimeout(() => this.close(), 120));
    input.addEventListener("keydown", (e) => this.onKey(e));
    this.list.addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (!li) return;
      e.preventDefault();
      this.pick(this.items[Number(li.dataset.i)]);
    });
  }
  isOpen() { return !this.list.classList.contains("hidden"); }
  open(query) {
    const q = (query || "").trim().toLowerCase();
    const all = this.getItems() || [];
    this.items = (q ? all.filter((n) => n.toLowerCase().includes(q)) : all).slice(0, 200);
    this.activeIndex = -1;
    if (!this.items.length) {
      if (!q) {
        this.list.innerHTML = '<li class="empty">ยังไม่มีรายการ — พิมพ์ใหม่ได้ หรือเพิ่มในหน้าตั้งค่า</li>';
        this.list.classList.remove("hidden");
      } else this.close();
      return;
    }
    if (q && this.items.length === 1 && this.items[0].toLowerCase() === q) { this.close(); return; }
    this.list.innerHTML = this.items.map((n, i) => `<li data-i="${i}">${esc(this.format(n))}</li>`).join("");
    this.list.classList.remove("hidden");
  }
  close() { this.list.classList.add("hidden"); this.activeIndex = -1; }
  highlight(i) {
    const lis = this.list.querySelectorAll("li[data-i]");
    if (!lis.length) return;
    this.activeIndex = (i + lis.length) % lis.length;
    lis.forEach((li, idx) => li.classList.toggle("active", idx === this.activeIndex));
    lis[this.activeIndex].scrollIntoView({ block: "nearest" });
  }
  onKey(e) {
    if (e.key === "ArrowDown" && (!this.isTextarea || this.isOpen() || e.altKey)) {
      e.preventDefault();
      if (!this.isOpen()) this.open(""); else this.highlight(this.activeIndex + 1);
    } else if (e.key === "ArrowUp" && this.isOpen()) {
      e.preventDefault(); this.highlight(this.activeIndex - 1);
    } else if (e.key === "Enter" && this.isOpen() && this.activeIndex >= 0) {
      e.preventDefault(); this.pick(this.items[this.activeIndex]);
    } else if (e.key === "Escape" && this.isOpen()) {
      e.preventDefault(); this.close();
    }
  }
  pick(value) {
    this.input.value = value;
    this.input.dispatchEvent(new Event("input", { bubbles: true }));
    this.input.dispatchEvent(new Event("change", { bubbles: true }));
    this.close();
  }
}

// ---------- Layout ----------
const NAV = [
  ["/", "บันทึกงาน"], ["/report", "รายงาน"], ["/dashboard", "Dashboard"], ["/settings", "ตั้งค่า"],
];
let _settingsCache = null;
async function loadSettings(force = false) {
  if (!_settingsCache || force) _settingsCache = await api("/api/settings");
  return _settingsCache;
}
function renderTopbar() {
  const header = document.querySelector("header.topbar");
  const here = location.pathname.replace(/\/$/, "") || "/";
  header.innerHTML = `
    <a class="brand" href="/" title="${esc("โปรแกรมบันทึกปัญหาเครื่องจักร — กลับหน้าบันทึกงาน")}"><span class="logo" id="lineLogo">T14</span><span class="app-name">บันทึกปัญหาเครื่องจักร</span></a>
    <nav>${NAV.map(([href, label]) => `<a href="${href}" class="${(href === "/" ? here === "/" : here.startsWith(href)) ? "active" : ""}">${label}</a>`).join("")}</nav>
    <div class="spacer"></div>
    <div class="meta" id="todayMeta">วัน${thaiDay(todayIso())}ที่ ${fmtDate(todayIso())}</div>`;
  loadSettings().then((s) => {
    document.getElementById("lineLogo").textContent = s.line_name;
    document.title = document.title.replace("T14", s.line_name);
  }).catch(() => {});
}
document.addEventListener("DOMContentLoaded", renderTopbar);
