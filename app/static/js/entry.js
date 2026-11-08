/* หน้าบันทึกงาน: แถบยอดผลิต + กรอบปัญหาเครื่องจักร / กรอบการปรับปรุง */
"use strict";

const $ = (id) => document.getElementById(id);
const state = {
  date: todayIso(),
  settings: null,
  master: null,
  events: [],
  dailyDirty: false,
  dailySaved: false,
  targetAuto: false, // ช่องเป้าหมายมีค่าเริ่มต้นที่เติมให้อัตโนมัติ (ผู้ใช้ยังไม่ได้พิมพ์)
  panels: {},
};

function masterNames(kind) { return (state.master?.[kind] || []).map((x) => x.name); }

const PANEL_TEXT = {
  problem: {
    title: "⚠ ปัญหาเครื่องจักร", problem: "ปัญหา", corrective: "การแก้ไข", save: "💾 บันทึกปัญหา",
  },
  improve: {
    title: "🔧 การปรับปรุง", problem: "งานที่ปรับปรุง", corrective: "รายละเอียด", save: "💾 บันทึกการปรับปรุง",
  },
};

// ช่องที่ตรวจว่าเป็นค่าใหม่ (ยังไม่มีใน Master) — ปัญหา/การแก้ไข เป็นช่องพิมพ์อิสระ ไม่ถาม
const MASTER_FIELDS = [
  { field: "size", kind: "size" },
  { field: "machine", kind: "machine" },
  { field: "responsible", kind: "person" },
];

class EntryPanel {
  constructor(type) {
    this.type = type;
    this.root = $(`panel-${type}`);
    this.mode = "machine"; // machine (กรอกเวลา) | rate (กรอกยอดผลิต — v1.9) | stopline | cleaning (v1.10) — เฉพาะกรอบปัญหา
    this.rateMemo = [];    // ค่าผลิตได้จริงที่พิมพ์ไว้ (ตามลำดับช่อง) — เปลี่ยนช่วงเวลาแล้วค่าไม่หาย
    this.editingId = null;
    this.dirty = false;
    this.existingFiles = [];
    this.removeIds = new Set();
    this.pendingFiles = [];
    this.render();
    this.bind();
    this.reset();
  }

  el(name) { return this.root.querySelector(`[data-f="${name}"]`); }

  render() {
    const t = PANEL_TEXT[this.type];
    const isProblem = this.type === "problem";
    this.root.innerHTML = `
      <div class="panel-head"><span>${t.title}</span><span class="grow"></span>
        <label class="ev-date hidden" data-f="evDateBox" title="แก้วันที่ของรายการนี้ — มีผลเมื่อกดบันทึกการแก้ไข">วันที่ของรายการ
          <input type="date" class="input" data-f="evDate"></label>
        <span class="pill hidden" data-f="editPill">✎ กำลังแก้ไข</span></div>
      <form class="panel-body" autocomplete="off" novalidate>
        ${isProblem ? `<div class="mode" role="radiogroup" aria-label="ชนิดปัญหา">
          <button type="button" data-mode="machine">ปัญหาเครื่องจักร</button>
          <button type="button" data-mode="rate" title="เครื่องเสียแต่ยังมีงานออก — คิดชั่วโมงสูญเสียจากจำนวนชิ้น">📦 คิดจากยอดผลิต</button>
          <button type="button" data-mode="stopline">⏸ Stop Line</button>
          <button type="button" data-mode="cleaning" title="หยุดตามแผน — บันทึกลงรายงาน ไม่นับชั่วโมง ไม่ลงกราฟ">🧽 Monday Cleaning</button></div>` : ""}
        <div class="pgrid">
          <div class="field c2 stop-only"><label class="req">วันที่เริ่ม</label><input type="date" class="input" data-f="startDate"></div>
          <div class="field c2 stop-only"><label class="req">วันที่สิ้นสุด</label><input type="date" class="input" data-f="endDate"></div>
          <div class="field stop-only"><label class="req" title="ค่าเริ่มต้น = จำนวนวัน × 24 แก้ไขได้">ชั่วโมง</label>
            <input class="input center num" data-f="stopHours" inputmode="decimal"></div>
          <div class="field time-only"><label class="req">เวลาเริ่ม</label><input class="input center num" data-f="timeFrom" placeholder="HH.MM" inputmode="decimal"></div>
          <div class="field time-only"><label class="req">เวลาสิ้นสุด</label><input class="input center num" data-f="timeTo" placeholder="HH.MM" inputmode="decimal"></div>
          <div class="field hours-field"><span class="label" data-f="hoursLabel">ชั่วโมง</span><div class="calc num" data-f="hours">—</div></div>
          <div class="field time-only"><span class="label">กะ</span><div class="calc" data-f="shift">—</div></div>
          <div class="field time-only size-field"><label>Size</label><input class="input" data-f="size" placeholder="เลือก"></div>
          <div class="field machine-field"><label data-f="machineLabel" class="req">เครื่องจักร</label><input class="input" data-f="machine" placeholder="เลือก"></div>
          ${isProblem ? `<div class="field rate-only"><label class="req" title="ค่าค้างไว้ใช้ครั้งต่อไป">เป้าผลิต/ชม.</label>
            <input class="input right num" data-f="rateTarget" inputmode="numeric" placeholder="ชิ้น"></div>
          <div class="field c5 rate-only"><label class="req" title="1 ช่อง = 1 ชั่วโมงตามช่วงเวลา · ช่องว่างไม่นับ · ล้างทุกครั้งที่บันทึก">ผลิตได้จริง/ชม. <span class="muted small" data-f="rateHint"></span></label>
            <div class="rate-list" data-f="rateList"></div></div>` : ""}
          <div class="field c3"><label class="req" data-f="problemLabel">${t.problem}</label>
            <textarea class="input" data-f="problem" rows="3" placeholder="พิมพ์รายละเอียด"></textarea></div>
          <div class="field c3"><label data-f="correctiveLabel">${t.corrective}</label>
            <textarea class="input" data-f="corrective" rows="3" placeholder="พิมพ์รายละเอียด"></textarea></div>
          ${isProblem ? "" : `
          <div class="field c2"><label>กำหนดวันเสร็จ</label><input type="date" class="input" data-f="dueDate"></div>
          <div class="field c2"><label>ผู้รับผิดชอบ</label><input class="input" data-f="responsible" placeholder="เลือก"></div>
          <div class="field c2"><label>สถานะ</label>
            <select class="input" data-f="status">
              <option value="pending">รอดำเนินการ</option><option value="in_progress">ระหว่างดำเนินการ</option><option value="done">เสร็จแล้ว</option>
            </select></div>`}
        </div>
        <div class="panel-foot">
          <label class="btn sm" title="รูปภาพ, PDF, Excel, Word · สูงสุด ${ATTACH_MAX_FILES} ไฟล์ ไฟล์ละไม่เกิน ${ATTACH_MAX_MB} MB">📎 แนบเอกสาร
            <input type="file" multiple hidden data-f="filePick" accept="${ATTACH_EXT.join(",")}"></label>
          <div class="files" data-f="files"></div>
          <button type="button" class="btn sm" data-f="cancel">ล้าง</button>
          <button type="submit" class="btn save-${this.type}" data-f="save">${t.save}</button>
        </div>
      </form>`;
    this.form = this.root.querySelector("form");
  }

  bind() {
    new Combo(this.el("size"), () => masterNames("size"), { format: sizeLabel });
    new Combo(this.el("machine"), () => masterNames("machine"));
    if (this.el("responsible")) new Combo(this.el("responsible"), () => masterNames("person"));

    this.root.querySelectorAll(".mode button").forEach((b) => b.addEventListener("click", () => {
      if (b.dataset.mode !== this.mode) { this.setMode(b.dataset.mode); this.dirty = true; }
    }));
    ["timeFrom", "timeTo"].forEach((f) => {
      this.el(f).addEventListener("input", () => { this.syncRateSlots(); this.updateCalc(); });
      this.el(f).addEventListener("blur", (e) => {
        const m = parseTime(e.target.value);
        if (m !== null) e.target.value = formatTime(m);
        this.updateCalc();
      });
    });
    ["startDate", "endDate"].forEach((f) => this.el(f).addEventListener("change", () => this.updateStopHours()));
    if (this.el("rateList")) {
      this.el("rateTarget").addEventListener("input", () => this.updateCalc());
      this.el("rateTarget").addEventListener("blur", (e) => this.formatQty(e.target));
      this.el("rateList").addEventListener("input", () => { this.rememberRates(); this.updateCalc(); });
      this.el("rateList").addEventListener("focusout", (e) => { if (e.target.matches("input")) this.formatQty(e.target); });
    }
    this.el("stopHours").addEventListener("input", () => { this.stopHoursTouched = true; });
    this.form.addEventListener("input", (e) => { this.dirty = true; if (e.target.value) e.target.classList.remove("invalid"); });
    this.form.addEventListener("submit", (e) => { e.preventDefault(); this.submit(); });
    this.el("cancel").addEventListener("click", () => this.reset());
    this.el("filePick").addEventListener("change", (e) => { this.addFiles([...e.target.files]); e.target.value = ""; });
    this.el("files").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-act]");
      if (!b) return;
      if (b.dataset.act === "drop") this.pendingFiles.splice(Number(b.dataset.i), 1);
      else {
        const id = Number(b.dataset.id);
        if (this.removeIds.has(id)) this.removeIds.delete(id); else this.removeIds.add(id);
      }
      this.dirty = true;
      this.renderFiles();
    });
  }

  setMode(mode) {
    this.mode = this.type === "problem" ? mode : "machine";
    const stop = this.mode === "stopline", rate = this.mode === "rate", clean = this.mode === "cleaning";
    this.root.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === this.mode));
    this.root.querySelectorAll(".stop-only").forEach((x) => x.classList.toggle("hidden", !stop));
    // v1.10 โหมดยอดผลิตใช้ช่องเวลาร่วมกับโหมดเวลา (สลับโหมดแล้วเวลาที่พิมพ์ไว้ไม่หาย) · Monday Cleaning ไม่มี Size
    this.root.querySelectorAll(".time-only").forEach((x) => x.classList.toggle("hidden", stop || (clean && x.classList.contains("size-field"))));
    this.root.querySelectorAll(".rate-only").forEach((x) => x.classList.toggle("hidden", !rate));
    this.root.querySelectorAll(".hours-field").forEach((x) => x.classList.toggle("hidden", stop));
    this.root.classList.toggle("rate-mode", rate);
    this.root.classList.toggle("cleaning-mode", clean);
    if (rate && !this.el("rateTarget").value && state.settings.rate_target) {
      this.el("rateTarget").value = fmtInt(Number(state.settings.rate_target));  // เป้าค้างไว้จากครั้งก่อน
    }
    if (rate) this.syncRateSlots();
    // วันที่ของรายการ (ตอนแก้ไข): Stop Line ใช้ช่องวันที่เริ่มแทน
    this.el("evDateBox").classList.toggle("hidden", !this.editingId || stop);
    const ml = this.el("machineLabel");
    ml.textContent = stop || clean ? "เครื่องจักร (ถ้ามี)" : "เครื่องจักร";
    ml.classList.toggle("req", !stop && !clean);
    const pl = this.el("problemLabel");
    pl.textContent = stop ? "สาเหตุที่หยุด Line" : clean ? "รายละเอียด" : PANEL_TEXT[this.type].problem;
    pl.classList.toggle("req", !clean);
    this.el("problem").placeholder = clean ? "ไม่บังคับ — ว่าง = Monday Cleaning" : "พิมพ์รายละเอียด";
    this.el("correctiveLabel").textContent = clean ? "หมายเหตุ" : PANEL_TEXT[this.type].corrective;
    this.el("hoursLabel").textContent = clean ? "ชั่วโมง (ไม่นับ)" : "ชั่วโมง";
    this.el("hoursLabel").title = clean ? "บันทึกอย่างเดียว — ไม่รวมในชั่วโมงรวม / ชั่วโมงสูญเสีย / กราฟ" : "";
    this.updateCalc();
  }

  updateCalc() {
    const f = parseTime(this.el("timeFrom").value), t = parseTime(this.el("timeTo").value);
    this.el("timeFrom").classList.toggle("invalid", this.el("timeFrom").value.trim() !== "" && f === null);
    this.el("timeTo").classList.toggle("invalid", this.el("timeTo").value.trim() !== "" && t === null);
    this.el("shift").textContent = f === null ? "—"
      : calcShift(f, parseTime(state.settings.morning_start), parseTime(state.settings.night_start)) === "M" ? "☀ เช้า" : "☾ ดึก";
    if (this.mode === "rate") {
      // ชั่วโมงมาจากยอดผลิต (ช่วงเวลาบอกตำแหน่ง/กะเท่านั้น)
      const { target, actuals } = this.readRates();
      const ok = target > 0 && actuals.length && actuals.every((a) => !Number.isNaN(a));
      this.el("rateTarget").classList.toggle("invalid", Number.isNaN(target));
      const hours = ok ? calcRateHours(target, actuals) : null;
      this.el("hours").innerHTML = hours === null ? "—"
        : `${fmtHours(hours)} <span class="unit">ชม. (${Math.round(hours * 60)} นาที)</span>`;
      return;
    }
    const hours = f !== null && t !== null ? calcHours(f, t) : null;
    this.el("hours").innerHTML = hours !== null ? `${fmtHours(hours)} <span class="unit">ชม.</span>` : "—";
  }

  // ---------- คิดจากยอดผลิต (v1.9 · v1.10 ช่องตามช่วงเวลา) ----------
  /** เก็บค่าที่พิมพ์ไว้ตามลำดับช่อง — ย่อ/ขยายช่วงเวลาแล้วค่าเดิมกลับมา */
  rememberRates() {
    this.el("rateList").querySelectorAll("input").forEach((inp, i) => { this.rateMemo[i] = inp.value; });
  }

  /** ช่องผลิตได้จริง 1 ช่องต่อ 1 ชั่วโมงในช่วงเวลา (ป้ายเวลาจริงเหนือช่อง) — ยังไม่มีเวลา: แสดงค่าที่มีอยู่ (รายการเก่า) */
  syncRateSlots() {
    if (!this.el("rateList")) return;  // this.rateMemo อัปเดตทุกครั้งที่พิมพ์ในช่อง (rememberRates)
    const f = parseTime(this.el("timeFrom").value), t = parseTime(this.el("timeTo").value);
    const slots = f !== null && t !== null ? rateSlots(f, t) : null;
    const filled = this.rateMemo.filter((v) => String(v ?? "").trim() !== "").length;
    const labels = slots ? slots.map(formatTime) : (this.rateMemo.length ? this.rateMemo : [""]).map((_, i) => `ชม.ที่ ${i + 1}`);
    this.el("rateList").innerHTML = labels.map((lb, i) => `<span class="rate-item"><span class="rate-h">${esc(lb)}</span>
      <input class="input right num" inputmode="numeric" placeholder="ชิ้น" value="${esc(this.rateMemo[i] ?? "")}" aria-label="ผลิตได้จริง ${esc(lb)}"></span>`).join("");
    const over = slots && filled > slots.length && this.rateMemo.slice(slots.length).some((v) => String(v ?? "").trim() !== "");
    this.el("rateHint").textContent = !slots ? "— กรอกเวลาเริ่ม–สิ้นสุดก่อน ช่องจะขึ้นตามชั่วโมง"
      : over ? `— ⚠ ช่วงเวลา ${slots.length} ชม. ยอดผลิตชั่วโมงที่เกินช่วงจะไม่ถูกบันทึก` : `— ${slots.length} ช่อง (ช่องว่างไม่นับ)`;
    this.el("rateHint").classList.toggle("neg", Boolean(over));
  }

  resetRates(values = []) {
    this.rateMemo = values.slice();
    this.syncRateSlots();
  }

  readRates() {
    const target = parseQty(this.el("rateTarget").value);
    const actuals = [...this.el("rateList").querySelectorAll("input")]
      .map((i) => i.value.trim()).filter((v) => v !== "").map(parseQty);
    return { target, actuals };
  }

  formatQty(input) {
    const v = parseQty(input.value);
    input.classList.toggle("invalid", Number.isNaN(v));
    if (v !== null && !Number.isNaN(v)) input.value = fmtInt(v);
  }

  /** Stop Line: เติมชั่วโมง = จำนวนวัน × 24 ให้อัตโนมัติ จนกว่าผู้ใช้จะแก้ตัวเลขเอง */
  updateStopHours() {
    const days = stopLineDays(this.el("startDate").value, this.el("endDate").value);
    this.el("endDate").classList.toggle("invalid", days === null && !!this.el("endDate").value);
    if (days !== null && !this.stopHoursTouched) this.el("stopHours").value = String(days * 24);
  }

  // ---------- ไฟล์แนบ ----------
  fileCount() { return this.existingFiles.length - this.removeIds.size + this.pendingFiles.length; }

  addFiles(files) {
    for (const f of files) {
      if (!ATTACH_EXT.includes(fileExt(f.name))) { toast(`ไม่รองรับไฟล์ "${f.name}" — แนบได้เฉพาะรูปภาพ, PDF, Excel, Word`, "err"); continue; }
      if (f.size > ATTACH_MAX_MB * 1048576) { toast(`ไฟล์ "${f.name}" ใหญ่เกิน ${ATTACH_MAX_MB} MB`, "err"); continue; }
      if (f.size === 0) { toast(`ไฟล์ "${f.name}" ว่างเปล่า`, "err"); continue; }
      if (this.fileCount() >= ATTACH_MAX_FILES) { toast(`แนบได้ไม่เกิน ${ATTACH_MAX_FILES} ไฟล์ต่อรายการ`, "err"); break; }
      this.pendingFiles.push(f);
      this.dirty = true;
    }
    this.renderFiles();
  }

  renderFiles() {
    const existing = this.existingFiles.map((a) => {
      const removed = this.removeIds.has(a.id);
      return `<span class="file-chip ${removed ? "removed" : ""}" title="${esc(a.name)}">
        <a class="nm file-link" href="/api/attachments/${a.id}" target="_blank" rel="noopener">${esc(a.name)}</a>
        <button type="button" data-act="toggle" data-id="${a.id}" title="${removed ? "ยกเลิกการลบ" : "ลบไฟล์นี้ (มีผลเมื่อกดบันทึก)"}">${removed ? "↺" : "✕"}</button></span>`;
    });
    const pending = this.pendingFiles.map((f, i) => `<span class="file-chip new" title="${esc(f.name)} (${fmtSize(f.size)}) — จะอัปโหลดเมื่อกดบันทึก">
      <span class="nm">${esc(f.name)}</span><button type="button" data-act="drop" data-i="${i}" title="เอาออก">✕</button></span>`);
    const html = existing.concat(pending).join("");
    this.el("files").innerHTML = html || `<span class="muted small">ยังไม่มีไฟล์แนบ</span>`;
  }

  // ---------- ฟอร์ม ----------
  read() {
    const stop = this.mode === "stopline";
    const v = (f) => this.el(f).value.trim();
    const body = {
      // ตอนแก้ไข: วันที่ของรายการแก้ได้ในกรอบ (v1.10) — บันทึกใหม่ใช้วันที่ด้านบน
      date: stop ? this.el("startDate").value : this.editingId ? this.el("evDate").value : state.date,
      type: this.type,
      stop_line: stop,
      machine: v("machine"), problem: v("problem"), corrective: v("corrective"),
    };
    if (stop) {
      Object.assign(body, { end_date: this.el("endDate").value || null, hours: Number(v("stopHours").replace(",", ".")) || null });
    } else if (this.mode === "rate") {
      const { target, actuals } = this.readRates();
      Object.assign(body, { time_from: v("timeFrom"), time_to: v("timeTo"), size: v("size"),
        rate_target: target, rate_actuals: actuals });
    } else if (this.mode === "cleaning") {
      Object.assign(body, { time_from: v("timeFrom"), time_to: v("timeTo"), planned_stop: "cleaning" });
    } else {
      Object.assign(body, { time_from: v("timeFrom"), time_to: v("timeTo"), size: v("size") });
    }
    if (this.type === "improve") {
      Object.assign(body, { due_date: this.el("dueDate").value || null, responsible: v("responsible"), status: this.el("status").value });
    }
    return body;
  }

  validate(body) {
    const errors = [];
    const mark = (f, bad) => { this.el(f).classList.toggle("invalid", bad); return bad; };
    const stop = body.stop_line;
    if (!stop && mark("evDate", !body.date)) errors.push("วันที่ของรายการ");
    if (stop) {
      if (mark("startDate", !body.date)) errors.push("วันที่เริ่ม");
      if (mark("endDate", !body.end_date)) errors.push("วันที่สิ้นสุด");
      const days = body.date && body.end_date ? stopLineDays(body.date, body.end_date) : 0;
      if (days === null) { mark("endDate", true); errors.push("วันที่สิ้นสุดต้องไม่ก่อนวันที่เริ่ม"); }
      if (days && mark("stopHours", !(body.hours > 0 && body.hours <= days * 24))) errors.push(`ชั่วโมง (มากกว่า 0 และไม่เกิน ${days * 24})`);
    } else if (this.mode === "rate") {
      if (mark("timeFrom", parseTime(body.time_from) === null)) errors.push("เวลาเริ่ม (HH.MM เช่น 7.00)");
      if (mark("timeTo", parseTime(body.time_to) === null)) errors.push("เวลาสิ้นสุด (HH.MM เช่น 8.00)");
      if (mark("rateTarget", !(body.rate_target > 0))) errors.push("เป้าผลิต/ชม. (จำนวนเต็มมากกว่า 0)");
      const bad = !body.rate_actuals.length || body.rate_actuals.some((a) => Number.isNaN(a));
      this.el("rateList").querySelectorAll("input").forEach((i, n) => {
        i.classList.toggle("invalid", bad && (Number.isNaN(parseQty(i.value)) || (n === 0 && !body.rate_actuals.length)));
      });
      if (bad) errors.push("ผลิตได้จริง/ชม. (อย่างน้อย 1 ชั่วโมง เป็นจำนวนเต็ม)");
      if (mark("machine", !body.machine)) errors.push("เครื่องจักร");
    } else if (this.mode === "cleaning") {
      if (mark("timeFrom", parseTime(body.time_from) === null)) errors.push("เวลาเริ่ม (HH.MM เช่น 7.00)");
      if (mark("timeTo", parseTime(body.time_to) === null)) errors.push("เวลาสิ้นสุด (HH.MM เช่น 8.00)");
      this.el("machine").classList.remove("invalid");
      this.el("problem").classList.remove("invalid");
      return errors;  // เครื่องจักร / รายละเอียด ไม่บังคับ
    } else {
      if (mark("timeFrom", parseTime(body.time_from) === null)) errors.push("เวลาเริ่ม (HH.MM เช่น 7.00)");
      if (mark("timeTo", parseTime(body.time_to) === null)) errors.push("เวลาสิ้นสุด (HH.MM เช่น 8.00)");
      if (mark("machine", !body.machine)) errors.push("เครื่องจักร");
    }
    if (mark("problem", !body.problem)) errors.push(this.el("problemLabel").textContent);
    return errors;
  }

  async askNewMasterValues(body) {
    const fresh = MASTER_FIELDS
      .map((f) => ({ ...f, checked: true, value: body[f.field] }))
      .filter((x) => x.value && !masterNames(x.kind).includes(x.value));
    if (!fresh.length) return [];
    const html = `ค่าต่อไปนี้ยังไม่มีในรายการตัวเลือก — เลือกรายการที่ต้องการ<b>เพิ่มเข้า Master</b>
      <ul class="check-list">${fresh.map((x, i) => `
        <li><label><input type="checkbox" data-i="${i}" ${x.checked ? "checked" : ""}>
          <span><span class="kind">${esc(MASTER_LABELS[x.kind])}:</span> ${esc(x.value.length > 120 ? x.value.slice(0, 120) + "…" : x.value)}</span></label></li>`).join("")}
      </ul>`;
    return modal({
      title: "พบค่าใหม่", html, okText: "บันทึก", cancelText: "กลับไปแก้ไข",
      collect: (dlg) => [...dlg.querySelectorAll("input[type=checkbox]:checked")].map((c) => fresh[Number(c.dataset.i)]),
    });
  }

  async submit() {
    const body = this.read();
    const errors = this.validate(body);
    if (errors.length) { toast("กรุณากรอก: " + errors.join(", "), "err"); return; }
    const toAdd = await this.askNewMasterValues(body);
    if (toAdd === false) return;

    const btn = this.el("save");
    btn.disabled = true;
    const editing = this.editingId;
    let saved;
    try {
      saved = await api(editing ? `/api/events/${editing}` : "/api/events", { method: editing ? "PUT" : "POST", body });
    } catch (err) {
      toast(err.message, "err");
      btn.disabled = false;
      return;
    }
    // ไฟล์แนบ: ลบที่ทำเครื่องหมาย แล้วอัปโหลดไฟล์ใหม่
    let fileError = null;
    try {
      for (const id of this.removeIds) await api(`/api/attachments/${id}`, { method: "DELETE" });
      if (this.pendingFiles.length) {
        const fd = new FormData();
        this.pendingFiles.forEach((f) => fd.append("files", f));
        await api(`/api/events/${saved.id}/attachments`, { method: "POST", body: fd });
      }
    } catch (err) { fileError = err.message; }
    for (const item of toAdd) {
      try { await api(`/api/master/${item.kind}`, { method: "POST", body: { name: item.value } }); }
      catch (err) { toast(err.message, "err"); }
    }
    if (toAdd.length) state.master = await api("/api/master");
    btn.disabled = false;

    await loadEvents();
    if (fileError) {
      toast(`บันทึกรายการแล้ว แต่ไฟล์แนบไม่สำเร็จ: ${fileError}`, "err");
      const ev = await api(`/api/events?date=${saved.date}`).then((list) => list.find((x) => x.id === saved.id));
      if (ev) this.load(ev);
      return;
    }
    if (saved.rate_target) state.settings.rate_target = String(saved.rate_target);  // เป้าค้างไว้ใช้ครั้งต่อไป
    const moved = saved.date !== state.date;
    const where = moved ? ` (บันทึกไว้ที่วันที่ ${fmtDate(saved.date)})` : "";
    // v1.10 รายการย้ายไปวันอื่น → ปุ่มไปที่วันนั้น
    toast((editing ? "แก้ไขรายการแล้ว" : "บันทึกรายการแล้ว") + where, "ok",
      moved ? { label: `ไปที่วันที่ ${fmtDate(saved.date)}`, onClick: () => setDate(saved.date) } : null);
    this.reset({ keep: true });
  }

  reset({ keep = false } = {}) {
    const keepSize = keep ? this.el("size").value : "";
    ["timeFrom", "timeTo", "size", "machine", "problem", "corrective", "dueDate", "responsible", "startDate", "endDate", "stopHours"]
      .forEach((f) => {
        const el = this.el(f);
        if (!el) return;
        el.value = "";
        el.classList.remove("invalid");
      });
    this.el("size").value = keepSize; // Size มักเหมือนเดิมทั้งวัน
    if (this.el("status")) this.el("status").value = "pending";
    if (this.el("rateList")) {
      this.resetRates();  // ผลิตได้จริง ล้างทุกครั้ง — เป้าผลิต/ชม. ค้างไว้
      this.el("rateTarget").classList.remove("invalid");
    }
    this.el("evDate").value = state.date;
    this.el("evDate").classList.remove("invalid");
    this.el("startDate").value = state.date;
    this.el("endDate").value = state.date;
    this.stopHoursTouched = false;
    this.updateStopHours();
    this.existingFiles = [];
    this.removeIds = new Set();
    this.pendingFiles = [];
    this.editingId = null;
    this.dirty = false;
    this.el("editPill").classList.add("hidden");
    this.el("save").textContent = PANEL_TEXT[this.type].save;
    this.setMode(keep ? this.mode : "machine");
    this.renderFiles();
  }

  load(ev) {
    this.reset();
    const set = (f, v) => { this.el(f).value = v ?? ""; };
    this.editingId = ev.id;  // ก่อน setMode — แสดงช่องวันที่ของรายการ
    set("evDate", ev.date);
    set("timeFrom", ev.time_from); set("timeTo", ev.time_to);  // ก่อนช่องยอดผลิต (ช่องขึ้นตามช่วงเวลา)
    if (ev.rate_actuals) {
      this.el("rateTarget").value = fmtInt(ev.rate_target);
      this.rateMemo = ev.rate_actuals.map(fmtInt);
    }
    this.setMode(ev.stop_line ? "stopline" : ev.cleaning ? "cleaning" : ev.rate_actuals ? "rate" : "machine");
    set("startDate", ev.date);
    set("endDate", ev.end_date || ev.date);
    if (ev.stop_line) { set("stopHours", fmtHours(ev.hours)); this.stopHoursTouched = true; }
    set("size", ev.size); set("machine", ev.machine);
    set("problem", ev.problem); set("corrective", ev.corrective);
    if (this.type === "improve") { set("dueDate", ev.due_date); set("responsible", ev.responsible); set("status", ev.status || "pending"); }
    this.existingFiles = ev.attachments || [];
    this.el("editPill").classList.remove("hidden");
    this.el("save").textContent = "💾 บันทึกการแก้ไข";
    this.updateCalc();
    this.renderFiles();
    this.root.scrollIntoView({ behavior: "smooth", block: "nearest" });
    (ev.stop_line ? this.el("problem") : ev.rate_actuals && ev.time_from ? this.el("rateList").querySelector("input") : this.el("timeFrom")).focus();
    // รายการยอดผลิตเก่า (v1.9) ไม่มีเวลา — v1.10 ต้องกรอกเวลาก่อนบันทึกการแก้ไข
    if (ev.rate_actuals && !ev.time_from) toast("รายการนี้ยังไม่มีช่วงเวลา — กรอกเวลาเริ่ม–สิ้นสุดก่อนบันทึกการแก้ไข", "err");
  }

  /** v1.10 เปลี่ยนวันที่ด้านบนระหว่างแก้ไข → ย้ายรายการไปวันนั้น (มีผลเมื่อกดบันทึกการแก้ไข) */
  moveTo(iso) {
    if (this.mode === "stopline") {  // วันที่สิ้นสุดเลื่อนเท่ากัน — จำนวนวันเท่าเดิม
      const days = stopLineDays(this.el("startDate").value || iso, this.el("endDate").value || iso) || 1;
      this.el("startDate").value = iso;
      this.el("endDate").value = addDays(iso, days - 1);
    } else {
      this.el("evDate").value = iso;
    }
    this.dirty = true;
  }
}

// ---------- วันที่ ----------
function anyDirty() { return state.dailyDirty || Object.values(state.panels).some((p) => p.dirty); }

async function setDate(iso, { force = false } = {}) {
  if (!iso) return;
  const panels = Object.values(state.panels);
  const keep = new Set();  // กรอบที่กำลังแก้ไขและเลือก "ย้ายรายการ" — ไม่ล้าง
  // v1.10 กำลังแก้ไขรายการอยู่ → ถาม ย้ายไปวันที่ใหม่ / ทิ้งการแก้ไข (เดิมล้างฟอร์มเงียบ ๆ)
  const editing = panels.filter((p) => p.editingId);
  if (!force && iso !== state.date && editing.length) {
    const what = editing.map((p) => PANEL_TEXT[p.type].title.replace(/^\S+\s/, "")).join(" และ ");
    const choice = await choiceBox("กำลังแก้ไขรายการอยู่",
      `กำลังแก้ไขรายการ<b>${esc(what)}</b> ของวันที่ ${fmtDate(state.date)}<br>
       ต้องการ<b>ย้ายรายการนี้ไปวันที่ ${fmtDate(iso)}</b> หรือทิ้งการแก้ไข?<br>
       <span class="small muted">ย้าย = เปลี่ยนวันที่ในกรอบให้ แล้วกด 💾 บันทึกการแก้ไข เพื่อยืนยัน (ข้อมูลอื่นที่แก้ไว้ยังอยู่)</span>`,
      [{ value: "discard", label: "ทิ้งการแก้ไข", kind: "danger" },
       { value: "move", label: `ย้ายไปวันที่ ${fmtDate(iso)}`, kind: "primary" }]);
    if (!choice) { $("datePick").value = state.date; return; }
    if (choice === "move") editing.forEach((p) => { p.moveTo(iso); keep.add(p); });
  }
  const otherDirty = state.dailyDirty || panels.some((p) => !p.editingId && p.dirty);
  if (!force && otherDirty && iso !== state.date) {
    const ok = await confirmBox("มีข้อมูลที่ยังไม่ได้บันทึก",
      "ต้องการเปลี่ยนวันที่และ<b>ทิ้งข้อมูลที่ยังไม่บันทึก</b>หรือไม่?", "เปลี่ยนวันที่", true);
    if (!ok) { $("datePick").value = state.date; return; }
  }
  state.date = iso;
  $("datePick").value = iso;
  $("dayName").textContent = `วัน${thaiDay(iso)}`;
  history.replaceState(null, "", iso === todayIso() ? "/" : `/?date=${iso}`);
  panels.forEach((p) => { if (!keep.has(p)) p.reset(); });
  if (keep.size) toast(`เปลี่ยนวันที่ของรายการเป็น ${fmtDate(iso)} แล้ว — กด 💾 บันทึกการแก้ไข เพื่อยืนยัน`, "ok");
  await Promise.all([loadDaily(), loadEvents()]);
}

// ---------- ยอดผลิต ----------
async function loadDaily() {
  try {
    const d = await api(`/api/daily/${state.date}`);
    const defTarget = state.settings.default_target;
    $("target").value = d.saved ? fmtInt(d.target) : (defTarget ? fmtInt(Number(defTarget)) : "");
    $("output").value = fmtInt(d.output);
    $("holiday").checked = d.holiday;
    state.dailySaved = d.saved;
    state.targetAuto = !d.saved && Boolean(defTarget);
    setDailyState(d.saved ? "saved" : "new");
    state.dailyDirty = false;
    updateDiff();
    updateMoveBtn();
  } catch (err) { toast(err.message, "err"); }
}

function setDailyState(kind) {
  const el = $("dailyState");
  el.className = "pill " + (kind === "saved" ? "done" : "open");
  el.textContent = kind === "saved" ? "✓ บันทึกแล้ว" : kind === "dirty" ? "ยังไม่บันทึก" : "ยังไม่มีข้อมูล";
}

function updateDiff() {
  const t = parseQty($("target").value), o = parseQty($("output").value);
  const box = $("diffBox");
  box.className = "diff-box num";
  if (t === null || o === null || Number.isNaN(t) || Number.isNaN(o)) { box.textContent = "—"; return; }
  box.textContent = fmtSigned(o - t);
  box.classList.add(signClass(o - t));
}

async function saveDaily() {
  const target = parseQty($("target").value), output = parseQty($("output").value);
  if (Number.isNaN(target) || Number.isNaN(output)) { toast("เป้าหมาย / ผลิตได้ ต้องเป็นตัวเลขจำนวนเต็ม", "err"); return; }
  try {
    const d = await api(`/api/daily/${state.date}`, { method: "PUT", body: { target, output, holiday: $("holiday").checked } });
    $("target").value = fmtInt(d.target);
    $("output").value = fmtInt(d.output);
    $("holiday").checked = d.holiday;
    state.dailyDirty = false;
    state.dailySaved = true;
    state.targetAuto = false;
    setDailyState("saved");
    updateDiff();
    updateMoveBtn();
    toast(`บันทึกยอดผลิตวันที่ ${fmtDate(state.date)} แล้ว`, "ok");
  } catch (err) { toast(err.message, "err"); }
}

// ---------- ย้ายข้อมูลที่กรอกผิดวัน (v1.10) ----------
function updateMoveBtn() { $("moveDay").classList.toggle("hidden", !state.dailySaved && !state.events.length); }

async function moveDay() {
  if (anyDirty()) { toast("มีข้อมูลที่ยังไม่บันทึก — บันทึกหรือกด ล้าง ก่อนย้ายวันที่", "err"); return; }
  const src = state.date, n = state.events.length;
  const daily = state.dailySaved
    ? `<li>ยอดผลิต: เป้าหมาย <b>${esc($("target").value || "—")}</b> · ผลิตได้ <b>${esc($("output").value || "—")}</b>${$("holiday").checked ? " · วันหยุด" : ""}</li>` : "";
  const res = await modal({
    title: `ย้ายข้อมูลของวันที่ ${fmtDate(src)} (วัน${thaiDay(src)})`,
    html: `<div class="field" style="max-width:220px"><label class="req">ย้ายไปวันที่ (วันที่ถูกต้อง)</label>
        <input type="date" class="input" data-f="to"></div>
      <ul class="check-list">${daily}
        ${n ? `<li><label><input type="checkbox" data-f="withEvents" checked>
          <span>ย้ายรายการปัญหา / การปรับปรุงของวันนี้ไปด้วย (<b>${n}</b> รายการ — Stop Line เลื่อนวันที่สิ้นสุดเท่ากัน)</span></label></li>` : ""}
      </ul>
      <p class="small muted" style="margin:6px 0 0">ไม่เขียนทับ: ถ้าวันที่ปลายทางมียอดผลิตบันทึกไว้แล้ว จะย้ายยอดผลิตไม่ได้</p>`,
    okText: "↪ ย้าย",
    collect: (dlg) => ({ to: dlg.querySelector("[data-f=to]").value, withEvents: Boolean(dlg.querySelector("[data-f=withEvents]")?.checked) }),
  });
  if (!res) return;
  if (!res.to || res.to === src) { toast("กรุณาเลือกวันที่ปลายทาง (ไม่ใช่วันเดิม)", "err"); return; }
  try {
    const r = await api(`/api/daily/${src}/move`, { method: "POST", body: { to: res.to, with_events: res.withEvents } });
    await setDate(res.to, { force: true });
    const what = [state.dailySaved && "ยอดผลิต", r.events_moved && `${r.events_moved} รายการ`].filter(Boolean).join(" + ");
    toast(`ย้าย${what}ไปวันที่ ${fmtDate(res.to)} แล้ว`, "ok", { label: `กลับไปวันที่ ${fmtDate(src)}`, onClick: () => setDate(src) });
  } catch (err) { toast(err.message, "err"); }
}

/** วันหยุด: ไม่เติมเป้าหมายเริ่มต้นให้อัตโนมัติ (ค่าที่ผู้ใช้พิมพ์เองไม่ถูกล้าง) */
function onHolidayChange() {
  const defTarget = state.settings.default_target;
  if ($("holiday").checked && state.targetAuto) {
    $("target").value = "";
    state.targetAuto = false;
  } else if (!$("holiday").checked && !state.dailySaved && !$("target").value && defTarget) {
    $("target").value = fmtInt(Number(defTarget));
    state.targetAuto = true;
  }
  state.dailyDirty = true;
  setDailyState("dirty");
  updateDiff();
}

// ---------- รายการของวัน (หน้าต่าง ดู/แก้ไข) ----------
async function loadEvents() {
  try {
    state.events = await api(`/api/events?date=${state.date}`);
  } catch (err) { toast(err.message, "err"); state.events = []; }
  const n = state.events.length;
  // ชั่วโมงรวมไม่นับ Stop Line / Monday Cleaning (บันทึกอย่างเดียว)
  const hours = Math.round(state.events.filter((e) => !e.record_only).reduce((s, e) => s + e.hours, 0) * 100) / 100;
  const stops = state.events.filter((e) => e.stop_line).length;
  const cleans = state.events.filter((e) => e.cleaning).length;
  const excluded = [stops && `Stop Line ${stops}`, cleans && `Monday Cleaning ${cleans}`].filter(Boolean).join(" · ");
  // 2 บรรทัด: จำนวน/ชั่วโมง + รายการที่ไม่นับ (แถบวันที่อยู่บรรทัดเดียวเสมอ — v1.10)
  const main = n ? `วันนี้ ${n} รายการ · ${fmtHours(hours)} ชม.` : "ยังไม่มีรายการของวันนี้";
  const note = n && excluded ? `ไม่รวม ${excluded} รายการ` : "";
  $("daySummary").innerHTML = `<span>${esc(main)}</span>${note ? `<span class="note">${esc(note)}</span>` : ""}`;
  $("daySummary").title = note ? `${main} (${note})` : main;
  updateMoveBtn();
  if (state.dayDialog) renderDayRows();
}

function dayRowsHtml() {
  if (!state.events.length) return '<tr><td colspan="12" class="empty-state">ยังไม่มีรายการของวันนี้</td></tr>';
  const today = todayIso();
  return state.events.map((e) => {
    return `<tr data-id="${e.id}">
      <td><span class="pill ${e.stop_line ? "stopline" : e.cleaning ? "cleaning" : e.type}">${esc(e.type_label)}</span></td>
      <td class="c num" style="white-space:nowrap">${eventTimeText(e)}</td>
      <td class="c num${e.record_only ? " not-counted" : ""}">${fmtHours(e.hours)}</td>
      <td class="c">${esc(e.shift_label)}</td>
      <td style="white-space:nowrap">${esc(sizeLabel(e.size))}</td>
      <td>${esc(e.machine)}</td>
      <td class="wrap">${esc(e.problem)}</td>
      <td class="wrap">${esc(e.corrective)}</td>
      <td>${attachLinks(e.attachments)}</td>
      <td class="num">${fmtDate(e.due_date)}</td>
      <td>${esc(e.responsible)}</td>
      <td>${statusPill(e, today)}</td>
      <td class="c" style="white-space:nowrap"><button class="btn sm" data-act="edit">แก้ไข</button>
        <button class="btn sm danger" data-act="del">ลบ</button></td></tr>`;
  }).join("");
}

function renderDayRows() {
  const body = state.dayDialog.querySelector("tbody");
  if (body) body.innerHTML = dayRowsHtml();
}

function openDayList() {
  const dlg = document.createElement("dialog");
  dlg.className = "modal wide";
  dlg.innerHTML = `
    <div class="modal-head">รายการของวันที่ ${fmtDate(state.date)} (วัน${thaiDay(state.date)})</div>
    <div class="modal-body"><p class="small muted" style="margin:0 0 6px">ชั่วโมงของ Stop Line / Monday Cleaning (สีจาง) เป็นข้อมูลบันทึกอย่างเดียว ไม่นับรวมในชั่วโมงรวม / กราฟ</p>
      <div class="table-wrap"><table class="data">
      <thead><tr><th>ประเภท</th><th class="c">เวลา</th><th class="c">ชม.</th><th class="c">กะ</th><th>Size</th><th>เครื่องจักร</th>
        <th>ปัญหา / งานที่ปรับปรุง</th><th>การแก้ไข / รายละเอียด</th><th>ไฟล์แนบ</th><th>กำหนดเสร็จ</th><th>ผู้รับผิดชอบ</th><th>สถานะ</th><th class="c">จัดการ</th></tr></thead>
      <tbody></tbody></table></div></div>
    <div class="modal-foot"><button type="button" class="btn" data-act="close">ปิด</button></div>`;
  document.body.appendChild(dlg);
  state.dayDialog = dlg;
  renderDayRows();
  const close = () => { dlg.close(); dlg.remove(); state.dayDialog = null; };
  dlg.addEventListener("cancel", (e) => { e.preventDefault(); close(); });
  dlg.addEventListener("click", async (e) => {
    const b = e.target.closest("button[data-act]");
    if (!b) return;
    if (b.dataset.act === "close") { close(); return; }
    const ev = state.events.find((x) => x.id === Number(b.closest("tr").dataset.id));
    if (!ev) return;
    if (b.dataset.act === "edit") {
      const panel = state.panels[ev.type];
      if (panel.dirty && panel.editingId !== ev.id) {
        const ok = await confirmBox("กรอบนี้มีข้อมูลที่ยังไม่บันทึก", "ต้องการทิ้งข้อมูลนั้นแล้วแก้ไขรายการนี้หรือไม่?", "แก้ไขรายการนี้", true);
        if (!ok) return;
      }
      close();
      panel.load(ev);
    } else await deleteEvent(ev);
  });
  dlg.showModal();
}

async function deleteEvent(ev) {
  const files = ev.attachments.length ? `<br>และไฟล์แนบ ${ev.attachments.length} ไฟล์` : "";
  const ok = await confirmBox("ยืนยันการลบรายการ",
    `ลบรายการ <b>${ev.stop_line ? `Stop Line ${fmtDate(ev.date)}–${fmtDate(ev.end_date)}` : ev.time_from ? `${esc(ev.time_from)}–${esc(ev.time_to)}` : ""} ${ev.cleaning ? "Monday Cleaning " : ""}${esc(ev.machine)}</b><br>"${esc(ev.problem.slice(0, 100))}"${files}<br><br>
     <span class="small">ข้อมูลที่ลบจะกู้คืนได้จากไฟล์ Backup เท่านั้น</span>`, "ลบรายการ", true);
  if (!ok) return;
  try {
    await api(`/api/events/${ev.id}`, { method: "DELETE" });
    const panel = state.panels[ev.type];
    if (panel.editingId === ev.id) panel.reset();
    toast("ลบรายการแล้ว", "ok");
    await loadEvents();
  } catch (err) { toast(err.message, "err"); }
}

// ---------- เริ่มต้น ----------
async function init() {
  try {
    [state.settings, state.master] = await Promise.all([loadSettings(), api("/api/master")]);
  } catch (err) { toast(err.message, "err"); return; }

  state.panels.problem = new EntryPanel("problem");
  state.panels.improve = new EntryPanel("improve");

  $("datePick").addEventListener("change", (e) => setDate(e.target.value));
  $("prevDay").addEventListener("click", () => setDate(addDays(state.date, -1)));
  $("nextDay").addEventListener("click", () => setDate(addDays(state.date, 1)));
  $("todayBtn").addEventListener("click", () => setDate(todayIso()));
  $("openDayList").addEventListener("click", openDayList);

  ["target", "output"].forEach((id) => {
    $(id).addEventListener("input", (e) => {
      state.dailyDirty = true;
      if (id === "target") state.targetAuto = false;
      setDailyState("dirty");
      e.target.classList.toggle("invalid", Number.isNaN(parseQty(e.target.value)));
      updateDiff();
    });
    $(id).addEventListener("blur", (e) => { const v = parseQty(e.target.value); if (v !== null && !Number.isNaN(v)) e.target.value = fmtInt(v); });
    $(id).addEventListener("keydown", (e) => { if (e.key === "Enter") saveDaily(); });
  });
  $("saveDaily").addEventListener("click", saveDaily);
  $("moveDay").addEventListener("click", moveDay);
  $("holiday").addEventListener("change", onHolidayChange);
  window.addEventListener("beforeunload", (e) => { if (anyDirty()) { e.preventDefault(); e.returnValue = ""; } });

  const fromUrl = new URLSearchParams(location.search).get("date");
  await setDate(/^\d{4}-\d{2}-\d{2}$/.test(fromUrl || "") ? fromUrl : todayIso(), { force: true });
}

document.addEventListener("DOMContentLoaded", init);
