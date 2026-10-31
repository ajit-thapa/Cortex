/* Cortex sidebar panel. Vanilla custom element, no build step. */
const CAT_ICON = { fact: "📌", preference: "⭐", person: "👤", place: "📍", routine: "🔁", note: "📝" };
const PERIOD_COLOR = { peak: "#ef5350", shoulder: "#66bb6a", off_peak: "#ffa726" };

class CortexPanel extends HTMLElement {
  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) {
      this._build();
      this._load();
      this._timer = setInterval(() => this._load(), 30000);
    }
  }
  set narrow(v) { this._narrow = v; }
  disconnectedCallback() { clearInterval(this._timer); }

  async _load() {
    try {
      this._data = await this._hass.callWS({ type: "cortex/overview" });
      this._render();
    } catch (e) {
      this._root.querySelector("#body").textContent = "Cortex is not loaded: " + (e.message || e.code);
    }
  }
  async _ws(msg) { await this._hass.callWS(msg); await this._load(); }

  _build() {
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display:block; padding:16px; box-sizing:border-box; color:var(--primary-text-color);
                background:var(--primary-background-color); min-height:100%; }
        h1 { font-size:22px; margin:0 0 12px; font-weight:500 }
        h2 { font-size:15px; margin:0 0 8px; font-weight:500; opacity:.8 }
        .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:16px; max-width:1300px; margin:auto }
        .card { background:var(--card-background-color); border-radius:12px; padding:16px;
                box-shadow:var(--ha-card-box-shadow,0 1px 3px #0003) }
        .wide { grid-column:1/-1 }
        .row { display:flex; justify-content:space-between; gap:8px; padding:4px 0; align-items:center }
        .muted { opacity:.65; font-size:13px }
        .pill { padding:2px 10px; border-radius:99px; color:#fff; font-size:13px }
        .bars { display:flex; align-items:flex-end; gap:3px; height:110px; margin-top:8px }
        .bar { flex:1; border-radius:3px 3px 0 0; min-height:2px; position:relative }
        .bar.now { outline:2px solid var(--primary-text-color) }
        .fit { height:3px; background:#2e7d32; position:absolute; left:0; right:0 }
        .axis { display:flex; justify-content:space-between; font-size:11px; opacity:.6 }
        button { cursor:pointer; border:0; border-radius:8px; padding:6px 12px;
                 background:var(--primary-color); color:var(--text-primary-color,#fff) }
        button.ghost { background:transparent; color:var(--secondary-text-color); padding:2px 8px }
        input, select { padding:6px; border-radius:6px; border:1px solid var(--divider-color);
                 background:var(--card-background-color); color:var(--primary-text-color) }
        .mem { display:flex; gap:8px; padding:6px 0; border-bottom:1px solid var(--divider-color); align-items:center }
        .mem span.t { flex:1 }
        .ok { color:#66bb6a } .bad { color:#ef5350 }
      </style>
      <h1>Cortex</h1>
      <div id="body" class="grid">Loading…</div>`;
  }

  _render() {
    const d = this._data, e = d.energy, body = this._root.querySelector("#body");
    const f = (v, n = 1, u = "") => (v === null || v === undefined ? "–" : Number(v).toFixed(n) + u);
    const next = new Date(e.next_change).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    const maxRate = Math.max(...d.schedule.map(r => r.import), 1);
    const bars = d.schedule.map(r => {
      const p = r.import <= 12 ? "shoulder" : r.import >= 40 ? "peak" : "off_peak";
      return `<div class="bar ${r.hour === d.hour ? "now" : ""}" title="${r.hour}:00  import ${r.import}c  feed-in ${r.feed_in}c"
        style="height:${(r.import / maxRate) * 100}%;background:${PERIOD_COLOR[p]}">
        <div class="fit" style="bottom:${(r.feed_in / maxRate) * 100}%"></div></div>`;
    }).join("");
    const mem = d.memories.slice().reverse().map(m => `
      <div class="mem"><span>${CAT_ICON[m.category] || "📌"}</span><span class="t">${esc(m.text)}</span>
      <button class="ghost" data-del="${m.id}">✕</button></div>`).join("") || `<div class="muted">Nothing remembered yet.</div>`;
    const speech = d.speech.slice(0, 8).map(s => `
      <div class="row"><span>${esc(s.text)}</span>
      <span class="muted">${s.time.slice(11, 16)} ${s.spoken ? "🔊" : "🔇 " + s.reason}</span></div>`).join("") || `<div class="muted">Nothing said yet.</div>`;
    const health = d.health.length ? d.health.map(h => `<div class="row"><span>${esc(h)}</span></div>`).join("")
      : `<div class="row ok">All clear</div>`;
    const rem = d.reminders.map(r => `<div class="row"><span>${esc(r.message)}</span>
      <span class="muted">${new Date(r.at).toLocaleString([], { hour: "2-digit", minute: "2-digit", weekday: "short" })}
      <button class="ghost" data-cancel="reminder:${r.id}">✕</button></span></div>`).join("") || `<div class="muted">No reminders.</div>`;
    const wat = d.watches.map(w => `<div class="row"><span>${esc(w.entity_id)}${w.to_state ? " → " + esc(w.to_state) : ""}</span>
      <button class="ghost" data-cancel="watch:${w.id}">✕</button></div>`).join("") || `<div class="muted">No watches.</div>`;
    body.innerHTML = `
      <div class="card"><h2>Power now</h2>
        <div class="row"><span class="pill" style="background:${PERIOD_COLOR[e.period]}">${e.period.replace("_", " ")}</span>
          <b>${f(e.import_rate, 1, "c")}</b></div>
        <div class="row muted"><span>Next: ${e.next_period.replace("_", " ")} at ${next}</span><span>Feed-in ${f(e.feed_in_rate, 0, "c")}</span></div>
        <div class="bars">${bars}</div><div class="axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>23</span></div>
        <div class="muted">Bars = import rate. Green line = feed-in.</div></div>
      <div class="card"><h2>Solar and storage</h2>
        <div class="row"><span>Solar today</span><b>${f(e.pv_today, 0, " kWh")} (${e.solar_day})</b></div>
        <div class="row"><span>Tomorrow</span><b>${f(e.pv_tomorrow, 0, " kWh")}</b></div>
        <div class="row"><span>Shortfall</span><b>${f(e.pv_shortfall, 1, " kWh")}</b></div>
        <div class="row"><span>Battery</span><b>${f(e.battery_stored)} kWh · ${f(e.battery_soc, 0, "%")} · room ${f(e.battery_room)}</b></div>
        <div class="row"><span>EV ${e.ev_plugged ? "🔌" : ""}</span><b>${f(e.ev_stored)} kWh · ${f(e.ev_soc, 0, "%")} · room ${f(e.ev_room)}</b></div>
        <div class="row"><span>Daily charge</span><b>$${f(e.daily_charge, 2)} → export ${f(e.export_to_cover, 2)} kWh</b></div>
        <div class="row muted"><span>Auto:</span><span>top-up ${d.automation.topup ? "on" : "off"} · export ${d.automation.export ? "on" : "off"} · EV gate ${d.automation.ev_gate ? "on" : "off"}</span></div></div>
      <div class="card"><h2>House health</h2>${health}
        <div class="row"><span class="muted">Speech ${d.hushed ? "hushed" : "active"}</span>
        <button id="hush">${d.hushed ? "Unhush" : "Hush 1h"}</button></div></div>
      <div class="card"><h2>Reminders</h2>${rem}<h2 style="margin-top:12px">Watches</h2>${wat}</div>
      <div class="card wide"><h2>Memory (${d.memories.length})</h2>
        <div class="row"><input id="mtext" placeholder="Something worth remembering" style="flex:1">
        <select id="mcat">${d.categories.map(c => `<option>${c}</option>`).join("")}</select><button id="madd">Add</button></div>
        ${mem}</div>
      <div class="card wide"><h2>Recent speech</h2>${speech}</div>`;
    body.querySelectorAll("[data-del]").forEach(b => b.onclick = () => this._ws({ type: "cortex/memory_delete", id: b.dataset.del }));
    body.querySelectorAll("[data-cancel]").forEach(b => b.onclick = () => {
      const [kind, id] = b.dataset.cancel.split(":"); this._ws({ type: "cortex/cancel", kind, id });
    });
    body.querySelector("#hush").onclick = () => this._ws({ type: "cortex/hush", minutes: d.hushed ? 0 : 60 });
    body.querySelector("#madd").onclick = () => {
      const t = body.querySelector("#mtext").value.trim();
      if (t) this._ws({ type: "cortex/memory_add", text: t, category: body.querySelector("#mcat").value });
    };
  }
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
customElements.define("cortex-panel", CortexPanel);
