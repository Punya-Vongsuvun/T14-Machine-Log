/* หน้ารายงาน (แนวนอน A4) */
"use strict";

const $ = (id) => document.getElementById(id);
const TYPE_FILTER_LABELS = {
  problem: "ปัญหา", problem_sl: "ปัญหา+Stop Line+Cleaning", improve: "การปรับปรุง", stopline: "Stop Line",
  cleaning: "Monday Cleaning", all: "ทั้งหมด",
};
const SHIFT_FILTER_LABELS = { M: "เช้า", N: "ดึก" };
const STATUS_FILTER_LABELS = {
  ...STATUS_LABELS, overdue: "เกินกำหนด",
  pending_ontime: "รอดำเนินการ (ยังไม่เกินกำหนด)", in_progress_ontime: "ระหว่างดำเนินการ (ยังไม่เกินกำหนด)",
  open: "ยังไม่เสร็จ (รอ + ระหว่างดำเนินการ)",
};
const BLANK = "__blank__"; // "ไม่ระบุ" (ลิงก์จากแท่งกราฟ "ไม่ระบุ" ใน Dashboard)
const blankText = (v) => (v === BLANK ? "ไม่ระบุ" : v);
// ตัวกรองที่เป็นปัญหา/Stop Line/Monday Cleaning ล้วน → ไม่มีคอลัมน์ กำหนดเสร็จ / ผู้รับผิดชอบ / สถานะ
const PROBLEM_ONLY = new Set(["problem", "problem_sl", "stopline", "cleaning"]);

// คอลัมน์ของรายการ: [หัวคอลัมน์, ความกว้าง (สัดส่วน), ฟังก์ชันสร้างเซลล์]
function eventColumns(type) {
  const cols = [
    ["เวลาเริ่ม", 4.5, (e) => e.stop_line
      ? `<td class="c num mark" colspan="2">${fmtDate(e.date).slice(0, 5)}–${fmtDate(e.end_date).slice(0, 5)}</td>`
      // v1.9 คิดจากยอดผลิต รายการเก่าไม่มีเวลา — แสดงยอดผลิตแบบจาง (v1.10 รายการที่มีเวลา: ยอดผลิตอยู่ใต้ปัญหา)
      : e.rate_actuals && !e.time_from ? `<td class="mark rate-cell" colspan="2"><span class="rate-note">${esc(rateNote(e))}</span></td>`
      : `<td class="c num mark">${esc(e.time_from)}</td>`],
    ["เวลาสิ้นสุด", 4.5, (e) => e.stop_line || (e.rate_actuals && !e.time_from) ? "" : `<td class="c num">${esc(e.time_to)}</td>`],
    // Stop Line / Monday Cleaning: บันทึกอย่างเดียว — ชั่วโมงสีจาง ไม่รวมในชั่วโมงรวม
    ["ชม.", 3, (e) => `<td class="c num${e.record_only ? " not-counted" : ""}"${e.record_only ? ' title="บันทึกอย่างเดียว ไม่รวมในชั่วโมงรวม"' : ""}>${fmtHours(e.hours)}</td>`],
    ["กะ", 3.5, (e) => `<td class="c">${esc(e.shift_label)}</td>`],
    ["Size", 4, (e) => `<td class="c">${esc(sizeLabel(e.size))}</td>`],
    ["เครื่องจักร", 7.5, (e) => `<td>${e.stop_line ? `<span class="pill stopline">Stop Line</span>${e.machine ? "<br>" + esc(e.machine) : ""}`
      : e.cleaning ? `<span class="pill cleaning">Monday Cleaning</span>${e.machine ? "<br>" + esc(e.machine) : ""}` : esc(e.machine)}</td>`],
    [type === "improve" ? "งานที่ปรับปรุง" : "ปัญหา", 16, (e) => {
      const files = e.attachments.length
        ? ` <span class="clip" title="${esc(e.attachments.map((a) => a.name).join(", "))}">📎${e.attachments.length}</span>` : "";
      const rate = e.rate_actuals && e.time_from ? `<br><span class="rate-note">${esc(rateNote(e))}</span>` : "";
      return `<td class="txt">${esc(e.problem)}${files}${rate}</td>`;
    }],
    [type === "improve" ? "รายละเอียด" : "การแก้ไข", 14, (e) => `<td class="txt">${esc(e.corrective)}</td>`],
  ];
  if (!PROBLEM_ONLY.has(type)) {
    cols.push(
      ["กำหนดเสร็จ", 6, (e) => `<td class="c num">${fmtDate(e.due_date)}</td>`],
      ["ผู้รับผิดชอบ", 7, (e) => `<td>${esc(e.responsible)}</td>`],
      ["สถานะ", 7, (e) => `<td class="c due">${statusPill(e)}</td>`],
    );
  }
  return cols;
}

const DAY_COLUMNS = [["วันที่", 6.5], ["วัน", 5.5], ["เป้าหมาย", 6], ["ผลิตได้", 6], ["ผลต่าง", 5.5]];
const MISSING_TIPS = { target: "ยังไม่บันทึกเป้าหมาย", output: "ยังไม่บันทึกยอดผลิต" };

/** ช่องเป้าหมาย/ผลิตได้: วันหยุดที่ไม่มีค่า = "วันหยุด" สีเทา, วันที่ขาดข้อมูล = "—" สีเหลือง (v1.5 E2) */
function qtyCell(d, field, span) {
  // yc = คอลัมน์ยอดผลิต (เป้าหมาย / ผลิตได้ / ผลต่าง) — ไม่พิมพ์เมื่อเลือกประเภท (v1.10.2)
  if (d[field] !== null) return `<td class="r num day-cell yc"${span}>${fmtInt(d[field])}</td>`;
  if (d.holiday) return `<td class="c day-cell holiday-cell yc"${span}>วันหยุด</td>`;
  if (d.missing === field || d.missing === "both") {
    return `<td class="c day-cell missing-cell yc"${span} title="${MISSING_TIPS[field]}">—</td>`;
  }
  return `<td class="r num day-cell yc"${span}></td>`;
}

function render(r, filters) {
  const cols = eventColumns(filters.type);
  const all = DAY_COLUMNS.concat(cols);
  const total = all.reduce((s, c) => s + c[1], 0);
  const isYield = (i) => i >= 2 && i <= 4;  // DAY_COLUMNS: เป้าหมาย, ผลิตได้, ผลต่าง
  const colgroup = all.map((c, i) => `<col${isYield(i) ? ' class="yc"' : ""} style="width:${(c[1] / total * 100).toFixed(2)}%">`).join("");
  const emptyEvent = `<td class="mark"></td>${"<td></td>".repeat(cols.length - 1)}`;

  const body = r.days.map((d) => {
    const n = Math.max(d.events.length, 1);
    const span = n > 1 ? ` rowspan="${n}"` : "";
    const dayCells = `
      <td class="c num day-cell"${span}>${fmtDate(d.date)}</td>
      <td class="c day-cell"${span}>${d.day_name}${d.holiday && (d.target !== null || d.output !== null) ? '<br><span class="pill holiday">วันหยุด</span>' : ""}</td>
      ${qtyCell(d, "target", span)}
      ${qtyCell(d, "output", span)}
      <td class="r num day-cell yc ${signClass(d.diff)}"${span}>${fmtSigned(d.diff)}</td>`;
    if (!d.events.length) return `<tr class="no-events">${dayCells}${emptyEvent}</tr>`;
    return d.events.map((e, i) =>
      `<tr class="type-${e.stop_line ? "stopline" : e.cleaning ? "cleaning" : e.type}">${i === 0 ? dayCells : ""}${cols.map((c) => c[2](e)).join("")}</tr>`).join("");
  }).join("");

  const t = r.totals;
  const filterText = [
    `ประเภท: ${TYPE_FILTER_LABELS[filters.type]}`,
    filters.machine && `เครื่องจักร: ${blankText(filters.machine)}`,
    filters.size && `Size: ${filters.size === BLANK ? "ไม่ระบุ" : sizeLabel(filters.size)}`,
    filters.shift && `กะ: ${SHIFT_FILTER_LABELS[filters.shift]}`,
    filters.status && `สถานะ: ${STATUS_FILTER_LABELS[filters.status]}`,
    filters.sl === "0" && "ไม่รวม Stop Line / Monday Cleaning",
  ].filter(Boolean).join(" · ");
  const legend = [
    filters.type !== "improve" && filters.type !== "stopline" && '<span class="l-problem">ปัญหา</span>',
    !PROBLEM_ONLY.has(filters.type) && '<span class="l-improve">การปรับปรุง</span>',
    !["problem", "improve", "cleaning"].includes(filters.type) && '<span class="l-stopline">Stop Line</span>',
    !["problem", "improve", "stopline"].includes(filters.type) && '<span class="l-cleaning">Monday Cleaning</span>',
  ].filter(Boolean).join("");
  const stopNote = t.by_type.stop_line
    ? `<span>Stop Line: <b>${t.by_type.stop_line}</b> ครั้ง · ${fmtHours(t.stop_line_hours)} ชม. <span class="muted">(บันทึกอย่างเดียว ไม่รวมในชั่วโมงรวม)</span></span>` : "";
  const cleaningNote = t.cleaning_count
    ? `<span>Monday Cleaning: <b>${t.cleaning_count}</b> ครั้ง · ${fmtHours(t.cleaning_hours)} ชม. <span class="muted">(บันทึกอย่างเดียว ไม่รวมในชั่วโมงรวม)</span></span>` : "";

  // v1.10.1 มีตัวกรอง → ตอนพิมพ์แสดงเฉพาะวันที่มีรายการตรงตัวกรอง (บนจอยังเห็นทุกวัน)
  const filtered = filters.type !== "all" || Boolean(filters.machine || filters.size || filters.shift || filters.status);
  $("sheet").classList.toggle("print-filtered", filtered);
  // v1.10.2 เลือกประเภท (ไม่ใช่ "ทั้งหมด") → ตอนพิมพ์เฉพาะรายการของประเภทนั้น ไม่พิมพ์ยอดผลิต
  $("sheet").classList.toggle("print-typed", filters.type !== "all");
  $("sheet").innerHTML = `
    <div class="sheet-head">
      <div>
        <h1>รายงานบันทึกปัญหาและการปรับปรุงเครื่องจักร — Line ${esc(r.line_name)}</h1>
        <div class="muted">ช่วงวันที่ ${fmtDate(r.from)} ถึง ${fmtDate(r.to)} · ${esc(filterText)}</div>
      </div>
      <div class="muted small" style="text-align:right">
        <div class="legend">${legend}</div>
        พิมพ์เมื่อ ${fmtDate(r.generated_at.slice(0, 10))} ${r.generated_at.slice(11)} น.
      </div>
    </div>
    <table class="report">
      <colgroup>${colgroup}</colgroup>
      <thead><tr>${all.map((c, i) => `<th${isYield(i) ? ' class="yc"' : ""}>${c[0]}</th>`).join("")}</tr></thead>
      <tbody>${body || `<tr><td colspan="${all.length}" class="c" style="padding:20px">ไม่มีข้อมูลในช่วงที่เลือก</td></tr>`}</tbody>
      <tfoot><tr>
        <td colspan="2" class="c">รวม</td>
        <td class="r num yc">${fmtInt(t.target)}</td>
        <td class="r num yc">${fmtInt(t.output)}</td>
        <td class="r num yc ${signClass(t.diff)}">${fmtSigned(t.diff)}</td>
        <td colspan="2"></td>
        <td class="c num" title="ไม่รวม Stop Line / Monday Cleaning">${fmtHours(t.hours)}</td>
        <td colspan="${cols.length - 3}">${t.count} รายการ</td>
      </tr>
      <tr class="complete-row yc">
        <td colspan="2" class="c">เฉพาะ ${t.complete_days} วันที่มีครบ</td>
        <td class="r num">${fmtInt(t.complete_target)}</td>
        <td class="r num">${fmtInt(t.complete_output)}</td>
        <td class="r num ${signClass(t.diff)}">${fmtSigned(t.diff)}</td>
        <td colspan="${cols.length}">ตัวเลขเดียวกับ Dashboard${t.complete_pct === null ? "" : ` · บรรลุเป้า ${t.complete_pct.toFixed(1)}%`}</td>
      </tr></tfoot>
    </table>
    <div class="report-summary">
      <span>ชั่วโมงรวม (ไม่รวม Stop Line / Monday Cleaning): <b>${fmtHours(t.hours)} ชม.</b></span>
      <span>ปัญหา: <b>${t.by_type.problem}</b> ครั้ง</span>
      <span>การปรับปรุง: <b>${t.by_type.improve}</b> ครั้ง</span>
      ${stopNote}
      ${cleaningNote}
      ${t.holiday_days ? `<span class="yc">วันหยุด: <b>${t.holiday_days}</b> วัน</span>` : ""}
      ${t.missing_days ? `<span class="missing-note yc">ยังไม่บันทึกเป้าหมาย/ยอดผลิต: <b>${t.missing_days}</b> วัน</span>` : ""}
      <span class="muted">📎 = จำนวนไฟล์แนบ · Stop Line นับที่วันที่เริ่ม · แถว "รวม" = ผลบวกของคอลัมน์<span class="yc"> · ผลต่างรวมและแถว "เฉพาะวันที่มีครบ" คิดเฉพาะวันที่มีทั้งเป้าหมายและยอดผลิต</span></span>
    </div>`;
}

// sl=0 มาจากลิงก์ Dashboard (กราฟไม่นับ Stop Line) — ล้างได้ด้วยการเปลี่ยนประเภท
const state = { noStopLine: false, shownQs: null };

async function run() {
  const filters = {
    from: $("fFrom").value, to: $("fTo").value, type: $("fType").value,
    machine: $("fMachine").value, size: $("fSize").value, shift: $("fShift").value, status: $("fStatus").value,
  };
  if (state.noStopLine) filters.sl = "0";
  if (!filters.from || !filters.to) { toast("กรุณาเลือกช่วงวันที่", "err"); return; }
  const qs = new URLSearchParams(filters);
  history.replaceState(null, "", `/report?${qs}`);
  try {
    render(await api(`/api/report?${qs}`), filters);
    state.shownQs = qs.toString();
  } catch (err) { toast(err.message, "err"); }
}

/** ส่งออก Excel ของรายงานที่แสดงอยู่ (ตัวกรองเดียวกัน) */
async function exportXlsx() {
  if (!state.shownQs) { toast('กด "แสดงรายงาน" ก่อน', "err"); return; }
  const btn = $("xlsxBtn");
  btn.disabled = true;
  try {
    let res;
    try {
      res = await fetch(`/api/report.xlsx?${state.shownQs}`);
    } catch (_) {
      throw new Error("ติดต่อโปรแกรมไม่ได้ — ตรวจสอบว่าหน้าต่างโปรแกรม (Start.bat) ยังเปิดอยู่");
    }
    if (!res.ok) {
      let msg = `เกิดข้อผิดพลาด (${res.status})`;
      try { const d = await res.json(); if (typeof d.detail === "string") msg = d.detail; } catch (_) { /* ไม่ใช่ JSON */ }
      throw new Error(msg);
    }
    const m = /filename\*=UTF-8''([^;]+)/.exec(res.headers.get("Content-Disposition") || "");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(await res.blob());
    a.download = m ? decodeURIComponent(m[1]) : "T14_report.xlsx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
    toast(`ส่งออก ${a.download} แล้ว`, "ok");
  } catch (err) {
    toast(err.message, "err");
  } finally {
    btn.disabled = false;
  }
}

async function init() {
  const p = new URLSearchParams(location.search);
  const today = todayIso();
  $("fFrom").value = p.get("from") || today.slice(0, 8) + "01";
  $("fTo").value = p.get("to") || today;
  $("fType").value = TYPE_FILTER_LABELS[p.get("type")] ? p.get("type") : "all";
  try {
    const m = await api("/api/master");
    const opt = (n) => `<option value="${esc(n)}">${esc(n)}</option>`;
    const blank = `<option value="${BLANK}">ไม่ระบุ</option>`;
    const withValue = (names, v) => (v && v !== BLANK && !names.includes(v) ? names.concat(v) : names);
    $("fMachine").innerHTML = '<option value="">ทั้งหมด</option>' +
      withValue(m.machine.map((x) => x.name), p.get("machine")).map(opt).join("") + blank;
    $("fSize").innerHTML = '<option value="">ทั้งหมด</option>' +
      withValue(m.size.map((x) => x.name), p.get("size")).map((n) => `<option value="${esc(n)}">${esc(sizeLabel(n))}</option>`).join("") + blank;
    $("fMachine").value = p.get("machine") || "";
    $("fSize").value = p.get("size") || "";
  } catch (err) { toast(err.message, "err"); }
  $("fShift").value = SHIFT_FILTER_LABELS[p.get("shift")] ? p.get("shift") : "";
  $("fStatus").value = STATUS_FILTER_LABELS[p.get("status")] ? p.get("status") : "";
  state.noStopLine = p.get("sl") === "0";
  $("runBtn").addEventListener("click", run);
  $("fType").addEventListener("change", () => { state.noStopLine = false; run(); });
  $("printBtn").addEventListener("click", () => window.print());
  $("xlsxBtn").addEventListener("click", exportXlsx);
  run();
}

document.addEventListener("DOMContentLoaded", init);
