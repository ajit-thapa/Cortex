/* Cortex Energy Studio. Vanilla custom element: live power flow, rate ribbon,
   24h chart, plan, daily history and house status. No build step, no libraries. */
const C = {
  solar: "#f9a825", grid: "#7e57c2", batt: "#26a69a", ev: "#42a5f5", home: "#ef6c00",
  peak: "#ef5350", shoulder: "#66bb6a", off_peak: "#ffa726",
};
const NS = "http://www.w3.org/2000/svg";
const N = "sensor.neovolt_neovoltlocal_";
const E = {
  bt: [["Voltage", N + "battery_voltage", "mdi"], ["Current", N + "battery_current"], ["Power", N + "battery_power"], ["Health (SOH)", N + "combined_battery_soh"],
       ["Max cell temp", N + "battery_max_cell_temperature"], ["Min cell temp", N + "battery_min_cell_temperature"], ["Max cell V", N + "battery_max_cell_voltage"], ["Min cell V", N + "battery_min_cell_voltage"]],
  health: [["Inverter", N + "inverter_fault"], ["Battery", N + "battery_fault"], ["Protection", N + "battery_protection"], ["Grid freq", N + "grid_frequency"], ["Meter", "sensor.home_energy_purchased_today"]],
  life: [["Lifetime charged", N + "battery_charge_energy"], ["Lifetime discharged", N + "battery_discharge_energy"]],
  flows: [["Solar", N + "combined_pv_power", "#f2c744"], ["House", N + "combined_house_load", "#e8833a"], ["Battery", N + "combined_battery_power", "#7f5af0"], ["Grid", N + "grid_total_active_power", "#e45649"]],
  day: [["Solar", "sensor.neovolt_online_pv_generated_today", "#f2c744"], ["Import", "sensor.neovolt_online_grid_import_today", "#e45649"], ["Export", "sensor.neovolt_online_feed_in_today", "#50a14f"]],
  cyc: [["Charged", "sensor.neovolt_online_battery_charged_today", "#26a69a"], ["Discharged", "sensor.neovolt_online_battery_discharged_today", "#7e57c2"]],
  cost: [["Solar sold (period)", "sensor.agl_solar_sold_this_period"], ["Supply charge", "sensor.agl_supply_charge"], ["Recent cost total", "sensor.globird_energy_balance"],
         ["GloBird invoice", "sensor.globird_energy_latest_invoice"], ["Export total (period)", "sensor.agl_solar_feed_in_credit"], ["Consumption (period)", "sensor.agl_consumption_this_period"]],
  autos: ["automation.agl_plan_shoulder_grid_top_up_battery", "automation.agl_plan_evening_export_17_00_21_00_28c_fit", "automation.agl_plan_ev_charge_in_shoulder_window", "automation.agl_plan_ev_plug_in_gate_10_00_14_00_only", "automation.agl_plan_peak_guard_ev_and_battery"],
  nums: [["Battery capacity (kWh)", "input_number.system_battery_capacity"], ["BYD capacity (kWh)", "input_number.system_ev_battery_capacity"], ["PV capacity (kW)", "input_number.system_solar_inverter_size"],
         ["Wall connector (kW)", "input_number.system_ev_charger_power"], ["Round-trip efficiency", "input_number.system_battery_round_trip_efficiency"], ["Low-solar line (kWh)", "input_number.agl_low_solar_threshold"],
         ["BYD target SOC (%)", "input_number.byd_target_soc"], ["Shoulder (c)", "input_number.agl_plan_shoulder"], ["Off-peak (c)", "input_number.agl_plan_off_peak"],
         ["Peak high season (c)", "input_number.agl_plan_high_season_peak"], ["Peak low season (c)", "input_number.agl_plan_low_season_peak"], ["FiT evening (c)", "input_number.agl_plan_fit_evening"],
         ["FiT morning (c)", "input_number.agl_plan_fit_morning"], ["FiT off-peak (c)", "input_number.agl_plan_fit_off_peak"], ["Supply (c/day)", "input_number.agl_plan_supply_charge"]],
};
const EV = {
  img: "/api/image/serve/3215d9a31830fbbdda209ef2fddeae4b/original",
  soc: "sensor.byd_sealion_7_battery_level", power: "sensor.byd_sealion_7_battery_power",
  plug: "binary_sensor.byd_sealion_7_plug", charging: "binary_sensor.byd_sealion_7_charging",
  online: "binary_sensor.byd_sealion_7_online", remain: "sensor.byd_sealion_7_charge_remaining_time",
  locked: "binary_sensor.byd_sealion_7_locked", loc: "device_tracker.byd_sealion_7_location",
  full: "switch.byd_sealion_7_charge_to_full", sched: "switch.byd_sealion_7_schedule_enabled",
  daily: "switch.byd_sealion_7_repeat_daily", start: "time.byd_sealion_7_start_time", end: "time.byd_sealion_7_end_time",
  go: "button.byd_sealion_7_start_charging", poll: "button.byd_sealion_7_force_poll",
  cap: "input_number.system_ev_battery_capacity", kw: "input_number.system_ev_charger_power",
  wcStatus: "sensor.tesla_wall_connector_status", wcPower: "sensor.tesla_wall_connector_total_power",
  wcSession: "sensor.tesla_wall_connector_session_energy", wcV: "sensor.tesla_wall_connector_grid_voltage",
  wcA: ["sensor.tesla_wall_connector_phase_a_current", "sensor.tesla_wall_connector_phase_b_current", "sensor.tesla_wall_connector_phase_c_current"],
  wcT: [["Handle", "sensor.tesla_wall_connector_handle_temperature"], ["MCU", "sensor.tesla_wall_connector_mcu_temperature"], ["PCB", "sensor.tesla_wall_connector_pcb_temperature"]],
};
const TABS = [["now", "Now"], ["ev", "EV"], ["battery", "Battery"], ["plan", "Plan"], ["analytics", "Analytics"], ["history", "History"], ["house", "House"]];

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
    } else if (this._data && this._tab === "battery" && Date.now() - (this._lastPaint || 0) > 1500) {
      this._lastPaint = Date.now();
      this._battWidgets();
    } else if (this._data && this._tab === "ev" && Date.now() - (this._lastPaint || 0) > 1500) {
      this._lastPaint = Date.now();
      this._paintEv();
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
    if (this._tab === "ev" && Date.now() - (this._evAt || 0) > 300000) this._loadEv();
    if (this._tab === "plan" && Date.now() - (this._earnAt || 0) > 120000) this._loadEarn();
    if ((this._tab === "battery" || this._tab === "analytics") && Date.now() - ((this._moreAt || {})[this._tab] || 0) > 300000) this._loadMore(this._tab);
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
    if (tab === "ev" && Date.now() - (this._evAt || 0) > 300000) this._loadEv();
    if (tab === "plan" && Date.now() - (this._earnAt || 0) > 120000) this._loadEarn();
    if ((tab === "battery" || tab === "analytics") && Date.now() - ((this._moreAt || {})[tab] || 0) > 300000) this._loadMore(tab);
    if (tab === "history" && !this._daily) this._loadDaily();
  }

  _render() {
    const d = this._data; if (!d) return;
    this._root.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === this._tab));
    this._root.querySelector("#clock").textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const view = this._root.querySelector("#view");
    view.innerHTML = ({ now: () => this._viewNow(), ev: () => this._viewEv(), battery: () => this._viewBattery(), analytics: () => this._viewAnalytics(), plan: () => this._viewPlan(), history: () => this._viewHistory(), house: () => this._viewHouse() })[this._tab]();
    ({ now: () => { this._paintLive(); this._paintChart(); }, ev: () => { this._wireEv(); this._paintEv(); }, battery: () => { this._battWidgets(); this._paintMore("battery"); }, analytics: () => this._paintMore("analytics"), plan: () => { this._wirePlan(); this._wireExtras(); this._paintEarn(); }, history: () => { this._wireHistory(); this._paintHistory(); }, house: () => this._wireHouse() })[this._tab]();
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
      <div class="card"><h2>Storage</h2><div id="gauges" class="battstack"><div data-bhost="house"></div><div data-bhost="ev"></div></div>
        <div class="muted" style="margin-top:8px">${esc(e.storage_summary || "")}</div></div>
      <div class="card wide"><h2>Last 24 hours <span class="legend"><b style="color:${C.solar}">■</b> solar <b style="color:${C.home}">■</b> load <b style="color:${C.grid}">■</b> grid <b style="color:${C.batt}">■</b> battery %</span></h2>
        <div id="chart" class="chart"><div class="muted">Loading history…</div></div></div>
      <div class="card wide" id="stats"><div class="visgrid">
        <div class="vcell"><h3>Solar today</h3><div class="sunbar"><div class="sbtrack"><i class="sbfill"></i><u class="sbfc"></u><u class="sblow"></u></div>
          <div class="sblab"><span>☀ <b id="v-gen">–</b> kWh so far</span><span class="muted" id="v-fc"></span></div></div><div class="vsub" id="v-sun"></div></div>
        <div class="vcell"><h3>Solar shortfall</h3><svg viewBox="0 0 200 118" class="fuel">
          <path id="fz-g" fill="none" stroke="#66bb6a" stroke-width="16"/><path id="fz-a" fill="none" stroke="#ffa726" stroke-width="16"/><path id="fz-r" fill="none" stroke="#ef5350" stroke-width="16"/>
          <g id="needle" style="transform-origin:100px 100px;transform:rotate(-90deg)"><line x1="100" y1="100" x2="100" y2="34" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></g>
          <circle cx="100" cy="100" r="8" fill="currentColor"/></svg><div class="vsub" id="v-short"></div></div>
        <div class="vcell"><h3>Next rate change</h3><svg viewBox="0 0 120 120" class="cring"><circle cx="60" cy="60" r="48" fill="none" stroke="currentColor" opacity=".12" stroke-width="10"/>
          <circle id="cr" cx="60" cy="60" r="48" fill="none" stroke-width="10" stroke-linecap="round" transform="rotate(-90 60 60)" style="transition:stroke-dasharray 1s,stroke .5s"/>
          <text id="cr-t" x="60" y="62" text-anchor="middle" class="gv" style="font-size:20px"></text><text id="cr-s" x="60" y="80" text-anchor="middle" class="ax" style="font-size:10px"></text></svg><div class="vsub" id="v-next"></div></div>
      </div></div>
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
    this._battWidgets();
    this._paintVisuals();
  }

  _paintVisuals() {
    const r = this._root, q = id => r.querySelector(id); if (!q("#v-gen")) return;
    const e = this._data.energy, s = this._data.studio || {}, d = this._data;
    // solar today: generated vs forecast vs low-solar line
    const gen = this._num(s.day_pv) ?? 0, fc = e.pv_today, low = e.low_solar, mx = Math.max(fc || 0, gen, low || 0, 1) * 1.1;
    q(".sbfill").style.width = Math.min(gen / mx, 1) * 100 + "%";
    q(".sbfill").style.background = fc && gen >= fc ? C.shoulder : C.solar;
    q(".sbfc").style.left = fc === null || fc === undefined ? "-10%" : (fc / mx) * 100 + "%";
    q(".sblow").style.left = low ? (low / mx) * 100 + "%" : "-10%";
    q("#v-gen").textContent = fx(gen, 1);
    q("#v-fc").textContent = fc === null || fc === undefined ? "" : "forecast " + fx(fc, 0) + " kWh";
    q("#v-sun").innerHTML = `<span style="color:${e.solar_day === "low" ? C.peak : C.shoulder}">${esc(e.solar_day)} day</span> · line = low-solar ${fx(low, 0)} kWh`;
    // shortfall gauge
    const lo = -20, hi = 30, v = e.pv_shortfall, pt = (deg, rr = 80) => { const a = (180 - deg) * Math.PI / 180; return [(100 + rr * Math.cos(a)).toFixed(1), (100 - rr * Math.sin(a)).toFixed(1)]; };
    const arc = (a, b) => { const [x1, y1] = pt(a), [x2, y2] = pt(b); return `M${x1} ${y1} A80 80 0 0 1 ${x2} ${y2}`; };
    const deg = x => 180 * (x - lo) / (hi - lo);
    q("#fz-g").setAttribute("d", arc(0, deg(0))); q("#fz-a").setAttribute("d", arc(deg(0), deg(10))); q("#fz-r").setAttribute("d", arc(deg(10), 180));
    q("#needle").style.transform = `rotate(${-90 + (v === null || v === undefined ? 0 : 180 * (Math.max(lo, Math.min(hi, v)) - lo) / (hi - lo))}deg)`;
    q("#v-short").innerHTML = v === null || v === undefined ? "–" : v <= 0 ? `<b style="color:${C.shoulder}">${fx(-v, 1)} kWh surplus</b> · no top-up needed` : `<b style="color:${v > 10 ? C.peak : C.off_peak}">${fx(v, 1)} kWh short</b> · grid top-up likely`;
    // countdown ring
    const now = Date.now(), next = new Date(e.next_change).getTime(), sch = d.schedule || [];
    let h = d.hour, cur = (sch.find(x => x.hour === h) || {}).import, back = 0;
    while (back < 24 && (sch.find(x => x.hour === (h + 23) % 24) || {}).import === cur) { h = (h + 23) % 24; back++; }
    const st = new Date(); st.setHours(h, 0, 0, 0); if (st.getTime() > now) st.setDate(st.getDate() - 1);
    const frac = Math.max(0, Math.min((now - st.getTime()) / Math.max(next - st.getTime(), 1), 1)), mins = Math.max(Math.round((next - now) / 60000), 0);
    const c = 2 * Math.PI * 48, col = C[e.next_period] || C.ev;
    q("#cr").style.stroke = col; q("#cr").style.strokeDasharray = `${c * (1 - frac)} ${c}`;
    q("#cr-t").textContent = mins >= 60 ? Math.floor(mins / 60) + "h " + (mins % 60) + "m" : mins + "m";
    q("#cr-s").textContent = "left";
    q("#v-next").innerHTML = `→ <b style="color:${col}">${esc(e.next_period.replace("_", " "))}</b> at ${new Date(next).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  }

  _paintChart() {
    const el = this._root.querySelector("#chart"), s = this._series;
    if (!el) return;
    if (!s) return;
    const W = 900, H = 240, L = 34, R = 34, T = 10, B = 24, N = 288;
    const x = i => L + (i / (N - 1)) * (W - L - R);
    const vals = [...s.pv, ...s.load, ...s.grid].filter(v => v !== null);
    const hiP = Math.max(1, ...vals) * 1.1, loP = Math.min(0, ...vals) * 1.1, maxP = hiP;
    const clampY = y => Math.max(T, Math.min(H - B, y));
    const yP = v => clampY(T + (1 - (v - loP) / (hiP - loP || 1)) * (H - T - B));
    const ySoc = v => clampY(T + (1 - v / 100) * (H - T - B));
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
      const v = loP + ((hiP - loP) * k) / 4, y = yP(v);
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
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="24 hour energy chart" style="overflow:hidden">
      ${grid}${hrs}<line x1="${L}" x2="${W - R}" y1="${yP(0)}" y2="${yP(0)}" stroke="currentColor" opacity=".3"/>
      ${area(s.pv)}${line(s.pv, yP, C.solar, 1.4)}${line(s.load, yP, C.home, 2)}${line(s.grid, yP, C.grid, 1.4, "4 3")}${line(s.soc, ySoc, C.batt, 2)}
      <line x1="${nowx}" x2="${nowx}" y1="${T}" y2="${H - B}" stroke="currentColor" opacity=".3"/></svg>`;
  }

  // ---- EV -------------------------------------------------------------
  async _loadEv() {
    this._evAt = Date.now();
    const end = new Date(), start = new Date(end.getTime() - 24 * 3600 * 1000);
    try {
      const res = await this._hass.callWS({
        type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
        entity_ids: [EV.soc, EV.power], minimal_response: true, no_attributes: true, significant_changes_only: false,
      });
      const N = 144, step = (end - start) / N;
      const rs = id => {
        const rows = res[id] || [], out = new Array(N).fill(null); let j = 0, last = null;
        for (let i = 0; i < N; i++) {
          const t = start.getTime() + i * step;
          while (j < rows.length && (rows[j].lu ?? rows[j].lc) * 1000 <= t) { const v = parseFloat(rows[j].s); if (!Number.isNaN(v)) last = v; j++; }
          out[i] = last;
        }
        return out;
      };
      this._evSeries = { start, end, soc: rs(EV.soc), power: rs(EV.power) };
      if (this._tab === "ev") this._paintEv();
    } catch (e) { /* optional */ }
  }

  _evPlan() {
    const d = this._data, e = d.energy, sch = d.schedule || [];
    const soc = this._num(EV.soc) ?? 0, cap = this._num(EV.cap) ?? 82.5, kw = this._num(EV.kw) ?? 7.4;
    const target = this._evTarget ?? 80;
    const need = Math.max(target - soc, 0) * cap / 100;
    const f = this._flows(), surplus = Math.max(f.pv - f.home - Math.max(f.batt, 0), 0);
    const cheapest = sch.length ? Math.min(...sch.map(r => r.import)) : e.import_rate;
    const cheapHours = sch.filter(r => r.import === cheapest).map(r => r.hour);
    const now = e.import_rate;
    return { soc, cap, kw, target, need, hours: need / kw, now, cheapest, cheapHours,
      costNow: need * now / 100, costCheap: need * cheapest / 100, surplus, cover: Math.min(surplus / kw, 1) };
  }

  _viewEv() {
    const wcA = EV.wcA.map((id, i) => `<div class="phase"><span>${"ABC"[i]}</span><div><i data-a="${i}"></i></div><b data-av="${i}">–</b></div>`).join("");
    const temps = EV.wcT.map(([n], i) => `<div class="phase"><span>${n}</span><div><i data-t="${i}"></i></div><b data-tv="${i}">–</b></div>`).join("");
    return `<section class="grid">
      <div class="card evhero wide"><div class="stage">
          <div class="carbox"><img src="${EV.img}" alt="BYD Sealion 7" onerror="this.style.display='none'">
            <div class="carglow" id="ev-glow"></div>
            <div class="cartop"><span class="carname">BYD Sealion 7</span><span id="ev-state" class="pill"></span></div>
            <div class="carbar"><div class="barbg"><i id="ev-fill"></i><u id="ev-mark"></u></div>
              <div class="barlbl"><b id="ev-big"></b><span id="ev-sub" class="muted"></span></div></div></div>
          <div class="evside"><div data-bhost="ev"></div><div class="stats" id="ev-stats"></div></div></div></div>
      <div class="card"><h2>Charge planner <span class="muted">drag to set target</span></h2>
        <div class="big" id="ev-target-big"></div>
        <input type="range" id="ev-target" min="20" max="100" step="1" value="${this._evTarget ?? 80}" class="slider">
        <div class="seg" style="margin:8px 0">${[60, 80, 90, 100].map(v => `<button data-tgt="${v}">${v}%</button>`).join("")}</div>
        <div id="ev-plan"></div></div>
      <div class="card"><h2>Controls</h2>
        <div class="row"><span>Start charging now</span><button id="ev-go">Start</button></div>
        <div class="row"><span>Refresh car data</span><button id="ev-poll">Poll</button></div>
        <label class="row"><span>Charge to full</span><input type="checkbox" class="sw" data-sw="full"></label>
        <label class="row"><span>Schedule</span><input type="checkbox" class="sw" data-sw="sched"></label>
        <label class="row"><span>Repeat daily</span><input type="checkbox" class="sw" data-sw="daily"></label>
        <div class="row"><span>Window</span><span><input type="time" id="ev-start"> – <input type="time" id="ev-end"></span></div>
        <div class="seg" style="margin-top:8px"><button id="ev-cheap" title="Set the schedule to the cheapest hours">Cheapest hours</button><button id="ev-sun" title="Set the schedule to 10:00–14:00 shoulder">Shoulder 10–14</button></div>
        <div class="muted" id="ev-ctlmsg" style="margin-top:6px"></div></div>
      <div class="card wide"><h2>Last 24 hours <span class="legend"><b style="color:${C.ev}">■</b> charge level <b style="color:${C.solar}">━</b> power</span></h2>
        <div class="chart"><svg id="ev-chart" viewBox="0 0 900 220" preserveAspectRatio="none"></svg></div></div>
      <div class="card"><h2>Tesla Wall Connector <span id="wc-state" class="pill"></span></h2>
        <div class="stats" id="wc-stats"></div>
        <div class="muted" style="margin-top:10px">Phase current (A)</div>${wcA}
        <div class="muted" style="margin-top:10px">Temperature (°C)</div>${temps}</div>
    </section>`;
  }

  _wireEv() {
    const q = s => this._root.querySelector(s);
    const call = async (dom, svc, data) => {
      try { await this._hass.callService(dom, svc, data); q("#ev-ctlmsg").textContent = ""; }
      catch (e) { q("#ev-ctlmsg").textContent = "Failed: " + (e.message || e); }
    };
    const slider = q("#ev-target");
    slider.oninput = () => { this._evTarget = Number(slider.value); this._paintEv(); };
    this._root.querySelectorAll("[data-tgt]").forEach(b => b.onclick = () => { this._evTarget = Number(b.dataset.tgt); slider.value = this._evTarget; this._paintEv(); });
    q("#ev-go").onclick = () => call("button", "press", { entity_id: EV.go });
    q("#ev-poll").onclick = () => call("button", "press", { entity_id: EV.poll });
    this._root.querySelectorAll("[data-sw]").forEach(c => c.onchange = () =>
      call("switch", c.checked ? "turn_on" : "turn_off", { entity_id: EV[c.dataset.sw] }));
    const setT = (id, v) => v && call("time", "set_value", { entity_id: id, time: v.length === 5 ? v + ":00" : v });
    q("#ev-start").onchange = e => setT(EV.start, e.target.value);
    q("#ev-end").onchange = e => setT(EV.end, e.target.value);
    const preset = async (a, b) => {
      await call("time", "set_value", { entity_id: EV.start, time: a });
      await call("time", "set_value", { entity_id: EV.end, time: b });
      await call("switch", "turn_on", { entity_id: EV.sched });
    };
    q("#ev-sun").onclick = () => preset("10:00:00", "14:00:00");
    q("#ev-cheap").onclick = () => {
      const h = this._evPlan().cheapHours;
      if (!h.length) return;
      const pad = n => String(n % 24).padStart(2, "0") + ":00:00";
      preset(pad(Math.min(...h)), pad(Math.max(...h) + 1));
    };
  }

  _paintEv() {
    const q = s => this._root.querySelector(s); if (!q("#ev-state")) return;
    const st = id => this._hass.states[id];
    const on = id => st(id) && st(id).state === "on";
    const home = st(EV.loc) && st(EV.loc).state === "home";
    const pl = this._evPlan();
    const charging = on(EV.charging), plugged = on(EV.plug);
    const kwNow = (this._num(EV.power) ?? 0) / (((st(EV.power) || {}).attributes || {}).unit_of_measurement === "W" ? 1000 : 1);
    const pill = q("#ev-state");
    pill.textContent = charging ? "Charging" : plugged ? "Plugged in" : home ? "Home" : "Away";
    pill.style.background = charging ? C.shoulder : plugged ? C.off_peak : "#757575";
    this._battWidgets();
    const fill = q("#ev-fill"); if (fill) {
      fill.style.width = Math.max(0, Math.min(pl.soc, 100)) + "%"; fill.style.background = charging ? C.shoulder : C.ev;
      q("#ev-mark").style.left = pl.target + "%";
      q("#ev-big").textContent = Math.round(pl.soc) + "%";
      q("#ev-sub").textContent = `${fx(pl.soc * pl.cap / 100, 1)} kWh · target ${pl.target}%` + (charging ? ` · ${fx(kwNow)} kW` : "");
      q("#ev-glow").className = "carglow" + (charging ? " on" : "");
    }
    q("#ev-stats").innerHTML = [
      ["Power", charging ? fx(kwNow) + " kW" : "–", C.ev], ["Time left", (st(EV.remain) || {}).state && st(EV.remain).state !== "unknown" ? st(EV.remain).state : "–", C.shoulder],
      ["Solar surplus", fx(pl.surplus) + " kW", C.solar], ["Locked", on(EV.locked) ? "no" : "yes", on(EV.locked) ? C.peak : C.shoulder],
    ].map(([l, v, col]) => `<div class="stat" style="border-color:${col}"><span class="muted">${l}</span><b>${v}</b></div>`).join("");
    // planner
    q("#ev-target-big").innerHTML = `${pl.target}% <small>needs ${fx(pl.need, 1)} kWh · ${fx(pl.hours, 1)} h at ${fx(pl.kw)} kW</small>`;
    const solarPct = Math.round(pl.cover * 100);
    q("#ev-plan").innerHTML = `
      <div class="row"><span>Cost at today's ${fx(pl.now, 1)}c</span><b>$${fx(pl.costNow, 2)}</b></div>
      <div class="row"><span>Cost at cheapest ${fx(pl.cheapest, 1)}c${pl.cheapHours.length ? ` (${pl.cheapHours[0]}:00–${pl.cheapHours[pl.cheapHours.length - 1] + 1}:00)` : ""}</span><b class="ok">$${fx(pl.costCheap, 2)}</b></div>
      <div class="row"><span>You save by waiting</span><b>$${fx(pl.costNow - pl.costCheap, 2)}</b></div>
      <div class="row"><span>Solar covers right now</span><b>${solarPct}%</b></div>
      <div class="hbar" style="grid-template-columns:1fr"><div><i style="width:${solarPct}%;background:${C.solar}"></i></div></div>`;
    // controls (skip while the user is editing)
    this._root.querySelectorAll("[data-sw]").forEach(c => { c.checked = on(EV[c.dataset.sw]); });
    const hm = id => ((st(id) || {}).state || "").slice(0, 5);
    const s1 = q("#ev-start"), s2 = q("#ev-end");
    if (this._root.activeElement !== s1) s1.value = hm(EV.start);
    if (this._root.activeElement !== s2) s2.value = hm(EV.end);
    // wall connector
    const wc = st(EV.wcStatus), veh = on("binary_sensor.tesla_wall_connector_vehicle_connected");
    const wp = q("#wc-state"); wp.textContent = wc ? wc.state.replace(/_/g, " ") : "–"; wp.style.background = veh ? C.shoulder : "#757575";
    const wcKw = (this._kw(EV.wcPower) ?? 0);
    q("#wc-stats").innerHTML = [["Power", fx(wcKw) + " kW"], ["Session", fx(this._num(EV.wcSession), 1) + " kWh"], ["Grid", fx(this._num(EV.wcV), 0) + " V"], ["Vehicle", veh ? "connected" : "no"]]
      .map(([l, v]) => `<div class="stat" style="border-color:${C.ev}"><span class="muted">${l}</span><b>${v}</b></div>`).join("");
    EV.wcA.forEach((id, i) => { const a = this._num(id) ?? 0; q(`[data-a="${i}"]`).style.width = Math.min(a / 32 * 100, 100) + "%"; q(`[data-a="${i}"]`).style.background = C.ev; q(`[data-av="${i}"]`).textContent = fx(a, 0); });
    EV.wcT.forEach(([, id], i) => { const t = this._num(id) ?? 0; q(`[data-t="${i}"]`).style.width = Math.min(t / 90 * 100, 100) + "%"; q(`[data-t="${i}"]`).style.background = t > 70 ? C.peak : t > 55 ? C.off_peak : C.shoulder; q(`[data-tv="${i}"]`).textContent = fx(t, 0); });
    this._paintEvChart();
  }

  _paintEvChart() {
    const svg = this._root.querySelector("#ev-chart"), s = this._evSeries; if (!svg || !s) return;
    const W = 900, H = 220, L = 34, R = 34, T = 10, B = 24, N = s.soc.length;
    const x = i => L + (i / (N - 1)) * (W - L - R);
    const maxP = Math.max(...s.power.filter(v => v !== null), 1) * 1.1;
    const ys = v => T + (1 - v / 100) * (H - T - B), yp = v => T + (1 - v / maxP) * (H - T - B);
    const line = (arr, fn) => arr.map((v, i) => v === null ? "" : (i && arr[i - 1] !== null ? "L" : "M") + x(i).toFixed(1) + " " + fn(v).toFixed(1)).join("");
    const soc = line(s.soc, ys);
    let grid = "";
    for (let k = 0; k <= 4; k++) { const v = k * 25; grid += `<line x1="${L}" x2="${W - R}" y1="${ys(v)}" y2="${ys(v)}" stroke="currentColor" opacity=".1"/><text x="${L - 4}" y="${ys(v) + 3}" text-anchor="end" class="ax">${v}%</text>`; }
    let hrs = "";
    for (let k = 0; k <= 24; k += 4) { const t = new Date(s.start.getTime() + k / 24 * (s.end - s.start)); hrs += `<text x="${x(Math.min(k / 24 * (N - 1), N - 1))}" y="${H - 6}" text-anchor="middle" class="ax">${t.getHours()}:00</text>`; }
    svg.innerHTML = `${grid}${hrs}<path d="${soc} L${x(N - 1)} ${ys(0)} L${x(0)} ${ys(0)} Z" fill="${C.ev}" opacity=".15"/>
      <path d="${soc}" fill="none" stroke="${C.ev}" stroke-width="2.5"/><path d="${line(s.power, yp)}" fill="none" stroke="${C.solar}" stroke-width="2"/>
      <text x="${W - R + 4}" y="${yp(maxP) + 10}" class="ax">${maxP.toFixed(0)}</text>`;
  }

  _battWidgets() {
    const r = this._root, f = this._flows(), s = this._data.studio || {};
    r.querySelectorAll("[data-bhost]").forEach(h => { if (!h.querySelector(".batt")) h.innerHTML = battHTML(h.dataset.bhost, h.dataset.bhost === "house" ? "Home battery" : "BYD Sealion 7"); });
    const house = r.querySelector('[data-b="house"]'), ev = r.querySelector('[data-b="ev"]');
    if (house) {
      const soc = this._num(s.soc) ?? this._num(N + "combined_battery_soc") ?? this._num(N + "battery_soc"), cap = this._num("input_number.system_battery_capacity") ?? 50;
      const floor = this._num("number.neovolt_online_minimum_soc");
      battSet(house, { pct: soc, charging: f.batt > 0.05, discharging: f.batt < -0.05,
        sub: `${fx(soc === null ? null : soc * cap / 100, 1)} of ${fx(cap, 0)} kWh · ` + (f.batt > 0.05 ? "⚡ charging " + fx(f.batt) + " kW" : f.batt < -0.05 ? "▼ discharging " + fx(-f.batt) + " kW" : "idle"),
        marks: [{ pct: floor, color: C.peak, label: "Reserve" }] });
    }
    if (ev) {
      const soc = this._num(EV.soc) ?? this._num(s.ev_soc), cap = this._num(EV.cap) ?? 82.5;
      const chg = this._hass.states[EV.charging] && this._hass.states[EV.charging].state === "on";
      const kw = f.ev;
      battSet(ev, { pct: soc, charging: chg || kw > 0.05,
        sub: `${fx(soc === null ? null : soc * cap / 100, 1)} of ${fx(cap, 0)} kWh · ` + (chg || kw > 0.05 ? "⚡ charging " + fx(kw) + " kW" : (this._data.energy.ev_plugged ? "plugged in" : "unplugged")),
        marks: [{ pct: this._tab === "ev" && this._evTarget !== undefined ? this._evTarget : this._num("input_number.byd_target_soc"), color: C.home, label: "Target" }] });
    }
  }

  // ---- generic data loaders -------------------------------------------
  async _hist(ids, hours, n = 144, scale = {}) {
    const end = new Date(), start = new Date(end.getTime() - hours * 3600000);
    const res = await this._hass.callWS({ type: "history/history_during_period", start_time: start.toISOString(), end_time: end.toISOString(),
      entity_ids: ids, minimal_response: true, no_attributes: true, significant_changes_only: false }).catch(() => ({}));
    const step = (end - start) / n, out = { start, end };
    ids.forEach(id => {
      const rows = res[id] || [], a = new Array(n).fill(null); let j = 0, last = null;
      for (let i = 0; i < n; i++) {
        const t = start.getTime() + i * step;
        while (j < rows.length && (rows[j].lu ?? rows[j].lc) * 1000 <= t) { const v = parseFloat(rows[j].s); if (!Number.isNaN(v)) last = v * (scale[id] ?? 1); j++; }
        a[i] = last;
      }
      out[id] = a;
    });
    return out;
  }
  async _dayStats(ids, days) {
    const start = new Date(Date.now() - days * 86400000);
    const res = await this._hass.callWS({ type: "recorder/statistics_during_period", start_time: start.toISOString(), statistic_ids: ids, period: "day", types: ["max"] }).catch(() => ({}));
    const keys = [...new Set(ids.flatMap(id => (res[id] || []).map(r => new Date(r.start).toLocaleDateString("en-CA"))))].sort();
    const by = id => { const m = {}; (res[id] || []).forEach(r => { m[new Date(r.start).toLocaleDateString("en-CA")] = r.max; }); return keys.map(k => m[k] ?? 0); };
    return { days: keys.map(k => new Date(k + "T12:00").toLocaleDateString([], { weekday: "short" })), by };
  }
  _st(id) { return this._hass.states[id]; }
  _tile(label, id, color) {
    const st = this._st(id), v = st ? st.state : "–", u = st && st.attributes.unit_of_measurement ? " " + st.attributes.unit_of_measurement : "";
    const num = parseFloat(v), show = Number.isNaN(num) ? v : (Math.abs(num) >= 100 ? num.toFixed(0) : num.toFixed(Math.abs(num) < 10 ? 2 : 1)).replace(/\.?0+$/, "");
    return `<div class="stat" style="border-color:${color || C.ev}"><span class="muted">${esc(label)}</span><b>${esc(show)}<small>${esc(u)}</small></b></div>`;
  }
  async _loadMore(tab) {
    if (tab === "battery") {
      const f = E.flows.map(x => x[1]);
      const [fl, soc, tmp] = await Promise.all([this._hist(f, 24, 144), this._hist([N + "combined_battery_soc"], 48, 144), this._hist([N + "battery_max_cell_temperature", N + "battery_min_cell_temperature"], 24, 144)]);
      this._bt = { fl, soc, tmp };
    } else if (tab === "analytics") {
      const pvId = "sensor.sungrow_pv", fc = "sensor.pv_forecast_power_now", sun = "sensor.sun_solar_elevation";
      const [sol, dayS, cyc, eff, rate] = await Promise.all([
        this._hist([pvId, fc, sun], 14, 168, { [fc]: 0.001 }), this._dayStats(E.day.concat(E.cyc).map(x => x[1]), 8),
        Promise.resolve(null), this._hist(["sensor.neovolt_online_self_sufficiency", "sensor.neovolt_online_self_consumption"], 168, 84),
        this._hist(["sensor.agl_plan_import_rate", "sensor.agl_plan_feed_in_rate"], 48, 96)]);
      this._an = { sol, dayS, eff, rate };
    }
    this._moreAt = { ...(this._moreAt || {}), [tab]: Date.now() };
    if (this._tab === tab) this._paintMore(tab);
  }

  // ---- BATTERY ---------------------------------------------------------
  _viewBattery() {
    const soc = this._num(N + "combined_battery_soc") ?? this._num(N + "battery_soc");
    const cap = this._num("input_number.system_battery_capacity") ?? 50;
    return `<section class="grid">
      <div class="card"><h2>Home ESS</h2><div data-bhost="house"></div>
        <div class="stats" style="margin-top:12px">${E.life.map(([l, id]) => this._tile(l, id, C.batt)).join("")}</div></div>
      <div class="card"><h2>Monitor</h2><div class="stats">${E.bt.map(([l, id]) => this._tile(l, id, C.batt)).join("")}</div></div>
      <div class="card"><h2>System health</h2><div class="stats">${E.health.map(([l, id]) => {
        const st = this._st(id), ok = st && /^(ok|normal|none|0)$/i.test(st.state);
        return this._tile(l, id, st && (ok || !isNaN(parseFloat(st.state))) ? C.shoulder : C.peak); }).join("")}</div></div>
      <div class="card wide"><h2>Power flows today (W)</h2><div id="bt-flows"></div></div>
      <div class="card"><h2>Charge level 48h (%)</h2><div id="bt-soc"></div></div>
      <div class="card"><h2>Cell temperatures 24h (°C)</h2><div id="bt-tmp"></div></div>
    </section>`;
  }

  // ---- ANALYTICS -------------------------------------------------------
  _viewAnalytics() {
    const todays = [["Solar generated", "sensor.neovolt_online_pv_generated_today", C.solar], ["Exported", "sensor.neovolt_online_feed_in_today", C.shoulder], ["Imported", "sensor.neovolt_online_grid_import_today", C.peak],
      ["Battery charged", "sensor.neovolt_online_battery_charged_today", C.batt], ["Battery discharged", "sensor.neovolt_online_battery_discharged_today", "#7e57c2"], ["Battery level", "sensor.neovolt_online_soc", C.batt]];
    return `<section class="grid">
      <div class="card wide"><h2>Today</h2><div class="stats">${todays.map(([l, id, c]) => this._tile(l, id, c)).join("")}</div>
        <div class="row" style="margin-top:8px"><span>${esc((this._st("sensor.daily_summary") || {}).state || "")}</span><span class="muted">Best appliance time: <b>${esc((this._st("sensor.best_time_to_run_appliances") || {}).state || "–")}</b></span></div></div>
      <div class="card wide"><h2>Solar production vs forecast (kW)</h2><div id="an-sol"></div></div>
      <div class="card"><h2>Daily energy (kWh)</h2><div id="an-day"></div></div>
      <div class="card"><h2>Battery cycling (kWh/day)</h2><div id="an-cyc"></div></div>
      <div class="card"><h2>Self-sufficiency & self-consumption (%)</h2><div id="an-eff"></div></div>
      <div class="card"><h2>AGL rates 48h</h2><div id="an-rate"></div></div>
      <div class="card wide"><h2>Cost tracking</h2><div class="stats">${E.cost.map(([l, id]) => this._tile(l, id, C.off_peak)).join("")}</div></div>
    </section>`;
  }

  _paintMore(tab) {
    const q = id => this._root.querySelector(id), put = (id, h) => { const el = q(id); if (el) el.innerHTML = h; };
    if (tab === "battery" && this._bt) {
      const { fl, soc, tmp } = this._bt;
      put("#bt-flows", lineChart(E.flows.map(([n, id, c], i) => ({ name: n, color: c, data: fl[id], area: i === 0 })), { start: fl.start, end: fl.end, h: 240, w: 1100 }));
      put("#bt-soc", lineChart([{ name: "SOC", color: C.batt, data: soc[N + "combined_battery_soc"], area: true }], { min: 0, max: 100, start: soc.start, end: soc.end }));
      put("#bt-tmp", lineChart([{ name: "Max cell", color: "#e8833a", data: tmp[N + "battery_max_cell_temperature"] }, { name: "Min cell", color: "#4a90d9", data: tmp[N + "battery_min_cell_temperature"] }], { start: tmp.start, end: tmp.end }));
    }
    if (tab === "analytics" && this._an) {
      const { sol, dayS, eff, rate } = this._an, ids = ["sensor.sungrow_pv", "sensor.pv_forecast_power_now"];
      put("#an-sol", lineChart([{ name: "Actual PV", color: "#FFB300", data: sol[ids[0]], area: true }, { name: "Forecast", color: "#00B0FF", data: sol[ids[1]] }], { start: sol.start, end: sol.end, min: 0, h: 220, w: 1100 }));
      put("#an-day", barChart(dayS.days, E.day.map(([n, id, c]) => ({ name: n, color: c, data: dayS.by(id) }))));
      put("#an-cyc", barChart(dayS.days, E.cyc.map(([n, id, c]) => ({ name: n, color: c, data: dayS.by(id) }))));
      put("#an-eff", lineChart([{ name: "Self-sufficiency", color: "#0f9d58", data: eff["sensor.neovolt_online_self_sufficiency"] }, { name: "Self-consumption", color: "#12b5cb", data: eff["sensor.neovolt_online_self_consumption"] }], { min: 0, max: 100, start: eff.start, end: eff.end, days: true }));
      put("#an-rate", lineChart([{ name: "Import", color: "#e45649", data: rate["sensor.agl_plan_import_rate"] }, { name: "Feed-in", color: "#50a14f", data: rate["sensor.agl_plan_feed_in_rate"] }], { step: true, min: 0, start: rate.start, end: rate.end }));
    }
  }

  // ---- PLAN extras: money, rate windows, automations, settings ---------
  _planExtras() {
    const n = id => this._num(id) ?? 0, gen = n("sensor.neovolt_online_pv_generated_today"), exp = n("sensor.neovolt_online_feed_in_today"), imp = n("sensor.neovolt_online_grid_import_today");
    const p = n("sensor.agl_plan_import_rate"), f = n("sensor.agl_plan_feed_in_rate"), self = Math.max(gen - exp, 0);
    const net = self * p + exp * f - imp * p, h = new Date().getHours(), bd = this._data.energy.business_day, high = this._data.energy.high_season;
    const v = id => fx(this._num(id), 2), now = (a, b) => (h >= a && h < b ? '<b class="ok">◀ now</b>' : "");
    const pk = high ? "input_number.agl_plan_high_season_peak" : "input_number.agl_plan_low_season_peak";
    return `<div class="card"><h2>Money today</h2>
        <div class="row"><span>Solar used on-site (${fx(self, 1)} kWh)</span><b>$${fx(self * p, 2)} avoided</b></div>
        <div class="row"><span>Exported (${fx(exp, 1)} kWh)</span><b>$${fx(exp * f, 2)} earned</b></div>
        <div class="row"><span>Imported (${fx(imp, 1)} kWh)</span><b>$${fx(imp * p, 2)} spent</b></div>
        <div class="row"><span><b>Net benefit</b></span><b class="${net >= 0 ? "ok" : "bad"}">$${fx(net, 2)}</b></div>
        <div class="muted">Indicative: uses the current rate for all kWh.</div></div>
      <div class="card"><h2>Rate windows</h2>
        <div class="row"><span>10–14 Shoulder</span><span><b>${v("input_number.agl_plan_shoulder")}c</b> ${now(10, 14)}</span></div>
        <div class="row"><span>14–16 Off peak</span><span><b>${v("input_number.agl_plan_off_peak")}c</b> ${now(14, 16)}</span></div>
        <div class="row"><span>16–20 ${bd ? "Peak" : "Off peak (no peak today)"}</span><span><b>${bd ? v(pk) : v("input_number.agl_plan_off_peak")}c</b> ${now(16, 20)}</span></div>
        <div class="row"><span>20–10 Off peak</span><span><b>${v("input_number.agl_plan_off_peak")}c</b> ${h >= 20 || h < 10 ? '<b class="ok">◀ now</b>' : ""}</span></div>
        <div class="row"><span>FiT 07–08 / 17–21</span><span><b>${v("input_number.agl_plan_fit_morning")}c / ${v("input_number.agl_plan_fit_evening")}c</b></span></div>
        <div class="muted">Supply ${v("input_number.agl_plan_supply_charge")} c/day · ${high ? "high" : "low"} season.</div></div>
      <div class="card"><h2>Automations</h2>${E.autos.map(id => { const st = this._st(id); return st ? `<label class="row"><span>${esc(st.attributes.friendly_name || id)}</span><input type="checkbox" class="sw" data-auto="${id}" ${st.state === "on" ? "checked" : ""}></label>` : ""; }).join("") || '<div class="muted">None found.</div>'}</div>
      <div class="card"><h2>System settings <span class="muted">edit a value, press Enter</span></h2>${E.nums.map(([l, id]) => { const st = this._st(id); return st ? `<div class="row"><span>${esc(l)}</span><input type="number" class="num" data-num="${id}" value="${esc(st.state)}" step="${st.attributes.step || "any"}" min="${st.attributes.min ?? ""}" max="${st.attributes.max ?? ""}"></div>` : ""; }).join("")}</div>`;
  }
  _wireExtras() {
    const call = (d, sv, data) => this._hass.callService(d, sv, data).catch(() => {});
    this._root.querySelectorAll("[data-auto]").forEach(c => c.onchange = () => call("automation", c.checked ? "turn_on" : "turn_off", { entity_id: c.dataset.auto }));
    this._root.querySelectorAll("[data-num]").forEach(i => i.onchange = () => { const v = parseFloat(i.value); if (!Number.isNaN(v)) call("input_number", "set_value", { entity_id: i.dataset.num, value: v }); });
  }

  // ---- HOUSEKEEPING extras --------------------------------------------
  _houseExtras() {
    const ups = Object.entries(this._hass.states).filter(([k, s]) => k.startsWith("update.") && s.state === "on").map(([k, s]) => s.attributes.friendly_name || k);
    const w = this._st("weather.forecast_ingleburn");
    return `<div class="card"><h2>Housekeeping</h2>
        <div class="row"><span>Updates pending</span><b>${ups.length ? esc(ups.join(", ")) : "None"}</b></div>
        <div class="row"><span>Internet speed</span><b>${esc((this._st("sensor.fast_com_download") || {}).state || "–")} Mbps</b></div>
        <div class="row"><span>Solar exported at battery full</span><b>${esc((this._st("input_number.solar_exported_at_battery_full") || {}).state || "–")}</b></div>
        ${w ? `<div class="row"><span>Weather</span><b>${esc(w.state.replace(/-/g, " "))} ${w.attributes.temperature ?? ""}°</b></div>` : ""}</div>`;
  }

  // ---- evening export plan: earnings vs daily supply charge -------------
  async _loadEarn() {
    const id = (this._data.studio || {}).day_export; if (!id) return;
    this._earnAt = Date.now();
    const start = new Date(); start.setHours(0, 0, 0, 0);
    const res = await this._hass.callWS({ type: "history/history_during_period", start_time: start.toISOString(), end_time: new Date().toISOString(),
      entity_ids: [id], minimal_response: true, no_attributes: true, significant_changes_only: false }).catch(() => ({}));
    const sch = this._data.schedule || [], rate = h => (sch.find(r => r.hour === h) || { feed_in: 0 }).feed_in;
    const buckets = {}; let prev = null, kwh = 0, earned = 0;
    (res[id] || []).forEach(r => {
      const v = parseFloat(r.s); if (Number.isNaN(v)) return;
      const t = new Date((r.lu ?? r.lc) * 1000);
      if (prev !== null && v > prev && v - prev < 5) { const d = v - prev, c = rate(t.getHours()); buckets[c] = (buckets[c] || 0) + d; kwh += d; earned += d * c / 100; }
      prev = v;
    });
    this._earn = { buckets, kwh, earned };
    if (this._tab === "plan") this._paintEarn();
  }
  _paintEarn() {
    const el = this._root.querySelector("#earn"), d = this._data; if (!el || !d) return;
    const e = d.energy, m = this._earn || { buckets: {}, kwh: 0, earned: 0 };
    const daily = e.daily_charge ?? 0, sch = d.schedule || [], top = Math.max(...sch.map(r => r.feed_in), 0) || e.feed_in_rate || 1;
    const left = Math.max(daily - m.earned, 0), covered = left <= 0.004, pct = daily ? Math.min(m.earned / daily, 1) * 100 : 0;
    const needKwh = left / (top / 100), expKw = Math.max(-this._flows().grid, 0), nowRate = e.feed_in_rate ?? 0;
    const rows = Object.keys(m.buckets).map(Number).sort((a, b) => b - a).map(c =>
      `<div class="row"><span class="muted">${fx(c, 0)}c × ${fx(m.buckets[c], 1)} kWh</span><b>$${fx(m.buckets[c] * c / 100, 2)}</b></div>`).join("");
    const usable = e.battery_usable ?? 0, can = usable >= needKwh;
    el.innerHTML = `
      <div class="hero-top"><div class="big">$${fx(m.earned, 2)}<small>of $${fx(daily, 2)} supply charge</small></div>
        <span class="pill" style="background:${covered ? C.shoulder : C.off_peak};align-self:center">${covered ? "covered ✓" : "$" + fx(left, 2) + " to go"}</span></div>
      <div class="hbar" style="grid-template-columns:1fr;margin:10px 0"><div style="height:14px"><i style="width:${pct}%;background:${covered ? C.shoulder : C.off_peak}"></i></div></div>
      <div class="row"><span>${covered ? "Surplus earned" : "Left to cover"}</span><b>${covered ? "$" + fx(m.earned - daily, 2) : "$" + fx(left, 2) + " ≈ " + fx(needKwh, 2) + " kWh at " + fx(top, 0) + "c"}</b></div>
      <div class="row"><span>Feed-in now</span><b>${fx(nowRate, 0)}c</b></div>
      <div class="row"><span>Exporting now</span><b>${expKw > 0.05 ? fx(expKw) + " kW → $" + fx(expKw * nowRate / 100, 2) + "/h" : "not exporting"}</b></div>
      <div class="row"><span>Exported today</span><b>${fx(m.kwh, 1)} kWh</b></div>${rows}
      ${covered ? "" : `<div class="row"><span>Battery usable</span><b class="${can ? "ok" : "bad"}">${fx(usable, 1)} kWh ${can ? "· enough" : "· short by " + fx(needKwh - usable, 1)}</b></div>`}
      <div class="muted">Earnings = each kWh exported × the feed-in rate at that hour.</div>`;
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
    const ap = d.autopilot || { mode: "off", decisions: [] };
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
      <div class="card"><h2>Evening export plan</h2><div id="earn"><div class="muted">Loading…</div></div></div>
      <div class="card wide"><h2>Autopilot <span class="pill" style="background:${ap.mode === "auto" ? C.shoulder : ap.mode === "shadow" ? C.off_peak : "#757575"}">${esc(ap.mode)}</span>
        <span class="seg"><button id="ap-topup">Plan top-up</button><button id="ap-export">Plan export</button></span></h2>
        ${(ap.decisions || []).length ? ap.decisions.map(x => `<div class="row"><span><b>${x.window === "topup" ? "Top-up" : "Export"}</b> ${x.do ? "✅" : "⏸"} ${esc(x.reason)}
          ${x.do ? `<span class="muted">· ${x.kw} kW ${x.window === "topup" ? "to " + x.target_soc : "to floor " + x.floor_soc}%</span>` : ""}
          ${x.outcome ? `<br><span class="muted">${esc(x.outcome)}</span>` : ""}</span>
          <span class="muted">${esc(x.source)} · ${esc(x.result)} · ${x.time.slice(5, 16).replace("T", " ")}</span></div>`).join("")
          : `<div class="muted">No decisions yet. Autopilot plans at the start of the shoulder window and the evening feed-in window.</div>`}</div>
      <div class="card"><h2>Next change</h2>
        <div class="big">${esc(e.next_period.replace("_", " "))}</div>
        <div class="muted">at ${new Date(e.next_change).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" })}</div>
        <div class="row"><span>Business day</span><b>${e.business_day ? "yes" : "no (no peak)"}</b></div>
        <div class="row"><span>High season</span><b>${e.high_season ? "yes" : "no"}</b></div></div>
      ${this._planExtras()}
    </section>`;
  }

  _wirePlan() {
    const act = async action => { try { await this._hass.callWS({ type: "cortex/action", action }); } catch (e) { /* shown next load */ } this._load(); };
    const t = this._root.querySelector("#ap-topup"), x = this._root.querySelector("#ap-export");
    if (t) t.onclick = () => act("autopilot_topup");
    if (x) x.onclick = () => act("autopilot_export");
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
      ${this._houseExtras()}
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

// ---- generic charts ------------------------------------------------------
function lineChart(series, o = {}) {
  const W = o.w || 520, H = o.h || 200, L = 40, R = 12, T = 10, B = 22;
  const all = series.flatMap(s => s.data.filter(v => v !== null));
  if (!all.length) return `<div class="muted" style="padding:20px">No data yet.</div>`;
  const lo = o.min ?? Math.min(0, ...all), hi = o.max ?? (Math.max(...all, 1) * 1.08), n = series[0].data.length;
  const x = i => L + (i / Math.max(n - 1, 1)) * (W - L - R), y = v => T + (1 - (v - lo) / (hi - lo || 1)) * (H - T - B);
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = lo + (hi - lo) * k / 4; g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".1"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end" class="ax">${Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1)}</text>`; }
  let lab = "";
  if (o.start) for (let k = 0; k <= 6; k++) { const t = new Date(o.start.getTime() + (o.end - o.start) * k / 6); lab += `<text x="${x(k / 6 * (n - 1))}" y="${H - 6}" text-anchor="middle" class="ax">${o.days ? t.toLocaleDateString([], { weekday: "short" }) : t.getHours() + ":00"}</text>`; }
  const path = (d, step) => d.map((v, i) => v === null ? "" : (i && d[i - 1] !== null ? (step ? `H${x(i).toFixed(1)}V` : "L") : "M") + (step && i && d[i - 1] !== null ? y(v).toFixed(1) : x(i).toFixed(1) + " " + y(v).toFixed(1))).join("");
  const body = series.map(s => {
    const d = path(s.data, o.step);
    const area = s.area ? `<path d="${d} L${x(n - 1)} ${y(Math.max(lo, 0))} L${x(0)} ${y(Math.max(lo, 0))} Z" fill="${s.color}" opacity=".16"/>` : "";
    return area + `<path d="${d}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round"/>`;
  }).join("");
  return `<div class="chart" style="height:${H}px"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}${lab}${body}</svg></div>${legend(series)}`;
}
function legend(series) { return `<div class="lg">${series.map(s => `<span><b style="color:${s.color}">■</b> ${esc(s.name)}</span>`).join("")}</div>`; }
function barChart(days, series, o = {}) {
  const W = o.w || 520, H = o.h || 200, L = 40, R = 12, T = 10, B = 22, n = days.length;
  if (!n) return `<div class="muted" style="padding:20px">No data yet.</div>`;
  const hi = Math.max(...series.flatMap(s => s.data.map(v => v || 0)), 1) * 1.1, gw = (W - L - R) / n, bw = gw / (series.length + 1);
  const y = v => T + (1 - v / hi) * (H - T - B);
  let g = "";
  for (let k = 0; k <= 4; k++) { const v = hi * k / 4; g += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="currentColor" opacity=".1"/><text x="${L - 4}" y="${y(v) + 3}" text-anchor="end" class="ax">${v.toFixed(0)}</text>`; }
  const bars = days.map((d, i) => series.map((s, j) => { const v = s.data[i] || 0; return `<rect x="${L + i * gw + bw / 2 + j * bw}" y="${y(v)}" width="${bw - 1}" height="${H - B - y(v)}" rx="2" fill="${s.color}"><title>${s.name} ${v.toFixed(1)}</title></rect>`; }).join("")
    + `<text x="${L + i * gw + gw / 2}" y="${H - 6}" text-anchor="middle" class="ax">${d}</text>`).join("");
  return `<div class="chart" style="height:${H}px"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}${bars}</svg></div>${legend(series)}`;
}

// ---- battery visuals: Neovolt ESS tower and SUV, optional PNG overrides --------
const levelColor = p => (p === null ? "#757575" : p < 20 ? C.peak : p < 40 ? C.off_peak : C.shoulder);
// Drop transparent PNGs here to replace the drawings: /config/www/cortex/<name>.png
const BIMG = { house: "/local/cortex/neovolt-ess.png", ev: "/local/cortex/byd-sealion-7.png" };
const CAR_BODY = "M26 132C20 126 18 106 21 94C24 86 38 80 62 72C100 52 142 26 192 18C222 14 262 14 294 22C324 30 348 58 364 72C382 78 410 86 420 98C426 106 426 120 422 132L416 140L34 140Z";
const CAR_GLASS = "M348 70C332 44 312 33 288 27L196 26C160 30 120 52 88 70Z";
function carSvg(k) {
  const wheel = x => `<circle cx="${x}" cy="116" r="40" style="fill:var(--card-background-color,#222)"/><circle cx="${x}" cy="116" r="34" fill="#17181a"/><circle cx="${x}" cy="116" r="34" fill="none" stroke="#444" stroke-width="2"/>
      <g class="spin" style="transform-origin:${x}px 116px">${Array.from({ length: 10 }, (_, i) => { const a = i * 36 * Math.PI / 180; return `<line x1="${x + 7 * Math.cos(a)}" y1="${116 + 7 * Math.sin(a)}" x2="${x + 26 * Math.cos(a)}" y2="${116 + 26 * Math.sin(a)}" stroke="#bdbdbd" stroke-width="${i % 2 ? 2 : 4}" stroke-linecap="round"/>`; }).join("")}</g>
      <circle cx="${x}" cy="116" r="27" fill="none" stroke="#e0e0e0" stroke-width="3"/><circle cx="${x}" cy="116" r="6" fill="#9e9e9e"/>`;
  return `<svg viewBox="0 0 440 170" class="battsvg car">
    <defs><clipPath id="cb-${k}"><path d="${CAR_BODY}"/></clipPath><clipPath id="cf-${k}"><rect class="fclip" x="18" y="8" width="0" height="140"/></clipPath>
      <linearGradient id="cg-${k}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset=".45" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".3"/></linearGradient>
      <linearGradient id="cs-${k}"><stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".6"/><stop offset="1" stop-color="#fff" stop-opacity="0"/></linearGradient>
      <linearGradient id="gl-${k}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#cfe8ff" stop-opacity=".55"/><stop offset="1" stop-color="#1b2a38" stop-opacity=".85"/></linearGradient></defs>
    <ellipse class="cglow" cx="222" cy="156" rx="190" ry="11"/>
    <line class="cflow" x1="0" x2="215" y1="160" y2="160" stroke-width="3" stroke-dasharray="6 10" stroke-linecap="round"/>
    <g clip-path="url(#cb-${k})"><path d="${CAR_BODY}" fill="currentColor" opacity=".13"/>
      <rect class="bfill" x="18" y="8" width="0" height="140"/><rect class="bfill" style="fill:url(#cg-${k})" x="18" y="8" width="0" height="140"/>
      <g clip-path="url(#cf-${k})"><rect class="bsheen" x="-90" y="8" width="90" height="140" fill="url(#cs-${k})"/></g></g>
    <path d="${CAR_GLASS}" fill="url(#gl-${k})"/><line x1="214" x2="214" y1="26" y2="70" stroke="currentColor" stroke-opacity=".5" stroke-width="3"/>
    <path d="M26 132C20 126 18 106 21 94C24 86 38 80 62 72C100 52 142 26 192 18C222 14 262 14 294 22C324 30 348 58 364 72C382 78 410 86 420 98C426 106 426 120 422 132L416 140L34 140Z" fill="none" stroke="currentColor" stroke-width="3" opacity=".65" stroke-linejoin="round"/>
    <path d="M214 70C212 90 212 112 214 128M302 70C300 90 300 112 302 128" fill="none" stroke="currentColor" stroke-opacity=".4" stroke-width="2"/>
    <path d="M196 84h14M284 84h14" stroke="currentColor" stroke-opacity=".6" stroke-width="3" stroke-linecap="round"/>
    <path d="M356 70l16 2c3 1 3 5-1 6l-14 1z" fill="currentColor" opacity=".55"/>
    <path d="M60 134L360 134" stroke="currentColor" stroke-opacity=".35" stroke-width="3"/>
    <path class="clamp" d="M396 92C406 94 414 98 420 104L418 108C410 104 402 101 392 100Z" fill="#fff59d"/>
    <path class="ctail" d="M21 94C22 90 26 88 30 86L40 84L40 90L26 98Z" fill="#ef5350"/>
    <circle cx="62" cy="100" r="5" style="fill:var(--card-background-color,#222)" stroke="currentColor" stroke-opacity=".8"/><path class="cbolt" d="M63 94l-5 8h4l-2 7 6-9h-4z" fill="#fff59d"/>
    <g class="wheels">${wheel(105)}${wheel(372)}</g><g class="bmarks"></g></svg>`;
}
function towerSvg(k) {
  const mods = Array.from({ length: 5 }, (_, i) => `<rect x="36" y="${17 + i * 41}" width="108" height="3" style="fill:var(--card-background-color,#222)"/>`).join("");
  const wave = "M-40 0" + Array.from({ length: 12 }, () => " q10 -6 20 0 t20 0").join("");
  return `<svg viewBox="0 0 190 240" class="battsvg tower">
    <defs><clipPath id="tb-${k}"><rect x="36" y="14" width="108" height="206" rx="10"/></clipPath>
      <linearGradient id="tg-${k}" x1="0" x2="1" y1="0" y2="0"><stop offset="0" stop-color="#000" stop-opacity=".22"/><stop offset=".35" stop-color="#fff" stop-opacity=".28"/><stop offset="1" stop-color="#000" stop-opacity=".22"/></linearGradient></defs>
    <rect x="30" y="224" width="120" height="8" rx="3" fill="currentColor" opacity=".35"/>
    <g clip-path="url(#tb-${k})"><rect x="36" y="14" width="108" height="206" fill="currentColor" opacity=".08"/>
      <g class="twrap"><g class="twaveg"><path class="bfill twv" d="${wave} V260 H-40Z"/></g></g>
      <rect class="bfill tfl" x="36" y="220" width="108" height="0"/>${mods}
      <rect x="36" y="14" width="108" height="206" fill="url(#tg-${k})"/></g>
    <rect x="30" y="8" width="120" height="216" rx="14" fill="none" stroke="currentColor" stroke-width="3" opacity=".6"/>
    <rect x="48" y="22" width="40" height="7" rx="3" fill="currentColor" opacity=".28"/><circle class="tled" cx="126" cy="26" r="4"/>
    <g class="tflow">${[0, 1, 2].map(i => `<path class="tch" style="animation-delay:${-i * 0.55}s" d="M164 ${200 - i * 0} l8 -9 l8 9" fill="none" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>`).join("")}</g>
    <g class="bmarks"></g></svg>`;
}
function battHTML(key, label) {
  return `<div class="batt ${key === "ev" ? "carw" : "towerw"}" data-b="${key}">
    <div class="bstage">${key === "ev" ? carSvg(key) : towerSvg(key)}
      <div class="bimg" hidden><img alt=""><div class="bfl"></div><div class="bimk"></div></div></div>
    <div class="battmeta"><span class="bbig"></span><b>${esc(label)}</b><span class="muted bsub"></span></div></div>`;
}
function cutout(im) {
  try {
    const W = Math.min(im.naturalWidth, 720), H = Math.round(im.naturalHeight * W / im.naturalWidth);
    const cv = document.createElement("canvas"); cv.width = W; cv.height = H;
    const cx = cv.getContext("2d", { willReadFrequently: true }); cx.drawImage(im, 0, 0, W, H);
    const img = cx.getImageData(0, 0, W, H), d = img.data;
    if (d[3] < 200 || d[(W - 1) * 4 + 3] < 200) return null; // already transparent
    const px = (x, y) => (y * W + x) * 4, corners = [[0, 0], [W - 1, 0], [0, H - 1], [W - 1, H - 1]].map(([x, y]) => [d[px(x, y)], d[px(x, y) + 1], d[px(x, y) + 2]]);
    const ref = [0, 1, 2].map(c => corners.reduce((a, k) => a + k[c], 0) / 4), tol = 46, seen = new Uint8Array(W * H), q = [];
    const near = i => { const j = i * 4; return Math.hypot(d[j] - ref[0], d[j + 1] - ref[1], d[j + 2] - ref[2]) < tol; };
    const push = i => { if (!seen[i] && near(i)) { seen[i] = 1; q.push(i); } };
    for (let x = 0; x < W; x++) { push(x); push((H - 1) * W + x); }
    for (let y = 0; y < H; y++) { push(y * W); push(y * W + W - 1); }
    while (q.length) { const i = q.pop(), x = i % W, y = (i / W) | 0; if (x > 0) push(i - 1); if (x < W - 1) push(i + 1); if (y > 0) push(i - W); if (y < H - 1) push(i + W); }
    let n = 0; for (let i = 0; i < seen.length; i++) if (seen[i]) { d[i * 4 + 3] = 0; n++; }
    const frac = n / seen.length; if (frac < 0.15 || frac > 0.92) return null;
    cx.putImageData(img, 0, 0); return cv.toDataURL("image/png");
  } catch (e) { return null; }
}
function battImg(root) {
  if (root._img !== undefined) return;
  root._img = "pending";
  const key = root.dataset.b, im = new Image();
  im.onload = () => {
    root._img = "ok";
    const wrap = root.querySelector(".bimg"), pic = wrap.querySelector("img");
    const src = cutout(im) || BIMG[key];
    pic.src = src; wrap.style.setProperty("--m", `url("${src}")`);
    wrap.hidden = false; root.querySelector(".battsvg").style.display = "none"; root.classList.add("photo");
    if (root._last) battSet(root, root._last);
  };
  im.onerror = () => { root._img = "no"; };
  im.src = BIMG[key];
}
function battSet(root, o) {
  if (!root) return;
  root._last = o; battImg(root);
  const pct = o.pct === null || o.pct === undefined ? null : Math.max(0, Math.min(o.pct, 100)), p = pct ?? 0, col = levelColor(pct), ev = root.dataset.b === "ev";
  root.classList.toggle("chg", !!o.charging); root.classList.toggle("dis", !!o.discharging); root.style.setProperty("--bc", col);
  root.querySelector(".bbig").textContent = pct === null ? "–" : Math.round(pct) + "%";
  root.querySelector(".bsub").textContent = o.sub || "";
  const marks = (o.marks || []).filter(m => m.pct !== null && m.pct !== undefined);
  if (root._img === "ok") {
    const wrap = root.querySelector(".bimg");
    wrap.style.setProperty(ev ? "--r" : "--t", (100 - p) + "%");
    root.querySelector(".bimk").innerHTML = marks.map(m => `<i title="${esc(m.label)} ${Math.round(m.pct)}%" style="background:${m.color};${ev ? `left:${m.pct}%;top:0;bottom:0;width:3px` : `bottom:${m.pct}%;left:0;right:0;height:3px`}"></i>`).join("");
    return;
  }
  root.querySelectorAll(".bfill").forEach((r, i) => { if (!i || r.classList.contains("twv") || r.classList.contains("tfl")) r.style.fill = col; });
  if (ev) {
    const w = 406 * p / 100;
    root.querySelectorAll(".bfill").forEach(r => { r.style.width = w + "px"; }); root.querySelector(".fclip").style.width = w + "px";
    root.querySelector(".bmarks").innerHTML = marks.map(m => { const x = 18 + 406 * m.pct / 100; return `<g><title>${esc(m.label)} ${Math.round(m.pct)}%</title><line x1="${x}" x2="${x}" y1="8" y2="148" stroke="${m.color}" stroke-width="3" stroke-dasharray="5 3"/><circle cx="${x}" cy="8" r="4" fill="${m.color}"/></g>`; }).join("");
  } else {
    const h = 206 * p / 100, y = 220 - h;
    const tf = root.querySelector(".tfl"); tf.style.y = y + "px"; tf.style.height = h + "px";
    root.querySelector(".twrap").style.transform = `translateY(${y + 2}px)`;
    root.querySelector(".bmarks").innerHTML = marks.map(m => { const my = 220 - 206 * m.pct / 100; return `<g><title>${esc(m.label)} ${Math.round(m.pct)}%</title><line x1="26" x2="154" y1="${my}" y2="${my}" stroke="${m.color}" stroke-width="3" stroke-dasharray="5 3"/><circle cx="26" cy="${my}" r="4" fill="${m.color}"/></g>`; }).join("");
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
.chart{width:100%;height:240px} .chart svg{width:100%;height:100%;overflow:hidden;color:var(--primary-text-color)}
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

.evring{width:100%;max-width:220px;display:block;margin:0 auto 10px;color:var(--primary-text-color)} .evpct{font-size:34px;font-weight:700;fill:currentColor}
.evring.pulse circle:nth-of-type(2){animation:glow 2s ease-in-out infinite} @keyframes glow{50%{opacity:.55}}
.slider{width:100%;accent-color:var(--primary-color);height:28px}
.sw{width:42px;height:22px;accent-color:var(--primary-color);cursor:pointer}
input[type=time]{background:var(--card-background-color);color:inherit;border:1px solid var(--divider-color);border-radius:8px;padding:3px 6px}
.phase{display:grid;grid-template-columns:44px 1fr 36px;gap:8px;align-items:center;margin:5px 0;font-size:13px}
.phase div{height:10px;background:var(--divider-color);border-radius:5px;overflow:hidden} .phase i{display:block;height:100%;border-radius:5px;transition:width .6s} .phase b{text-align:right}

.evhero{padding:0;overflow:hidden}
.stage{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(240px,1fr)}
.carbox{position:relative;min-height:280px;display:flex;align-items:center;justify-content:center;
  background:radial-gradient(120% 90% at 50% 38%,color-mix(in srgb,var(--primary-color) 22%,transparent),transparent 70%),linear-gradient(180deg,transparent,#0003)}
.carbox img{max-width:88%;max-height:210px;object-fit:contain;filter:drop-shadow(0 18px 18px #0006);position:relative;z-index:1;margin-bottom:34px}
.carglow{position:absolute;left:12%;right:12%;bottom:62px;height:26px;border-radius:50%;background:radial-gradient(closest-side,#66bb6a88,transparent);opacity:0;transition:opacity .6s}
.carglow.on{opacity:1;animation:glow 2s ease-in-out infinite}
.cartop{position:absolute;top:14px;left:18px;right:18px;display:flex;justify-content:space-between;align-items:center;z-index:2}
.carname{font-size:18px;font-weight:600;letter-spacing:.3px}
.carbar{position:absolute;left:18px;right:18px;bottom:14px;z-index:2}
.barbg{position:relative;height:12px;border-radius:7px;background:color-mix(in srgb,currentColor 14%,transparent);overflow:visible}
.barbg i{position:absolute;left:0;top:0;bottom:0;border-radius:7px;transition:width .8s,background .4s;box-shadow:0 0 12px currentColor}
.barbg u{position:absolute;top:-4px;bottom:-4px;width:3px;margin-left:-1px;border-radius:2px;background:#ef6c00;text-decoration:none}
.barlbl{display:flex;justify-content:space-between;align-items:baseline;margin-top:6px}.barlbl b{font-size:22px}
.evside{padding:18px;display:flex;flex-direction:column;justify-content:center;gap:10px;background:color-mix(in srgb,var(--primary-text-color) 4%,transparent)}
.evside .evring{max-width:150px}
@media (max-width:760px){.stage{grid-template-columns:1fr}.carbox{min-height:240px}}

.lg{display:flex;gap:14px;flex-wrap:wrap;font-size:12px;opacity:.8;margin-top:4px}
.stat b small{font-size:12px;font-weight:400;opacity:.6;margin-left:3px}
.num{width:90px;text-align:right;background:var(--card-background-color);color:inherit;border:1px solid var(--divider-color);border-radius:8px;padding:4px 6px}

.battstack{display:flex;flex-direction:column;gap:22px}
.batt{display:flex;flex-direction:column;gap:6px;color:var(--primary-text-color);--bc:#66bb6a}
.towerw{flex-direction:row;align-items:center;gap:18px}.towerw .bstage{flex:0 0 42%;max-width:190px}.towerw .battmeta{align-items:flex-start;text-align:left}
.battsvg{width:100%;display:block;margin:0 auto;overflow:visible}.car{max-width:380px}
.bfill{transition:width 1s ease,y 1s ease,height 1s ease,fill .6s}.fclip{transition:width 1s ease}
.chg .battsvg,.chg .bimg{filter:drop-shadow(0 0 8px var(--bc))}
.bsheen{opacity:0}.chg .bsheen{opacity:1;animation:sheen 2s linear infinite}
@keyframes sheen{from{transform:translateX(0)}to{transform:translateX(480px)}}
.cglow{fill:var(--bc);opacity:0;filter:blur(8px)}.chg .cglow{opacity:.5;animation:glow 2s ease-in-out infinite}
.cflow{stroke:var(--bc);opacity:0}.chg .cflow{opacity:.8;animation:dashmove 0.8s linear infinite}@keyframes dashmove{to{stroke-dashoffset:-16}}
.cbolt{opacity:0}.chg .cbolt{animation:pulse 1.1s ease-in-out infinite}@keyframes pulse{50%{opacity:1}0%,100%{opacity:.15}}
.ctail{opacity:.55}.chg .ctail{opacity:1}.clamp{opacity:.25}.chg .clamp{opacity:.9}
.spin{animation:none}.chg .spin{animation:none}
.twaveg{animation:wavex 2.4s linear infinite}@keyframes wavex{to{transform:translateX(40px)}}
.twrap{transition:transform 1s ease}
.tled{fill:#66bb6a;animation:blink 2s ease-in-out infinite}@keyframes blink{50%{opacity:.25}}
.tflow{opacity:0}.tch{stroke:var(--bc);opacity:0}
.chg .tflow,.dis .tflow{opacity:1}
.chg .tch{animation:up 1.6s linear infinite}.dis .tch{animation:down 1.6s linear infinite}
@keyframes up{0%{transform:translateY(20px);opacity:0}30%{opacity:1}100%{transform:translateY(-150px);opacity:0}}
@keyframes down{0%{transform:translateY(-150px);opacity:0}30%{opacity:1}100%{transform:translateY(20px);opacity:0}}
.bstage{position:relative}
.bimg{position:relative;width:100%;max-width:380px;margin:0 auto}.bimg img{width:100%;display:block;filter:grayscale(1) brightness(.6);opacity:.4}
.bfl{position:absolute;inset:0;-webkit-mask-image:var(--m);mask-image:var(--m);-webkit-mask-size:100% 100%;mask-size:100% 100%;-webkit-mask-repeat:no-repeat;mask-repeat:no-repeat;
  background:linear-gradient(105deg,var(--bc) 0 40%,color-mix(in srgb,var(--bc) 55%,#fff) 50%,var(--bc) 60% 100%);background-size:250% 100%;transition:clip-path 1s ease}
.carw .bfl{clip-path:inset(0 var(--r,100%) 0 0)}.towerw .bfl{clip-path:inset(var(--t,100%) 0 0 0)}
.chg .bfl{animation:photo 2.2s linear infinite}@keyframes photo{from{background-position:150% 0}to{background-position:-50% 0}}
.bimk{position:absolute;inset:0;pointer-events:none}.bimk i{position:absolute;opacity:.9}
.battmeta{display:flex;flex-direction:column;align-items:center;text-align:center;font-size:13px;gap:2px}
.battmeta b{font-size:15px}.bbig{font-size:34px;font-weight:700;line-height:1.1;color:var(--bc)}
.evside .batt{margin-bottom:4px}

.visgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px}
.vcell h3{margin:0 0 10px;font-size:14px;font-weight:600;opacity:.85}
.vsub{margin-top:8px;font-size:13px;opacity:.85}
.fuel{width:100%;max-width:240px;display:block;margin:0 auto;color:var(--primary-text-color)} #needle{transition:transform 1s cubic-bezier(.3,1.4,.5,1)}
.cring{width:130px;display:block;margin:0 auto;color:var(--primary-text-color)}
.sbtrack{position:relative;height:30px;border-radius:15px;background:var(--divider-color);overflow:visible;margin:18px 0 6px}
.sbfill{position:absolute;left:0;top:0;bottom:0;border-radius:15px;transition:width 1s,background .5s;box-shadow:0 0 12px #f9a82588}
.sbfc,.sblow{position:absolute;top:-8px;bottom:-8px;width:3px;border-radius:2px;text-decoration:none;transition:left 1s}
.sbfc{background:#42a5f5}.sblow{background:#ef5350;opacity:.9}
.sblab{display:flex;justify-content:space-between;font-size:13px}
@media (max-width:640px){:host{padding:10px 10px 40px}.big{font-size:24px}.chart{height:200px}.legend{margin-left:0}}
`;
customElements.define("cortex-studio", CortexStudio);
