/* Cortex Energy Studio. Vanilla custom element: live power flow, rate ribbon,
   24h chart, plan, daily history and house status. No build step, no libraries. */
const C = {
  solar: "#f9a825", grid: "#7e57c2", batt: "#26a69a", ev: "#42a5f5", home: "#ef6c00",
  peak: "#ef5350", shoulder: "#66bb6a", off_peak: "#ffa726",
};
const NS = "http://www.w3.org/2000/svg";
const TABS = [["now", "Now"], ["plan", "Plan"], ["history", "History"], ["house", "House"]];

const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fx = (v, n = 1) => (v === null || v === undefined || Number.isNaN(v) ? "–" : Number(v).toFixed(n));

class CortexStudio extends HTMLElement {
  constructor() {
    super();
    try { this._tab = localStorage.getItem("cortex-studio-tab") || "now"; } catch (e) { this._tab = "now"; }
    this._range = 14;
    this._series = null;
    this._daily = null;
    this._seriesAt = 0;
  }
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._build();
      this._load();
      this._timer = setInterval(() => this._load(), 30000);
    } else if (this._data && this._tab === "now" && Date.now() - (this._lastPaint || 0) > 1500) {
      this._lastPaint = Date.now();
      this._paintLive();
    }
  }
  set narrow(v) { this._narrow = v; }
  disconnectedCallback() { clearInterval(this._timer); }

  // ---- data -----------------------------------------------------------
  async _load() {
    try {
      this._data = await this._hass.callWS({ type: "cortex/overview" });
    } catch (e) {
      this._root.querySelector("#view").textContent = "Cortex is not loaded: " + (e.message || e.code);
      return;
    }
    const a = this._root.activeElement;
    if (a && (a.tagName === "INPUT" || a.tagName === "SELECT")) return;
    this._render();
    if (this._tab === "now" && Date.now() - this._seriesAt > 300000) this._loadSeries();
    if (this._tab === "history" && !this._daily) this._loadDaily();
  }

  _kw(id, invert = false) {
    const st = id && this._hass.states[id];
    if (!st) return null;
    const v = parseFloat(st.state);
    if (Number.isNaN(v)) return null;
    const unit = (st.attributes.unit_of_measurement || "kW").toLowerCase();
    const kw = unit === "w" ? v / 1000 : unit === "mw" ? v * 1000 : v;
    return invert ? -kw : kw;
  }
  _num(id) {
    const st = id && this._hass.states[id];
    const v = st ? parseFloat(st.state) : NaN;
    return Number.isNaN(v) ? null : v;
  }

  /** Live flows in kW. Conventions: grid + = import, battery + = charging. */
  _flows() {
    const s = this._data.studio || {};
    const pv = Math.max(this._kw(s.pv) ?? 0, 0);
    const grid = this._kw(s.grid, s.grid_invert) ?? 0;
    const batt = this._kw(s.battery, s.battery_invert) ?? 0;
    const ev = Math.max(this._kw(s.ev) ?? 0, 0);
    const load = Math.max(pv + grid - batt, 0);
    return { pv, grid, batt, ev, load, home: Math.max(load - ev, 0) };
  }

  async _loadSeries() {
    const s = this._data.studio || {};
    const ids = [s.pv, s.grid, s.battery, s.ev, s.soc].filter(Boolean);
    if (!ids.length) return;
    const end = new Date(), start = new Date(end.getTime() - 24 * 3600 * 1000);
    try {
      const res = await this._hass.callWS({
        type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
        entity_ids: ids, minimal_response: true, no_attributes: false, significant_changes_only: false,
      });
      const N = 288, step = (end - start) / N;
      const resample = (id, invert, scale) => {
        const rows = res[id] || [];
        const unit = ((rows[0] && rows[0].a && rows[0].a.unit_of_measurement) || "kW").toLowerCase();
        const k = scale === false ? 1 : unit === "w" ? 0.001 : 1;
        const out = new Array(N).fill(null);
        let j = 0, last = null;
        for (let i = 0; i < N; i++) {
          const t = start.getTime() + i * step;
          while (j < rows.length && (rows[j].lu ?? rows[j].lc) * 1000 <= t) {
            const v = parseFloat(rows[j].s); last = Number.isNaN(v) ? last : v * k; j++;
          }
          out[i] = last === null ? null : (invert ? -last : last);
        }
        return out;
      };
      const pv = resample(s.pv, false), grid = resample(s.grid, s.grid_invert),
        batt = resample(s.battery, s.battery_invert), ev = resample(s.ev, false),
        soc = resample(s.soc, false, false);
      const load = pv.map((p, i) => (p === null ? null : Math.max(p + (grid[i] ?? 0) - (batt[i] ?? 0), 0)));
      this._series = { start, end, pv, grid, batt, ev, soc, load };
      this._seriesAt = Date.now();
      if (this._tab === "now") this._paintChart();
    } catch (e) { /* history is optional */ }
  }

  async _loadDaily() {
    const s = this._data.studio || {};
    const ids = [s.day_pv, s.day_load, s.day_export, s.day_import].filter(Boolean);
    if (!ids.length) { this._daily = {}; return; }
    const start = new Date(Date.now() - this._range * 86400000);
    try {
      const res = await this._hass.callWS({
        type: "recorder/statistics_during_period", start_time: start.toISOString(),
        statistic_ids: ids, period: "day", types: ["max"],
      });
      this._daily = res;
      if (this._tab === "history") this._paintHistory();
    } catch (e) { this._daily = {}; }
  }

  // ---- frame ----------------------------------------------------------
  _build() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `<style>${CSS}</style>
      <header><h1>⚡ Energy Studio</h1><nav id="tabs"></nav><span id="clock" class="muted"></span></header>
      <main id="view"></main>`;
    const nav = this._root.querySelector("#tabs");
    nav.innerHTML = TABS.map(([k, l]) => `<button data-tab="${k}">${l}</button>`).join("");
    nav.querySelectorAll("button").forEach(b => b.onclick = () => this._go(b.dataset.tab));
  }
  _go(tab) {
    this._tab = tab;
    try { localStorage.setItem("cortex-studio-tab", tab); } catch (e) { /* ignore */ }
    this._render();
    if (tab === "now" && !this._series) this._loadSeries();
    if (tab === "history" && !this._daily) this._loadDaily();
  }

  _render() {
    const d = this._data; if (!d) return;
    this._root.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === this._tab));
    this._root.querySelector("#clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const view = this._root.querySelector("#view");
    view.innerHTML = ({ now: () => this._viewNow(), plan: () => this._viewPlan(), history: () => this._viewHistory(), house: () => this._viewHouse() })[this._tab]();
    ({ now: () => { this._paintLive(); this._paintChart(); }, plan: () => {}, history: () => { this._wireHistory(); this._paintHistory(); }, house: () => this._wireHouse() })[this._tab]();
  }

  // ---- NOW ------------------------------------------------------------
  _viewNow() {
    const e = this._data.energy;
    const hours = this._data.schedule.map(r => {
      const p = r.import <= 12 ? "shoulder" : r.import >= 40 ? "peak" : "off_peak";
      return `<i class="${r.hour === this._data.hour ? "cur" : ""}" style="background:${C[p]}" title="${r.hour}:00 · ${r.import}c import · ${r.feed_in}c feed-in"></i>`;
    }).join("");
    const nextT = new Date(e.next_change);
    return `
    <section class="grid">
      <div class="card hero wide">
        <div class="hero-top">
          <div><div class="muted">Right now</div>
            <div class="big"><span class="pill" style="background:${C[e.period]}">${e.period.replace("_", " ")}</span> ${fx(e.import_rate, 1)}<small>c/kWh</small></div></div>
          <div class="right"><div class="muted">Next: ${esc(e.next_period.replace("_", " "))}</div>
            <div class="big">${nextT.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}<small id="eta"></small></div></div>
        </div>
        <div class="ribbon" title="Import rate by hour">${hours}</div>
        <div class="ticks"><span>0</span><span>6</span><span>12</span><span>18</span><span>24</span></div>
      </div>
      <div class="card flow"><h2>Power flow</h2><div id="flow"></div></div>
      <div class="card"><h2>Storage</h2><div id="gauges" class="gauges"></div>
        <div class="muted" style="margin-top:8px">${esc(e.storage_summary || "")}</div></div>
      <div class="card wide"><h2>Last 24 hours <span class="legend"><b style="color:${C.solar}">■</b> solar <b style="color:${C.home}">■</b> load <b style="color:${C.grid}">■</b> grid <b style="color:${C.batt}">■</b> battery %</span></h2>
        <div id="chart" class="chart"><div class="muted">Loading history…</div></div></div>
      <div class="card stats" id="stats"></div>
    </section>`;
  }

  _paintLive() {
    const root = this._root, f = this._flows(), e = this._data.energy, s = this._data.studio || {};
    const eta = root.querySelector("#eta");
    if (eta) {
      const mins = Math.max(Math.round((new Date(e.next_change) - Date.now()) / 60000), 0);
      eta.textContent = ` in ${mins >= 60 ? Math.floor(mins / 60) + "h " + (mins % 60) + "m" : mins + "m"}`;
    }
    const flow = root.querySelector("#flow");
    if (flow) flow.innerHTML = flowSvg(f);
    const soc = this._num(s.soc), evsoc = this._num(s.ev_soc);
    const g = root.querySelector("#gauges");
    if (g) g.innerHTML = gauge(soc, "Battery", C.batt, f.batt > 0.05 ? "charging " + fx(f.batt) + " kW" : f.batt < -0.05 ? "discharging " + fx(-f.batt) + " kW" : "idle")
      + gauge(evsoc, "EV", C.ev, f.ev > 0.05 ? "charging " + fx(f.ev) + " kW" : e.ev_plugged ? "plugged in" : "unplugged");
    const st = root.querySelector("#stats");
    if (st) st.innerHTML = [
      ["Solar now", fx(f.pv) + " kW", C.solar], ["Home load", fx(f.load) + " kW", C.home],
      [f.grid >= 0 ? "Importing" : "Exporting", fx(Math.abs(f.grid)) + " kW", C.grid],
      ["Solar today", e.pv_today === null ? "–" : fx(e.pv_today, 0) + " kWh · " + e.solar_day, C.solar],
      ["Shortfall", e.pv_shortfall === null ? "–" : fx(e.pv_shortfall, 1) + " kWh", C.peak],
      ["Daily charge", "$" + fx(e.daily_charge, 2) + " → " + fx(e.export_to_cover, 2) + " kWh", C.shoulder],
    ].map(([l, v, c]) => `<div class="stat" style="border-color:${c}"><span class="muted">${l}</span><b>${v}</b></div>`).join("");
  }

  _paintChart() {
    const el = this._root.querySelector("#chart"), s = this._series;
    if (!el) return;
    if (!s) return;
    const W = 900, H = 240, L = 34, R = 34, T = 10, B = 24, N = 288;
    const x = i => L + (i / (N - 1)) * (W - L - R);
    const maxP = Math.max(1, ...s.pv.filter(v => v !== null), ...s.load.filter(v => v !== null), ...s.grid.map(v => Math.abs(v ?? 0))) * 1.1;
    const yP = v => T + (1 - v / maxP) * (H - T - B);
    const ySoc = v => T + (1 - v / 100) * (H - T - B);
    const line = (arr, y, color, w = 1.6, dash = "") => {
      let dstr = "", pen = false;
      arr.forEach((v, i) => { if (v === null) { pen = false; return; } dstr += (pen ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1); pen = true; });
      return `<path d="${dstr}" fill="none" stroke="${color}" stroke-width="${w}" stroke-linejoin="round" ${dash ? `stroke-dasharray="${dash}"` : ""}/>`;
    };
    const area = arr => {
      let d = "";
      arr.forEach((v, i) => { d += (i ? "L" : "M") + x(i).toFixed(1) + " " + yP(Math.max(v ?? 0, 0)).toFixed(1); });
      return `<path d="${d}L${x(N - 1)} ${yP(0)}L${x(0)} ${yP(0)}Z" fill="${C.solar}" opacity=".28"/>`;
    };
    let grid = "";
    for (let k = 0; k <= 4; k++) {
      const v = (maxP * k) / 4, y = yP(v);
      grid += `<line x1="${L}" x2="${W - R}" y1="${y}" y2="${y}" stroke="currentColor" opacity=".1"/><text x="${L - 4}" y="${y + 3}" text-anchor="end" class="ax">${v.toFixed(1)}</text>`;
    }
    for (let k = 0; k <= 100; k += 50) grid += `<text x="${W - R + 4}" y="${ySoc(k) + 3}" class="ax">${k}%</text>`;
    let hrs = "";
    for (let h = 0; h <= 24; h += 4) {
      const t = new Date(s.start.getTime() + (h / 24) * (s.end - s.start));
      const i = (h / 24) * (N - 1);
      hrs += `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" class="ax">${t.toLocaleTimeString([], { hour: "numeric" })}</text>`;
    }
    const nowx = x(N - 1);
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="24 hour energy chart">
      ${grid}${hrs}<line x1="${L}" x2="${W - R}" y1="${yP(0)}" y2="${yP(0)}" stroke="currentColor" opacity=".3"/>
      ${area(s.pv)}${line(s.pv, yP, C.solar, 1.4)}${line(s.load, yP, C.home, 2)}${line(s.grid, yP, C.grid, 1.4, "4 3")}${line(s.soc, ySoc, C.batt, 2)}
      <line x1="${nowx}" x2="${nowx}" y1="${T}" y2="${H - B}" stroke="currentColor" opacity=".3"/></svg>`;
  }

  // ---- PLAN -----------------------------------------------------------
  _viewPlan() {
    const d = this._data, e = d.energy, sch = d.schedule;
    const W = 900, H = 260, L = 34, T = 14, B = 26, n = sch.length, bw = (W - L - 10) / n;
    const maxR = Math.max(...sch.map(r => Math.max(r.import, r.feed_in)), 1) * 1.1;
    const y = v => T + (1 - v / maxR) * (H - T - B);
    let bars = "", pts = "", labels = "";
    sch.forEach((r, i) => {
      const p = r.import <= 12 ? "shoulder" : r.import >= 40 ? "peak" : "off_peak";
      const bx = L + i * bw;
      bars += `<rect x="${bx + 1}" y="${y(r.import)}" width="${bw - 2}" height="${H - B - y(r.import)}" rx="2" fill="${C[p]}" opacity="${r.hour === d.hour ? 1 : .78}"${r.hour === d.hour ? ' stroke="currentColor" stroke-width="2"' : ""}><title>${r.hour}:00 import ${r.import}c, feed-in ${r.feed_in}c</title></rect>`;
      pts += (i ? "L" : "M") + (bx + bw / 2).toFixed(1) + " " + y(r.feed_in).toFixed(1);
      if (r.hour % 3 === 0) labels += `<text x="${bx + bw / 2}" y="${H - 8}" text-anchor="middle" class="ax">${r.hour}</text>`;
    });
    let grid = "";
    for (let k = 0; k <= 4; k++) { const v = (maxR * k) / 4; grid += `<line x1="${L}" x2="${W - 10}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".1"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end" class="ax">${v.toFixed(0)}c</text>`; }
    const solarDay = e.solar_day === "low" ? C.peak : C.shoulder;
    const pvT = e.pv_today, pvM = e.pv_tomorrow, mx = Math.max(pvT || 0, pvM || 0, e.low_solar || 30, 1);
    const bar = (v, label) => `<div class="hbar"><span>${label}</span><div><i style="width:${v === null ? 0 : Math.min(v / mx, 1) * 100}%;background:${C.solar}"></i></div><b>${v === null ? "–" : fx(v, 0) + " kWh"}</b></div>`;
    return `<section class="grid">
      <div class="card wide"><h2>Today's rates <span class="legend"><b style="color:${C.shoulder}">■</b> shoulder <b style="color:${C.off_peak}">■</b> off-peak <b style="color:${C.peak}">■</b> peak <b style="color:#2e7d32">━</b> feed-in</span></h2>
        <div class="chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${bars}
        <path d="${pts}" fill="none" stroke="#2e7d32" stroke-width="2.5"/>${labels}</svg></div></div>
      <div class="card"><h2>Solar forecast</h2>${bar(pvT, "Today")}${bar(pvM, "Tomorrow")}
        <div class="row"><span>Low-solar line</span><b>${fx(e.low_solar, 0)} kWh</b></div>
        <div class="row"><span>Today is a</span><b style="color:${solarDay}">${esc(e.solar_day)} day</b></div>
        <div class="row"><span>Shortfall vs need</span><b>${e.pv_shortfall === null ? "–" : fx(e.pv_shortfall, 1) + " kWh"}</b></div></div>
      <div class="card"><h2>Evening export plan</h2>
        <div class="row"><span>Daily supply charge</span><b>$${fx(e.daily_charge, 2)}</b></div>
        <div class="row"><span>Export to cover it</span><b>${fx(e.export_to_cover, 2)} kWh</b></div>
        <div class="row"><span>Feed-in now</span><b>${fx(e.feed_in_rate, 0)}c</b></div>
        <div class="row"><span>Battery usable</span><b>${fx(e.battery_usable, 1)} kWh</b></div>
        <div class="row muted"><span>Auto top-up</span><span>${d.automation.topup ? "on" : "off"} · export ${d.automation.export ? "on" : "off"} · EV gate ${d.automation.ev_gate ? "on" : "off"}</span></div></div>
      <div class="card"><h2>Next change</h2>
        <div class="big">${esc(e.next_period.replace("_", " "))}</div>
        <div class="muted">at ${new Date(e.next_change).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</div>
        <div class="row"><span>Business day</span><b>${e.business_day ? "yes" : "no (no peak)"}</b></div>
        <div class="row"><span>High season</span><b>${e.high_season ? "yes" : "no"}</b></div></div>
    </section>`;
  }

  // ---- HISTORY --------------------------------------------------------
  _viewHistory() {
    return `<section class="grid"><div class="card wide">
      <h2>Daily energy <span class="seg">${[7, 14, 30].map(n => `<button data-range="${n}" class="${n === this._range ? "on" : ""}">${n}d</button>`).join("")}</span>
      <span class="legend"><b style="color:${C.solar}">■</b> solar <b style="color:${C.home}">■</b> used <b style="color:${C.grid}">■</b> imported <b style="color:${C.shoulder}">■</b> exported</span></h2>
      <div id="hchart" class="chart"><div class="muted">Loading…</div></div></div>
      <div class="card stats wide" id="htotals"></div></section>`;
  }
  _wireHistory() {
    this._root.querySelectorAll("[data-range]").forEach(b => b.onclick = () => {
      this._range = Number(b.dataset.range); this._daily = null; this._render(); this._loadDaily();
    });
  }
  _paintHistory() {
    const el = this._root.querySelector("#hchart"), tot = this._root.querySelector("#htotals");
    if (!el || !this._daily) return;
    const s = this._data.studio || {};
    const keys = [[s.day_pv, C.solar], [s.day_load, C.home], [s.day_import, C.grid], [s.day_export, C.shoulder]];
    const dayKey = t => new Date(t).toLocaleDateString("en-CA");
    const days = new Map();
    keys.forEach(([id], si) => {
      (this._daily[id] || []).forEach(r => {
        const k = dayKey(r.start); const row = days.get(k) || [0, 0, 0, 0];
        row[si] = r.max ?? 0; days.set(k, row);
      });
    });
    const rows = [...days.entries()].sort((a, b) => a[0].localeCompare(b[0]));
    if (!rows.length) { el.innerHTML = `<div class="muted">No daily statistics yet. They appear once Home Assistant has compiled a day of data.</div>`; return; }
    const W = 900, H = 260, L = 34, T = 10, B = 26, gw = (W - L - 6) / rows.length;
    const max = Math.max(...rows.flatMap(r => r[1]), 1) * 1.1, y = v => T + (1 - v / max) * (H - T - B);
    let bars = "", labels = "", grid = "";
    for (let k = 0; k <= 4; k++) { const v = (max * k) / 4; grid += `<line x1="${L}" x2="${W - 6}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".1"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end" class="ax">${v.toFixed(0)}</text>`; }
    rows.forEach(([day, vals], i) => {
      const gx = L + i * gw, bw = Math.max((gw - 4) / 4, 2);
      vals.forEach((v, j) => { bars += `<rect x="${gx + 2 + j * bw}" y="${y(v)}" width="${bw - 1}" height="${H - B - y(v)}" rx="1.5" fill="${keys[j][1]}"><title>${day}: ${v.toFixed(1)} kWh</title></rect>`; });
      if (rows.length <= 14 || i % 3 === 0) labels += `<text x="${gx + gw / 2}" y="${H - 8}" text-anchor="middle" class="ax">${day.slice(8)}/${day.slice(5, 7)}</text>`;
    });
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${grid}${bars}${labels}</svg>`;
    const sum = j => rows.reduce((a, r) => a + r[1][j], 0);
    const pv = sum(0), used = sum(1), imp = sum(2), exp = sum(3);
    const self = used > 0 ? Math.max(0, Math.min(100, (1 - imp / used) * 100)) : null;
    tot.innerHTML = [["Solar", fx(pv, 0) + " kWh", C.solar], ["Used", fx(used, 0) + " kWh", C.home],
      ["Imported", fx(imp, 0) + " kWh", C.grid], ["Exported", fx(exp, 0) + " kWh", C.shoulder],
      ["Self-sufficiency", self === null ? "–" : fx(self, 0) + "%", C.batt]]
      .map(([l, v, c]) => `<div class="stat" style="border-color:${c}"><span class="muted">${l}</span><b>${v}</b></div>`).join("");
  }

  // ---- HOUSE ----------------------------------------------------------
  _viewHouse() {
    const d = this._data, sec = d.security || { ok: true, issues: [] }, v = d.visitors || { log: [], parcels: 0, today: 0 };
    const list = (arr, fn, empty) => arr.length ? arr.map(fn).join("") : `<div class="muted">${empty}</div>`;
    return `<section class="grid">
      <div class="card"><h2>Security</h2>${sec.ok ? `<div class="big ok">All shut and locked</div>` : sec.issues.map(i => `<div class="row bad">${esc(i)}</div>`).join("")}
        <button id="seccheck">Check now</button></div>
      <div class="card"><h2>Visitors today: ${v.today} · parcels: ${v.parcels}</h2>
        ${list(v.log.slice(0, 5), x => `<div class="row"><span>${esc(x.kind)}: ${esc(x.text)}</span><span class="muted">${x.time.slice(11, 16)}</span></div>`, "No visitors yet.")}</div>
      <div class="card"><h2>House health</h2>${list(d.health, h => `<div class="row">${esc(h)}</div>`, "All clear")}</div>
      <div class="card"><h2>Suggestions</h2>${list(d.suggestions || [], x => `<div class="row"><span>💡 ${esc(x.text)}</span><button data-acc="${x.id}">Automate</button></div>`, "None yet.")}</div>
      <div class="card"><h2>Routines</h2>${list(d.routines || [], r => `<div class="row"><span>${esc(r.name)}</span><button data-run="${esc(r.name)}">Run</button></div>`, "No routines.")}</div>
      <div class="card wide"><h2>Timeline</h2>${list((d.timeline || []).slice(0, 14), x => `<div class="row"><span>${esc(x.text)}</span><span class="muted">${esc(x.kind)} · ${x.time.slice(5, 16).replace("T", " ")}</span></div>`, "No events yet.")}</div>
    </section>`;
  }
  _wireHouse() {
    const q = s => this._root.querySelectorAll(s);
    const act = async msg => { try { await this._hass.callWS({ type: "cortex/action", ...msg }); } catch (e) { /* shown on next load */ } this._load(); };
    q("[data-acc]").forEach(b => b.onclick = () => act({ action: "accept_suggestion", id: b.dataset.acc }));
    q("[data-run]").forEach(b => b.onclick = () => act({ action: "run_routine", id: b.dataset.run }));
    const c = this._root.querySelector("#seccheck"); if (c) c.onclick = () => act({ action: "security_check" });
  }
}

// ---- SVG pieces ---------------------------------------------------------
function gauge(pct, label, color, sub) {
  const r = 46, c = 2 * Math.PI * r, p = pct === null ? 0 : Math.max(0, Math.min(pct, 100)) / 100;
  return `<div class="gauge"><svg viewBox="0 0 120 120"><circle cx="60" cy="60" r="${r}" fill="none" stroke="currentColor" opacity=".12" stroke-width="10"/>
    <circle cx="60" cy="60" r="${r}" fill="none" stroke="${color}" stroke-width="10" stroke-linecap="round"
      stroke-dasharray="${c * p} ${c}" transform="rotate(-90 60 60)"/>
    <text x="60" y="64" text-anchor="middle" class="gv">${pct === null ? "–" : Math.round(pct) + "%"}</text></svg>
    <b>${label}</b><span class="muted">${esc(sub)}</span></div>`;
}

function flowSvg(f) {
  // Node centres in a 300x240 box.
  const N = { solar: [150, 30], grid: [34, 125], batt: [266, 125], ev: [150, 220], home: [150, 125] };
  const node = (k, label, kw, color, icon) =>
    `<g><circle cx="${N[k][0]}" cy="${N[k][1]}" r="${k === "home" ? 32 : 27}" style="fill:var(--card-background-color,#fff)"/>
     <circle cx="${N[k][0]}" cy="${N[k][1]}" r="${k === "home" ? 32 : 27}" fill="${color}" opacity=".16" stroke="${color}" stroke-width="2"/>
     <text x="${N[k][0]}" y="${N[k][1] - 4}" text-anchor="middle" class="ni">${icon}</text>
     <text x="${N[k][0]}" y="${N[k][1] + 11}" text-anchor="middle" class="nv">${kw}</text>
     <text x="${N[k][0]}" y="${N[k][1] + (k === "home" ? 46 : 41)}" text-anchor="middle" class="nl" style="paint-order:stroke;stroke:var(--card-background-color,#fff);stroke-width:3px">${label}</text></g>`;
  const link = (from, to, kw, color) => {
    if (Math.abs(kw) < 0.05) return `<line x1="${N[from][0]}" y1="${N[from][1]}" x2="${N[to][0]}" y2="${N[to][1]}" stroke="currentColor" opacity=".1" stroke-width="2"/>`;
    const rev = kw < 0;
    const a = rev ? to : from, b = rev ? from : to;
    const w = Math.min(2 + Math.abs(kw) * 0.9, 9), dur = Math.max(0.5, 2.6 - Math.abs(kw) * 0.18);
    return `<line x1="${N[a][0]}" y1="${N[a][1]}" x2="${N[b][0]}" y2="${N[b][1]}" stroke="${color}" stroke-width="${w}" stroke-linecap="round"
      stroke-dasharray="1 12" class="flow" style="animation-duration:${dur}s"/>`;
  };
  return `<svg viewBox="0 0 300 262" class="flowsvg">
    ${link("solar", "home", f.pv, C.solar)}${link("grid", "home", f.grid, C.grid)}${link("home", "batt", f.batt, C.batt)}${link("home", "ev", f.ev, C.ev)}
    ${node("solar", "Solar", fx(f.pv) + " kW", C.solar, "☀")}${node("grid", f.grid >= 0 ? "Grid in" : "Grid out", fx(Math.abs(f.grid)) + " kW", C.grid, "⚡")}
    ${node("batt", f.batt >= 0 ? "Charging" : "Discharging", fx(Math.abs(f.batt)) + " kW", C.batt, "🔋")}
    ${node("ev", "EV", fx(f.ev) + " kW", C.ev, "🚗")}${node("home", "Home", fx(f.home) + " kW", C.home, "🏠")}</svg>`;
}

const CSS = `
:host{display:block;box-sizing:border-box;min-height:100%;padding:16px 16px 40px;color:var(--primary-text-color);
  background:var(--primary-background-color);font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif)}
header{display:flex;align-items:center;gap:16px;flex-wrap:wrap;max-width:1300px;margin:0 auto 14px}
h1{font-size:22px;margin:0;font-weight:600}
h2{font-size:14px;margin:0 0 10px;font-weight:600;opacity:.85;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
nav{display:flex;gap:4px;background:var(--card-background-color);border-radius:999px;padding:4px;box-shadow:var(--ha-card-box-shadow,0 1px 3px #0002)}
nav button{border:0;background:transparent;color:var(--secondary-text-color);padding:6px 16px;border-radius:999px;cursor:pointer;font-size:14px}
nav button.on{background:var(--primary-color);color:var(--text-primary-color,#fff)}
#clock{margin-left:auto}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;max-width:1300px;margin:0 auto}
.card{background:var(--card-background-color);border-radius:16px;padding:16px;box-shadow:var(--ha-card-box-shadow,0 1px 3px #0002);min-width:0}
.wide{grid-column:1/-1}
.muted{opacity:.62;font-size:13px}
.big{font-size:30px;font-weight:600;line-height:1.2} .big small{font-size:14px;font-weight:400;opacity:.6;margin-left:4px}
.right{text-align:right}
.hero-top{display:flex;justify-content:space-between;gap:16px;flex-wrap:wrap}
.pill{display:inline-block;padding:3px 12px;border-radius:99px;color:#fff;font-size:14px;font-weight:500;vertical-align:middle;text-transform:capitalize}
.ribbon{display:flex;gap:2px;height:22px;margin-top:14px}
.ribbon i{flex:1;border-radius:4px;opacity:.7}
.ribbon i.cur{opacity:1;outline:2px solid var(--primary-text-color);outline-offset:1px}
.ticks{display:flex;justify-content:space-between;font-size:11px;opacity:.55;margin-top:3px}
.flowsvg{width:100%;max-height:300px} .ni{font-size:16px} .nv{font-size:10px;font-weight:600;fill:currentColor} .nl{font-size:9px;fill:currentColor;opacity:.65}
.flow{animation:dash linear infinite} @keyframes dash{to{stroke-dashoffset:-13}}
.gauges{display:flex;gap:16px;justify-content:space-around;flex-wrap:wrap}
.gauge{display:flex;flex-direction:column;align-items:center;gap:2px;width:130px} .gauge svg{width:110px}
.gv{font-size:24px;font-weight:600;fill:currentColor}
.chart{width:100%;height:240px} .chart svg{width:100%;height:100%;overflow:visible;color:var(--primary-text-color)}
.ax{font-size:10px;fill:currentColor;opacity:.55}
.legend{font-weight:400;font-size:12px;opacity:.8;margin-left:auto}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.stat{display:flex;flex-direction:column;border-left:4px solid;padding:4px 10px} .stat b{font-size:18px}
.row{display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--divider-color);align-items:center}
.row:last-child{border-bottom:0}
.hbar{display:grid;grid-template-columns:74px 1fr 70px;gap:8px;align-items:center;margin:8px 0}
.hbar div{height:12px;background:var(--divider-color);border-radius:6px;overflow:hidden} .hbar i{display:block;height:100%;border-radius:6px}
.seg{display:inline-flex;gap:2px} .seg button{border:1px solid var(--divider-color);background:transparent;color:inherit;padding:2px 10px;border-radius:8px;cursor:pointer}
.seg button.on{background:var(--primary-color);color:var(--text-primary-color,#fff);border-color:transparent}
button{cursor:pointer;border:0;border-radius:8px;padding:6px 12px;background:var(--primary-color);color:var(--text-primary-color,#fff)}
.ok{color:#66bb6a} .bad{color:#ef5350}
@media (max-width:640px){:host{padding:10px 10px 40px}.big{font-size:24px}.chart{height:200px}.legend{margin-left:0}}
`;
customElements.define("cortex-studio", CortexStudio);
