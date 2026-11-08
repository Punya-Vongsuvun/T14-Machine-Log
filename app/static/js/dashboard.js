/* หน้า Dashboard */
"use strict";

const $ = (id) => document.getElementById(id);
const TYPE_TEXT = { problem: "ปัญหา", improve: "การปรับปรุง", all: "ทุกประเภท" };
// สีแท่งตามประเภท [ปกติ, ชี้เมาส์] — v1.8 อ่อนลงจากสีกรอบหน้าบันทึกงาน (ชี้เมาส์ = สีเดิม)
const TYPE_COLORS = { problem: ["#e6774f", "#d9572f"], improve: ["#4a82d4", "#2160c4"] };
/** ผสมสีกับสีขาว t (0 = สีเดิม, 1 = ขาว) — ไล่โทนในสีเดียวกัน */
function tint(hex, t) {
  const n = parseInt(hex.slice(1), 16);
  const mix = (c) => Math.round(c + (255 - c) * t);
  return `#${[n >> 16, (n >> 8) & 255, n & 255].map((c) => mix(c).toString(16).padStart(2, "0")).join("")}`;
}
/** v1.9: Size / กะ แต่ละหมวดใช้โทนต่างกันในสีเดียว (เข้ม → อ่อน) — คู่เทียบปัญหา/ปรับปรุงของหมวดเดียวกันใช้ระดับเดียวกัน
 *  ระดับผูกกับหมวด (ไม่เปลี่ยนตามการเรียง): กะดึก = เข้ม / กะเช้า = อ่อน, Size ตามลำดับในรายการ Size */
function categoryLevel(key, g) {
  if (key === "shift") return [g.key === "N" ? 0 : 1, 2];
  if (key !== "size") return [null, 1];
  // Size ที่มีในช่วงนี้ เรียงตามรายการ Size (ไม่ระบุ = อ่อนสุด)
  const keys = lastData.charts.size.map((x) => x.key || "");
  const rank = (k) => (k === "" ? 1e9 : sizeOrder.includes(k) ? sizeOrder.indexOf(k) : 1e6);
  const order = [...keys].sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  return [order.indexOf(g.key || ""), order.length];
}
let sizeOrder = [];  // ลำดับ Size จาก Master (โหลดตอนเปิดหน้า)
const SHADE_MAX = 0.5;  // อ่อนสุด = ผสมขาว 50%
function barColor(key, type, g, hover = false) {
  const base = TYPE_COLORS[type][hover ? 1 : 0];
  const [lv, levels] = categoryLevel(key, g);
  return lv === null || lv < 0 || levels < 2 ? base : tint(base, (lv / (levels - 1)) * SHADE_MAX);
}
const PART_TYPES = ["problem", "improve"];
const PART_NAMES = { problem: "ปัญหา", improve: "การปรับปรุง" };
// กราฟงานปรับปรุง: เสร็จแล้ว = เขียว, ยังไม่เสร็จ 3 กลุ่ม = ส้มไล่โทน อ่อน → เข้ม
const IMPROVE_COLORS = { done: "#3f9d64", pending_ontime: "#f7c48e", in_progress_ontime: "#ef9a4f", overdue: "#d2661c" };
const INK = "#1b2232";
const INK_2 = "#566074";
const INK_3 = "#a3abba";
const GRID = "#e9edf3";
const CHARTS = {
  machine: { canvas: "cMachine" },  // v1.9: ทุกเครื่องตามลำดับใน Master + เรียง ตามเครื่อง / ชม. / ครั้ง
  size: { canvas: "cSize" },
  shift: { canvas: "cShift" },  // เฉพาะปัญหาเสมอ (v1.8)
};
const PREFS_KEY = "t14.dashboard.prefs";
const charts = {};
let lastData = null;

// ---------- ค่าที่ผู้ใช้เลือก (จำไว้ในเครื่อง) ----------
const PREFS_VERSION = 19;  // v1.9: กราฟเครื่องจักรเริ่มที่ "ตามเครื่อง" (ไม่ใช้ค่าเรียงที่จำไว้จากรุ่นก่อน)
function loadPrefs() {
  const base = { machine: { sort: "machine" }, size: { sort: "hours" }, shift: { sort: "hours" }, pct: true, v: PREFS_VERSION };
  try {
    const saved = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}");
    for (const k of ["size", "shift"]) if (saved[k]?.sort) base[k].sort = saved[k].sort;
    if (saved.v === PREFS_VERSION && saved.machine?.sort) base.machine.sort = saved.machine.sort;
    base.pct = saved.pct !== false;
  } catch (_) { /* ใช้ค่าเริ่มต้น */ }
  return base;
}
const prefs = loadPrefs();
function savePrefs() { try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch (_) { /* ไม่เป็นไร */ } }
/** ค่าที่ใช้วัดความสูงแท่งและ % — เรียง "ตามเครื่อง" ใช้ชั่วโมง */
const metric = (key) => (prefs[key].sort === "count" ? "count" : "hours");

// ---------- % ต่อท้าย (v1.6 — เปิด/ปิดได้) ----------
/** % ปัดเป็นจำนวนเต็ม ("<1%" ถ้าน้อยกว่า 1) — "" ถ้าปิด % หรือไม่มีตัวหาร */
function pctText(value, total) {
  if (!prefs.pct || !total || value === null || value === undefined) return "";
  const p = value / total * 100;
  return p > 0 && p < 1 ? "<1%" : `${Math.round(p)}%`;
}
/** ผลรวมของกราฟตามปุ่มเรียง ชม./ครั้ง — type = เฉพาะประเภทนั้น (% ของแต่ละแท่งคิดแยกตามประเภท) */
function chartTotal(key, type = null) {
  const sort = metric(key);
  return lastData.charts[key].reduce((sum, g) => sum + (type ? g.parts?.[type]?.[sort] || 0 : g[sort]), 0);
}
/** % จำนวนเต็มของหลายกลุ่มที่รวมกันได้ 100 พอดี (ปัดแบบเศษเหลือมากสุด) — values รวมกันต้องเท่ากับ total */
function pctSplit(values, total) {
  if (!total) return values.map(() => null);
  const raw = values.map((v) => v / total * 100);
  const out = raw.map(Math.floor);
  const left = 100 - out.reduce((a, b) => a + b, 0);  // จำนวนกลุ่มที่ต้องปัดขึ้น (คำนวณครั้งเดียว)
  raw.map((r, i) => [r - Math.floor(r), i]).sort((a, b) => b[0] - a[0]).slice(0, left).forEach(([, i]) => { out[i] += 1; });
  return out;
}
/** เหมือน pctSplit เป็นข้อความ "25%" — "" ถ้าปิด % หรือไม่มีตัวหาร */
function pctParts(values, total) {
  if (!prefs.pct || !total) return values.map(() => "");
  return pctSplit(values, total).map((v) => `${v}%`);
}
const withPct = (text, pct) => (pct ? `${text} · ${pct}` : text);
const measureCtx = document.createElement("canvas").getContext("2d");

/** เว้นระยะใต้ legend ให้ป้ายบนหัวแท่งที่สูงสุดไม่ทับ legend (v1.9) */
const legendGap = {
  id: "legendGap",
  beforeLayout(chart) {
    const lg = chart.legend;
    if (!lg || lg.$gapped) return;
    const fit = lg.fit;
    lg.fit = function () { fit.call(this); if (this.options.display) this.height += prefs.pct ? 28 : 16; };
    lg.$gapped = true;
  },
};

/** ป้ายบนหัวแท่ง (v1.8): บรรทัดบน = ชม. (ครั้ง) ตัวหนา, บรรทัดล่าง = % ตัวเล็กกว่า ไม่หนา
 *  ย่อตัวอักษรเมื่อป้ายกว้างเกินช่องของแท่ง (ไม่ให้ทับแท่งข้าง ๆ) */
const topLabels = {
  id: "topLabels",
  afterDatasetsDraw(chart) {
    const { ctx } = chart;
    ctx.save();
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    chart.$overflow = [];  // ป้ายที่ย่อสุดแล้วยังกว้างเกินช่อง (ใช้ตรวจในชุดทดสอบ)
    chart.data.datasets.forEach((ds, di) => {
      chart.getDatasetMeta(di).data.forEach((bar, i) => {
        const [main, pct, zero] = ds.$tops?.[i] || [];
        if (!main) return;
        if (zero) {  // v1.9: ไม่มีข้อมูล = "0" สีเทา ตัวเล็ก ไม่มี %
          ctx.font = `400 ${chart.$compact ? 9 : 10.5}px Sarabun, Tahoma, sans-serif`;
          ctx.fillStyle = INK_3;
          ctx.fillText(main, bar.x, bar.y - 3);
          return;
        }
        const slot = bar.width / BAR.barPercentage;
        let size = chart.$compact ? 10.5 : 12;
        const font = (sz, w) => `${w} ${sz}px Sarabun, Tahoma, sans-serif`;
        measureCtx.font = font(size, 600);
        while (size > 7.5 && measureCtx.measureText(main).width > slot - 2) measureCtx.font = font(size -= 0.5, 600);
        if (measureCtx.measureText(main).width > slot - 2) chart.$overflow.push(main);
        const pctSize = size - 1.5;
        let y = bar.y - 3;
        if (pct) {
          ctx.font = font(pctSize, 400);
          ctx.fillStyle = INK_2;
          ctx.fillText(pct, bar.x, y);
          y -= pctSize + 2;
        }
        ctx.font = font(size, 600);
        ctx.fillStyle = INK;
        ctx.fillText(main, bar.x, y);
      });
    });
    ctx.restore();
  },
};

/** ชื่อใต้แท่งที่ยาวเกิน 12 ตัวอักษร แบ่ง 2 บรรทัดตรงช่องว่าง (ไม่ให้ชื่อทับกัน) */
function wrapLabel(label) {
  if (label.length <= 12 || !label.includes(" ")) return label;
  const words = label.split(" ");
  const half = Math.ceil(words.length / 2);
  return [words.slice(0, half).join(" "), words.slice(half).join(" ")];
}

function presetRange(preset) {
  const now = new Date();
  const today = isoDate(now);
  const y = now.getFullYear(), m = now.getMonth();
  switch (preset) {
    case "lastMonth": return [isoDate(new Date(y, m - 1, 1)), isoDate(new Date(y, m, 0))];
    case "last7": return [addDays(today, -6), today];
    case "last30": return [addDays(today, -29), today];
    case "thisYear": return [`${y}-01-01`, today];
    default: return [isoDate(new Date(y, m, 1)), today];
  }
}

// ---------- กล่องตัวเลข ----------
// สีแถบหน้ากล่อง: good = เขียว (ดี), bad = ส้ม (ไม่ดี), accent = ฟ้า (ค่าตั้ง), "" = กลาง
function kpiCard({ label, value, sub = "", tone = "", cmp = "", small = false, link = "" }) {
  const attrs = link ? ` data-link="${link}" role="button" tabindex="0" title="คลิกเพื่อดูข้อมูล"` : "";
  return `<div class="card kpi ${tone}${link ? " link" : ""}"${attrs}>
    <div class="k-label">${label}</div>
    <div class="k-value num ${small ? "sm" : ""}" title="${esc(String(value).replace(/<[^>]+>/g, ""))}">${value}</div>
    <div class="k-sub">${sub}</div>
    ${cmp ? `<div class="k-cmp">${cmp}</div>` : ""}</div>`;
}

/** บรรทัดเปรียบเทียบ: better = "up" (มากดี) | "down" (น้อยดี) | null (ไม่ตัดสิน) */
function cmpLine(cur, prev, { better = "up", fmt = fmtInt, mode = "pct", unit = "" } = {}) {
  if (!lastData.compare || cur === null || cur === undefined) return "";
  if (prev === null || prev === undefined) return `<span class="muted">${esc(lastData.compare.label)}: ไม่มีข้อมูล</span>`;
  const d = cur - prev;
  const prevText = `${fmt(prev)}${unit}`;
  if (Math.abs(d) < 1e-9) return `<span class="flat">● เท่าเดิม</span> <span class="muted">(${prevText})</span>`;
  const good = better === null ? null : (better === "up" ? d > 0 : d < 0);
  const cls = good === null ? "flat" : good ? "up-good" : "up-bad";
  const arrow = d > 0 ? "▲" : "▼";
  let change;
  if (mode === "abs") change = `${d > 0 ? "+" : "−"}${fmtInt(Math.abs(d))}${unit}`;
  else if (mode === "pt") change = `${d > 0 ? "+" : "−"}${Math.abs(d).toFixed(1)} จุด`;
  else change = prev ? `${d > 0 ? "+" : "−"}${(Math.abs(d) / Math.abs(prev) * 100).toFixed(1)}%` : `${d > 0 ? "+" : "−"}${fmt(Math.abs(d))}${unit}`;
  return `<span class="${cls}">${arrow} ${change}</span> <span class="muted">(${prevText})</span>`;
}

/** −5.2% (ทศนิยม 1 ตำแหน่ง เหมือน % บรรลุเป้า) */
function fmtSignedPct(v) { return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toFixed(1)}%`; }

/** โทนสีจากการเปรียบเทียบ (ไม่มีช่วงเปรียบเทียบ = กลาง) */
function cmpTone(cur, prev, better) {
  if (!lastData.compare || prev === null || prev === undefined || cur === prev) return "";
  return (better === "up" ? cur > prev : cur < prev) ? "good" : "bad";
}

/** ข้อความย่อยกล่องเป้าหมาย: จำนวนวันที่ใช้คิด + วันหยุด + วันที่ขาดข้อมูล (v1.5 E2-5) */
function daysNote(k) {
  const parts = [`คิดจาก ${k.days_complete} วัน`];
  if (k.holiday_days) parts.push(`วันหยุด ${k.holiday_days} วัน`);
  if (k.missing_days) parts.push(`ขาดข้อมูล ${k.missing_days} วัน`);
  const tip = "คิดจากวันที่มีทั้งเป้าหมายและยอดผลิต · ขาดข้อมูล = วันที่ผ่านมาแล้วที่ยังไม่บันทึกเป้าหมาย/ยอดผลิต (ไม่นับวันหยุด)";
  // ตัดบรรทัดได้เฉพาะระหว่างส่วน (ตอนพิมพ์กล่องแคบ)
  return `<span title="${tip}">${parts.map((t) => `<span class="nowrap">${t}</span>`).join(" · ")}</span>`;
}

function renderKpis(d) {
  const k = d.kpis;
  const c = d.compare ? d.compare.kpis : {};
  const pct = k.achievement_pct;
  const top = k.top_machine;
  const hasTarget = k.target > 0;
  const fmtH = (h) => fmtHours(h);
  // งานปรับปรุง 4 กลุ่ม (ไม่นับซ้อน) — ตัวเลขชุดเดียวกับกราฟงานปรับปรุง
  const imp = Object.fromEntries(d.charts.improve.map((g) => [g.key, g.count]));
  const split = pctSplit(d.charts.improve.map((g) => g.count), k.improve_count);
  const cards = [
    kpiCard({ link: "report", label: "เป้าหมายรวม", value: fmtInt(k.target) || "0", sub: daysNote(k),
      tone: "accent", cmp: cmpLine(k.target, c.target, { better: null }) }),
    kpiCard({ link: "report", label: "ผลิตได้รวม", value: fmtInt(k.output) || "0", sub: `คิดจาก ${k.days_complete} วัน`,
      tone: hasTarget ? (k.output >= k.target ? "good" : "bad") : "", cmp: cmpLine(k.output, c.output) }),
    kpiCard({ link: "report", label: "ผลต่างรวม", value: `<span class="${signClass(k.diff)}">${fmtSigned(k.diff) || "0"}</span>`,
      sub: prefs.pct && hasTarget ? `ผลิตได้ − เป้าหมาย · ${fmtSignedPct(k.diff / k.target * 100)} ของเป้า` : "ผลิตได้ − เป้าหมาย",
      tone: hasTarget ? (k.diff >= 0 ? "good" : "bad") : "", cmp: cmpLine(k.diff, c.diff, { mode: "abs", fmt: (v) => fmtSigned(v) || "0" }) }),
    kpiCard({ link: "report", label: "% บรรลุเป้า", value: pct === null ? "—" : `${pct.toFixed(1)}%`,
      sub: pct === null ? "ยังไม่มีข้อมูลเป้าหมาย" : pct >= 100 ? "✓ ถึงเป้า" : "▼ ต่ำกว่าเป้า",
      tone: pct === null ? "" : pct >= 100 ? "good" : "bad",
      cmp: cmpLine(pct, c.achievement_pct, { mode: "pt", fmt: (v) => `${v.toFixed(1)}%` }) }),
    kpiCard({ link: "report", label: "ยอดผลิตเฉลี่ย / วัน", value: k.avg_output === null ? "—" : fmtInt(k.avg_output),
      sub: k.avg_target === null ? `จาก ${k.days_output} วันที่บันทึกยอดผลิต` : `เป้าเฉลี่ย ${fmtInt(k.avg_target)} / วัน`,
      tone: k.avg_output === null || k.avg_target === null ? "" : k.avg_output >= k.avg_target ? "good" : "bad",
      cmp: cmpLine(k.avg_output, c.avg_output) }),
    kpiCard({ link: "loss", label: "ชั่วโมงสูญเสียรวม", value: `${fmtHours(k.loss_hours)} <span class="small muted">ชม.</span>`,
      sub: `${k.loss_count} ครั้ง · เฉพาะปัญหาเครื่องจักร`,
      tone: cmpTone(k.loss_hours, c.loss_hours, "down"), cmp: cmpLine(k.loss_hours, c.loss_hours, { better: "down", fmt: fmtH, unit: " ชม." }) }),
    kpiCard({ link: "top", label: "เครื่องจักรที่ใช้เวลามากที่สุด", value: top ? esc(top.label) : "—",
      sub: top ? withPct(hoursCount(top.hours, top.count), pctText(top.hours, k.hours) && `${pctText(top.hours, k.hours)} ของทั้งหมด`) : "ไม่มีข้อมูล",
      tone: top ? "bad" : "", cmp: d.compare ? `<span class="muted">${esc(d.compare.label)}: ${c.top_machine ? `${esc(c.top_machine.label)} ${hoursCount(c.top_machine.hours, c.top_machine.count)}` : "ไม่มีข้อมูล"}</span>` : "" }),
    kpiCard({ link: "all", label: "ปัญหา / การปรับปรุง", value: `${k.by_type.problem} / ${k.by_type.improve}`,
      // บันทึกอย่างเดียว (ไม่นับในกราฟ/ชั่วโมง): Stop Line + Monday Cleaning (v1.10)
      sub: k.cleaning_count
        ? `<span title="บันทึกอย่างเดียว ไม่นับในกราฟ/ชั่วโมง">ครั้ง · Stop Line ${k.by_type.stop_line} · Cleaning ${k.cleaning_count} (บันทึกอย่างเดียว)</span>`
        : `ครั้ง · Stop Line ${k.by_type.stop_line} ครั้ง (บันทึกอย่างเดียว)`,
      tone: cmpTone(k.by_type.problem, c.by_type?.problem, "down"),
      cmp: d.compare ? `ปัญหา ${cmpLine(k.by_type.problem, c.by_type?.problem, { better: "down", unit: " ครั้ง" })}` : "" }),
    kpiCard({ link: "done", label: "งานที่ปรับปรุงแล้วเสร็จ", value: `${k.done_count} <span class="small muted">งาน</span>`,
      sub: k.improve_count ? `จาก ${k.improve_count} งาน (${split[0]}%)` : "ยังไม่มีงานปรับปรุง",
      tone: "good", cmp: cmpLine(k.done_count, c.done_count, { unit: " งาน" }) }),
    kpiCard({ link: "open", label: "งานปรับปรุงที่ยังไม่เสร็จ", value: `${k.open_count} / <span class="${k.overdue_count ? "neg" : ""}">${k.overdue_count}</span>` +
        // % ของงานปรับปรุงทั้งหมด เหมือนกราฟ (เสร็จ % + ยังไม่เสร็จ % = 100%)
        (prefs.pct && k.improve_count ? ` <span class="small muted">(${100 - split[0]}% / ${split[3]}%)</span>` : ""),
      // รอ / ระหว่าง = ยังไม่เกินกำหนด (ตรงกับแท่งในกราฟงานปรับปรุง)
      sub: `<span title="รอ / ระหว่าง = ยังไม่เกินกำหนด (ตรงกับกราฟงานปรับปรุง)">ยังไม่เสร็จ / เกินกำหนด · รอ ${imp.pending_ontime} · ระหว่าง ${imp.in_progress_ontime}</span>`,
      tone: k.open_count ? "bad" : "good", cmp: cmpLine(k.open_count, c.open_count, { better: "down", unit: " งาน" }) }),
  ];
  $("kpis").innerHTML = `<div class="kpi-grid ten">${cards.join("")}</div>`;
}

/** คลิกกล่องตัวเลข → ข้อมูลที่อยู่เบื้องหลังตัวเลขนั้น (v1.9) — จำนวนรายการเท่ากับตัวเลขในกล่อง */
function openKpi(link) {
  const k = lastData.kpis;
  switch (link) {
    case "report":  // กล่องยอดผลิต → หน้ารายงาน (ตารางยอดผลิตรายวัน) ช่วงเดียวกัน
      location.href = `/report?${new URLSearchParams({ from: lastData.from, to: lastData.to, type: "all" })}`;
      return;
    case "loss":
      return openList({ head: "ชั่วโมงสูญเสียรวม", scope: "เฉพาะปัญหาเครื่องจักร (ไม่รวม Stop Line / Monday Cleaning)", params: { type: "problem", sl: "0" } });
    case "top":
      if (!k.top_machine) return;
      return openList({ head: `เครื่องจักรที่ใช้เวลามากที่สุด: ${k.top_machine.label}`, scope: TYPE_TEXT[lastData.type],
        params: { type: lastData.type, sl: "0", machine: k.top_machine.key || BLANK } });
    case "all":
      return openList({ head: "ปัญหา / การปรับปรุง", scope: "ทุกประเภท (รวม Stop Line / Monday Cleaning)", params: { type: "all" } });
    case "done":
      return openList({ head: "งานที่ปรับปรุงแล้วเสร็จ", scope: "งานปรับปรุง", params: { type: "improve", status: "done" }, jobs: true });
    case "open":
      return openList({ head: "งานปรับปรุงที่ยังไม่เสร็จ", scope: "งานปรับปรุง", params: { type: "improve", status: "open" }, jobs: true });
    default:
  }
}

// ---------- กราฟ ----------
// แท่งตั้ง: ปัญหา / การปรับปรุง วางคู่กัน (ไม่ซ้อน)
const BAR = { borderRadius: 3, borderSkipped: "start", categoryPercentage: 0.8, barPercentage: 0.9, maxBarThickness: 46 };
// พิมพ์ A4: กราฟเครื่องจักรเต็มความกว้าง ใส่ได้ไม่เกิน 15 เครื่อง — เกินนี้ 14 อันดับแรก + "อื่น ๆ"
const PRINT_MAX_GROUPS = 15;

/** แท่ง "อื่น ๆ" = ผลรวมของเครื่องที่เหลือ (ใช้ตอนพิมพ์เท่านั้น) */
function groupOthers(rest) {
  const sumOf = (f) => rest.reduce((a, g) => a + f(g), 0);
  return {
    key: null, other: true, label: `อื่น ๆ (${rest.length} เครื่อง)`,
    hours: sumOf((g) => g.hours), count: sumOf((g) => g.count),
    parts: Object.fromEntries(PART_TYPES.map((t) => [t, {
      hours: sumOf((g) => g.parts?.[t]?.hours || 0), count: sumOf((g) => g.parts?.[t]?.count || 0) }])),
  };
}

function prepare(key, items, forPrint = false) {
  const sort = prefs[key].sort;
  let list = [...items];
  if (sort !== "machine") {  // "machine" = ลำดับเครื่องใน Master (Server ส่งมาเรียงแล้ว)
    const other = sort === "hours" ? "count" : "hours";
    list.sort((a, b) => b[sort] - a[sort] || b[other] - a[other] || a.label.localeCompare(b.label));
  }
  const total = list.length;
  let grouped = 0;
  if (forPrint && key === "machine" && list.length > PRINT_MAX_GROUPS) {
    const keep = PRINT_MAX_GROUPS - 1;
    grouped = list.length - keep;
    list = [...list.slice(0, keep), groupOthers(list.slice(keep))];
  }
  return { list, total, grouped };
}

/** ประเภทที่แสดงในกราฟ: กะ = ปัญหาเสมอ, "ทั้งหมด" = ปัญหา + การปรับปรุง วางคู่กัน */
const chartTypes = (key) => (key === "shift" ? ["problem"] : lastData.type === "all" ? PART_TYPES : [lastData.type]);

function barOptions({ forPrint, yTitle, onClick, legend, tooltip }) {
  return {
    responsive: !forPrint,  // ตอนพิมพ์กำหนดขนาดตามกระดาษเอง
    maintainAspectRatio: false,
    animation: forPrint ? false : { duration: 250 },  // ตอนพิมพ์ต้องวาดเสร็จทันที
    // พื้นที่ป้ายบนหัวแท่ง: มี legend → เว้นระหว่าง legend กับกราฟ (legendGap) แทนด้านบนสุด
    layout: { padding: { top: legend ? 4 : prefs.pct ? 30 : 18 } },
    onClick,
    onHover: (evt, els) => { evt.native.target.style.cursor = els.length ? "pointer" : "default"; },
    plugins: {
      legend: legend
        ? { display: true, position: "top", align: "end", labels: { boxWidth: forPrint ? 9 : 12, boxHeight: forPrint ? 9 : 12,
            padding: forPrint ? 6 : 10, color: INK_2, font: { family: "Sarabun", size: forPrint ? 10 : 12 } } }
        : { display: false },
      tooltip,
    },
    scales: {
      x: { grid: { display: false }, border: { color: "#cdd3df" },
        ticks: { color: INK, autoSkip: false, maxRotation: 0, font: { family: "Sarabun", size: forPrint ? 11 : 13, weight: "600" } } },
      y: { beginAtZero: true, grace: "8%",
        title: { display: true, text: yTitle, color: INK_2, font: { family: "Sarabun", size: forPrint ? 10 : 12 } },
        // v1.9: ไม่เกิน 4 เส้น เส้นจาง (ค่าจริงอยู่บนหัวแท่งแล้ว)
        ticks: { color: INK_3, precision: 0, maxTicksLimit: 4, font: { family: "Sarabun", size: forPrint ? 9 : 10 } },
        grid: { color: "#f0f2f6" }, border: { display: false } },
    },
  };
}

function drawChart(key, forPrint = false) {
  const p = { sort: metric(key) };
  const { list, grouped } = prepare(key, lastData.charts[key], forPrint);
  const data = list.length ? list : [{ label: "ไม่มีข้อมูล", hours: 0, count: 0, parts: {} }];
  const types = chartTypes(key);
  const card = document.querySelector(`[data-chart="${key}"]`);
  const sortText = { machine: "เรียงตามเครื่อง", hours: "เรียงตาม ชม.", count: "เรียงตาม ครั้ง" }[prefs[key].sort];
  const scope = key === "shift" ? "เฉพาะปัญหา · " : "";
  card.querySelector("[data-note]").textContent = `· ${scope}` + (grouped ? `พิมพ์ ${list.length - 1} รายการแรก + อื่น ๆ · ` : "") + sortText;

  const labelOf = (g) => (key === "size" && g.key ? sizeLabel(g.label) : g.label);
  // % ของแต่ละแท่ง = เทียบกับผลรวมของประเภทนั้นเอง (v1.8)
  const totals = Object.fromEntries(types.map((t) => [t, chartTotal(key, t)]));
  const datasets = types.map((t) => ({
    ...BAR, label: PART_NAMES[t], $type: t,
    data: data.map((g) => g.parts?.[t]?.[p.sort] || 0),
    backgroundColor: data.map((g) => barColor(key, t, g)),
    hoverBackgroundColor: data.map((g) => barColor(key, t, g, true)),
    $tops: data.map((g) => {
      const v = g.parts?.[t];
      if (!list.length) return null;
      return v && v.count ? [`${fmtHours(v.hours)} (${v.count})`, pctText(v[p.sort], totals[t])] : ["0", "", true];
    }),
  }));

  if (charts[key]) charts[key].destroy();
  const chart = new Chart($(CHARTS[key].canvas), {
    type: "bar",
    data: { labels: data.map((g) => wrapLabel(labelOf(g))), datasets },
    options: barOptions({
      forPrint,
      yTitle: p.sort === "hours" ? "ชั่วโมง" : "จำนวนครั้ง",
      legend: types.length > 1,
      onClick: (_evt, els) => {
        if (!els.length || !list[els[0].index] || list[els[0].index].other) return;
        const ds = datasets[els[0].datasetIndex];
        if (!list[els[0].index].parts?.[ds.$type]?.count) return;  // แท่ง 0
        openDrill(key, list[els[0].index], ds.$type, ds.$tops[els[0].index]?.[1] || "");
      },
      tooltip: { callbacks: {
        label: (c) => {
          const t = datasets[c.datasetIndex].$type;
          const v = data[c.dataIndex].parts?.[t] || { hours: 0, count: 0 };
          const pct = pctText(v[p.sort], totals[t]);
          return `${PART_NAMES[t]}: ${hoursCount(v.hours, v.count)}${pct ? ` · ${pct} ของ${PART_NAMES[t]}ทั้งหมด` : ""}`;
        },
        footer: () => (list.length ? "คลิกเพื่อดูรายการ" : ""),
      } },
    }),
    plugins: [topLabels, legendGap],
  });
  chart.$compact = forPrint;
  charts[key] = chart;
}

/** กราฟงานปรับปรุง: เสร็จแล้ว / รอดำเนินการ / ระหว่างดำเนินการ / เกินกำหนด — ไม่นับซ้อน รวม 4 แท่ง = 100% */
function drawImprove(forPrint = false) {
  const items = lastData.charts.improve;
  const total = lastData.kpis.improve_count;
  const pcts = pctParts(items.map((g) => g.count), total);
  document.querySelector('[data-chart="improve"] [data-note]').textContent =
    total ? `· งานปรับปรุงทั้งหมด ${total} งาน${prefs.pct ? " (รวม 4 แท่ง = 100%)" : ""}` : "· ยังไม่มีงานปรับปรุง";
  if (charts.improve) charts.improve.destroy();
  const chart = new Chart($("cImprove"), {
    type: "bar",
    data: {
      labels: items.map((g) => (g.key === "in_progress_ontime" ? ["ระหว่าง", "ดำเนินการ"] : g.label)),
      datasets: [{
        ...BAR, data: items.map((g) => g.count), backgroundColor: items.map((g) => IMPROVE_COLORS[g.key]),
        $tops: items.map((g, i) => [`${g.count} งาน`, pcts[i]]),
      }],
    },
    options: barOptions({
      forPrint, yTitle: "จำนวนงาน", legend: false,
      onClick: (_evt, els) => { if (els.length) openDrill("improve", items[els[0].index], null, pcts[els[0].index]); },
      tooltip: { callbacks: {
        label: (c) => withPct(`${items[c.dataIndex].count} งาน`, pcts[c.dataIndex]) +
          (items[c.dataIndex].key.endsWith("_ontime") ? " (ยังไม่เกินกำหนด)" : ""),
        footer: () => "คลิกเพื่อดูรายการ",
      } },
    }),
    plugins: [topLabels, legendGap],
  });
  chart.$compact = forPrint;
  charts.improve = chart;
}

// ---------- คลิกแท่งกราฟ → หน้าต่างรายการ (ดูอย่างเดียว) ----------
const CHART_NAMES = { machine: "เครื่องจักร", size: "Size", shift: "กะ", improve: "งานปรับปรุง" };
const BLANK = "__blank__";

/** ตัวกรองรายงานที่ตรงกับแท่งกราฟ — ต้องให้จำนวนรายการเท่ากับตัวเลขบนแท่ง */
function drillParams(chartKey, bar, part) {
  const params = { from: lastData.from, to: lastData.to };
  if (chartKey === "improve") return { ...params, type: "improve", status: bar.key };
  // แท่งแต่ละสี = ประเภทนั้น (กะ = ปัญหาเสมอ)
  return { ...params, type: part, sl: "0", [chartKey]: bar.key || BLANK };
}

/** pct = % บนแท่งที่คลิก (แสดงในหน้าต่างให้ตรงกับแท่ง) */
function openDrill(chartKey, bar, part = null, pct = "") {
  const barLabel = chartKey === "size" && bar.key ? sizeLabel(bar.label) : bar.label;
  return openList({
    head: `${CHART_NAMES[chartKey]}: ${barLabel}`,
    scope: chartKey === "improve" ? "งานปรับปรุงทุกประเภทเครื่อง" : TYPE_TEXT[part],
    params: drillParams(chartKey, bar, part), jobs: chartKey === "improve",
    pctText: pct ? `${pct} ของ${chartKey === "improve" ? "งานปรับปรุงทั้งหมด" : `${PART_NAMES[part]}ทั้งหมด`}` : "",
  });
}

/** หน้าต่างรายการ (ดูอย่างเดียว) — ใช้ทั้งคลิกแท่งกราฟและคลิกกล่องตัวเลข (v1.9) */
async function openList({ head, scope, params, jobs = false, pctText: pctNote = "" }) {
  params = { from: lastData.from, to: lastData.to, ...params };
  const qs = new URLSearchParams(params);
  let events;
  try {
    const r = await api(`/api/report?${qs}`);
    events = r.days.flatMap((d) => d.events.map((e) => ({ ...e, day_name: d.day_name })));
  } catch (err) { toast(err.message, "err"); return; }

  const hasImprove = events.some((e) => e.type === "improve");
  // ชั่วโมงรวมไม่นับ Stop Line / Monday Cleaning (เหมือนทุกที่)
  const hours = Math.round(events.filter((e) => !e.record_only).reduce((s, e) => s + e.hours, 0) * 100) / 100;
  const summary = (jobs ? `${events.length} งาน` : `${events.length} รายการ · ${fmtHours(hours)} ชม.`) + (pctNote ? ` · ${pctNote}` : "");
  const today = todayIso();
  const rows = events.map((e) => `<tr>
      <td class="num" style="white-space:nowrap">${fmtDate(e.date)}<br><span class="small muted">${e.day_name}</span></td>
      <td class="c num" style="white-space:nowrap">${eventTimeText(e)}</td>
      <td class="c num${e.record_only ? " not-counted" : ""}">${fmtHours(e.hours)}</td>
      <td class="c">${esc(e.shift_label)}</td>
      <td style="white-space:nowrap">${esc(sizeLabel(e.size))}</td>
      <td>${esc(e.machine)}</td>
      <td><span class="pill ${e.stop_line ? "stopline" : e.cleaning ? "cleaning" : e.type}">${esc(e.type_label)}</span></td>
      <td class="wrap">${esc(e.problem)}</td>
      <td class="wrap">${esc(e.corrective)}</td>
      <td>${attachLinks(e.attachments)}</td>
      ${hasImprove ? `<td class="num">${fmtDate(e.due_date)}</td><td>${esc(e.responsible)}</td><td>${statusPill(e, today)}</td>` : ""}
    </tr>`).join("");

  const dlg = document.createElement("dialog");
  dlg.className = "modal wide";
  dlg.innerHTML = `
    <div class="modal-head">${esc(head)}
      <span class="muted small" style="font-weight:400"> · ${esc(scope)} · ${fmtDate(lastData.from)} – ${fmtDate(lastData.to)} · ${summary}</span></div>
    <div class="modal-body"><div class="table-wrap"><table class="data">
      <thead><tr><th>วันที่</th><th class="c">เวลา</th><th class="c">ชม.</th><th class="c">กะ</th><th>Size</th><th>เครื่องจักร</th>
        <th>ประเภท</th><th>ปัญหา / งานที่ปรับปรุง</th><th>การแก้ไข / รายละเอียด</th><th>ไฟล์แนบ</th>
        ${hasImprove ? "<th>กำหนดเสร็จ</th><th>ผู้รับผิดชอบ</th><th>สถานะ</th>" : ""}</tr></thead>
      <tbody>${rows || `<tr><td colspan="13" class="empty-state">ไม่มีรายการ</td></tr>`}</tbody>
    </table></div></div>
    <div class="modal-foot">
      <a class="btn" href="/report?${qs}" data-act="report">📄 เปิดในหน้ารายงาน</a>
      <button type="button" class="btn primary" data-act="close">ปิด</button>
    </div>`;
  document.body.appendChild(dlg);
  const close = () => { dlg.close(); dlg.remove(); };
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.querySelector('[data-act="close"]').addEventListener("click", close);
  dlg.showModal();
}

function syncToggles() {
  for (const key of Object.keys(CHARTS)) {
    const card = document.querySelector(`[data-chart="${key}"]`);
    card.querySelectorAll("[data-sort] button").forEach((b) => b.classList.toggle("on", b.dataset.v === prefs[key].sort));
  }
  $("pctTog").querySelectorAll("button").forEach((b) => b.classList.toggle("on", (b.dataset.v === "on") === prefs.pct));
}

// ---------- โหลดข้อมูล ----------
async function run() {
  const from = $("fFrom").value, to = $("fTo").value, type = $("fType").value, compare = $("fCompare").value;
  if (!from || !to) return;
  const cmp = { compare };
  $("cmpRange").classList.toggle("hidden", compare !== "custom");
  if (compare === "custom") {
    if (!$("fCFrom").value || !$("fCTo").value) return; // รอเลือกช่วงเปรียบเทียบให้ครบ
    Object.assign(cmp, { cfrom: $("fCFrom").value, cto: $("fCTo").value });
  }
  history.replaceState(null, "", `/dashboard?${new URLSearchParams({ preset: $("fPreset").value, from, to, type, ...cmp })}`);
  try {
    lastData = await api(`/api/dashboard?${new URLSearchParams({ from, to, type, ...cmp })}`);
    $("dashTitle").textContent = `Dashboard — Line ${lastData.line_name}`;
    const c = lastData.compare;
    $("dashPeriod").textContent = `${fmtDate(from)} – ${fmtDate(to)} · กราฟแสดง: ${TYPE_TEXT[type]}` +
      (c ? ` · เทียบกับ${c.label} (${fmtDate(c.from)} – ${fmtDate(c.to)})` : "");
    renderKpis(lastData);
    drawAll();
  } catch (err) { toast(err.message, "err"); }
}

function applyPreset() {
  const preset = $("fPreset").value;
  if (preset === "custom") return;
  [$("fFrom").value, $("fTo").value] = presetRange(preset);
  run();
}

function drawAll(forPrint = false) {
  Object.keys(CHARTS).forEach((k) => drawChart(k, forPrint));
  drawImprove(forPrint);
}

// ---------- พิมพ์ A4 แนวนอน ----------
// พื้นที่พิมพ์ A4 แนวนอน (ขอบ 8 มม.) ≈ 1062 × 733 px — ค่าตรงกับ CSS @media print (v1.8):
// แถวบน = กราฟเครื่องจักรเต็มความกว้าง (กล่องกราฟสูง 49 มม.), แถวล่าง = 3 กราฟ (53 มม.), ช่องว่าง 2.5 มม. (9.5 px)
// padding + เส้นขอบกล่องกราฟ ≈ 17 px กว้าง / 3 มม. (11 px) สูง — รวมทั้งหน้า ≈ 722 px จาก 733 px (1 หน้า)
const PRINT = { width: 1062, gap: 9.5, pad: 17, heights: { top: 174, bottom: 189 } };
let printing = false;  // ป้องกัน beforeprint / afterprint ซ้ำ
function sizeChartsForPrint() {
  const now = new Date();
  $("printedAt").textContent = `พิมพ์เมื่อ ${fmtDate(isoDate(now))} ${String(now.getHours()).padStart(2, "0")}.${String(now.getMinutes()).padStart(2, "0")} น.`;
  if (printing || !lastData) return;
  printing = true;
  drawAll(true);  // วาดใหม่สำหรับกระดาษ: ไม่มี animation, ตัวอักษรเล็กลง, เกิน 15 เครื่อง → อื่น ๆ
  const third = Math.floor((PRINT.width - PRINT.gap * 2) / 3) - PRINT.pad;
  for (const [key, chart] of Object.entries(charts)) {
    const top = key === "machine";
    chart.resize(top ? PRINT.width - PRINT.pad : third, top ? PRINT.heights.top : PRINT.heights.bottom);
    chart.update("none");  // resize() ของ Chart.js คำนวณใหม่แบบหน่วงเวลา — ต้องคำนวณทันทีก่อนพิมพ์
  }
}
function restoreChartsAfterPrint() {
  if (!printing) return;
  printing = false;
  if (lastData) drawAll();
}

function init() {
  Chart.defaults.font.family = "Sarabun, Tahoma, sans-serif";
  const p = new URLSearchParams(location.search);
  $("fPreset").value = p.get("preset") || "thisMonth";
  $("fType").value = TYPE_TEXT[p.get("type")] ? p.get("type") : "problem";
  if ($("fPreset").value === "custom" && p.get("from") && p.get("to")) {
    $("fFrom").value = p.get("from");
    $("fTo").value = p.get("to");
  } else {
    [$("fFrom").value, $("fTo").value] = presetRange($("fPreset").value);
  }
  $("fPreset").addEventListener("change", applyPreset);
  ["fFrom", "fTo"].forEach((id) => $(id).addEventListener("change", () => { $("fPreset").value = "custom"; run(); }));
  $("fType").addEventListener("change", run);
  $("fCompare").value = ["prev", "yoy", "custom", "none"].includes(p.get("compare")) ? p.get("compare") : "prev";
  $("fCFrom").value = p.get("cfrom") || "";
  $("fCTo").value = p.get("cto") || "";
  ["fCompare", "fCFrom", "fCTo"].forEach((id) => $(id).addEventListener("change", run));

  document.querySelectorAll("[data-chart]").forEach((card) => {
    const key = card.dataset.chart;
    card.addEventListener("click", (e) => {
      const b = e.target.closest(".tog button");
      if (!b) return;
      prefs[key].sort = b.dataset.v;
      savePrefs();
      syncToggles();
      if (lastData) drawChart(key);
    });
  });
  $("kpis").addEventListener("click", (e) => { const c = e.target.closest(".kpi.link"); if (c) openKpi(c.dataset.link); });
  $("kpis").addEventListener("keydown", (e) => {
    const c = e.target.closest(".kpi.link");
    if (c && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); openKpi(c.dataset.link); }
  });
  $("pctTog").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    prefs.pct = b.dataset.v === "on";
    savePrefs();
    syncToggles();
    if (lastData) { renderKpis(lastData); drawAll(); }
  });
  syncToggles();

  window.addEventListener("beforeprint", sizeChartsForPrint);
  window.addEventListener("afterprint", restoreChartsAfterPrint);
  $("printBtn").addEventListener("click", () => window.print());
  api("/api/master").then((m) => { sizeOrder = m.size.map((x) => x.name); }).catch(() => {})
    .finally(() => document.fonts.ready.then(run));
}

document.addEventListener("DOMContentLoaded", init);
