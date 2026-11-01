/* Smart Roster - frontend. Vanilla JS, talks to the FastAPI backend under /api. */
"use strict";

// ------------------------------------------------------------------ helpers
const $ = (s, el = document) => el.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const CAL = { "365": "365 days (incl. Sundays & holidays)", HOLIDAY_OFF: "Closed on public holidays", SUNDAY_HOLIDAY_OFF: "Closed Sundays & holidays" };
const STATUS_NAME = { W: "Working", O: "Weekly off", L: "Leave", H: "Public holiday", C: "Comp-off", X: "Brand closed" };
const COLORS = ["#12C2D6", "#2563EB", "#7CE3F0", "#6D9BFF", "#0A9DB3", "#1E40AF", "#A5F0F8", "#9DB9FF"];

async function api(path, opts = {}) {
  const res = await fetch("/api" + path, {
    method: opts.method || "GET",
    headers: opts.body ? { "Content-Type": "application/json" } : undefined,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* not json */ }
  if (!res.ok) {
    const d = data && data.detail;
    throw new Error(typeof d === "string" ? d : d ? JSON.stringify(d) : `Request failed (${res.status})`);
  }
  return data;
}

function toast(msg, type = "") {
  const t = document.createElement("div");
  t.className = "toast " + type;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 4200);
}
const fail = (e) => toast(e.message || String(e), "err");

function modal(title, body, { okText = "Save", onOk = null, wide = false, extra = "" } = {}) {
  const ov = document.createElement("div");
  ov.className = "overlay";
  ov.innerHTML = `<div class="modal ${wide ? "wide" : ""}" role="dialog" aria-modal="true">
    <header><h2>${esc(title)}</h2><button class="x" aria-label="Close">×</button></header>
    <div class="body">${body}</div>
    <footer>${extra}<button class="btn" data-close>${onOk ? "Cancel" : "Close"}</button>${onOk ? `<button class="btn primary" data-ok>${esc(okText)}</button>` : ""}</footer></div>`;
  const close = () => ov.remove();
  ov.addEventListener("click", (e) => { if (e.target === ov || e.target.closest(".x") || e.target.closest("[data-close]")) close(); });
  if (onOk) {
    $("[data-ok]", ov).addEventListener("click", async (e) => {
      e.target.disabled = true;
      try { const r = await onOk(ov); if (r !== false) close(); } catch (err) { fail(err); }
      e.target.disabled = false;
    });
  }
  document.body.appendChild(ov);
  const first = $("input,select,textarea", ov); if (first) first.focus();
  return { el: ov, close };
}
function confirmBox(title, msg, okText = "Confirm") {
  return new Promise((resolve) => {
    const m = modal(title, `<p>${esc(msg)}</p>`, { okText, onOk: async () => { resolve(true); } });
    m.el.addEventListener("click", (e) => { if (e.target === m.el || e.target.closest("[data-close]") || e.target.closest(".x")) resolve(false); });
  });
}
const field = (label, input) => `<div class="field"><label>${esc(label)}</label>${input}</div>`;
const opts = (items, sel, blank) => (blank !== undefined ? `<option value="">${esc(blank)}</option>` : "") +
  items.map((i) => `<option value="${esc(i.id)}" ${String(i.id) === String(sel) ? "selected" : ""}>${esc(i.name)}</option>`).join("");
const chip = (text, cls = "") => `<span class="chip ${cls}">${esc(text)}</span>`;
const loading = () => `<div class="loading"><span class="spin"></span>Loading…</div>`;
const empty = (icon, title, sub, btn = "") => `<div class="card empty"><div class="big">${icon}</div><h2 style="justify-content:center">${esc(title)}</h2><p>${esc(sub)}</p>${btn}</div>`;
const fmtDate = (iso) => { const d = new Date(iso + "T00:00:00"); return `${d.getDate()} ${MONTHS[d.getMonth()]}`; };
const wdOf = (iso) => (new Date(iso + "T00:00:00").getDay() + 6) % 7;
const download = (url) => { const a = document.createElement("a"); a.href = url; document.body.appendChild(a); a.click(); a.remove(); };

// ------------------------------------------------------------------ state
const now = new Date();
const state = {
  ym: localStorage.getItem("sr_ym") || `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`,
  charts: [], grid: null,
  rv: { mode: "month", week: null, q: "", pod: "", brand: "", process: "", issues: false },
  ev: { q: "", pod: "", status: "" }, cv: { sev: "", q: "" }, lv: "PENDING", av: { q: "" }, bv: { q: "" },
  ref: null,
};
const my = () => { const [y, m] = state.ym.split("-").map(Number); return { month: m, year: y }; };
const monthLabel = () => { const { month, year } = my(); return `${MONTHS[month - 1]} ${year}`; };
async function refData() {
  if (!state.ref) {
    const [pods, brands, processes, employees] = await Promise.all([api("/pods"), api("/brands"), api("/processes"), api("/employees")]);
    state.ref = { pods, brands, processes, employees };
  }
  return state.ref;
}
const resetRef = () => { state.ref = null; };

// ------------------------------------------------------------------ navigation
const NAV = [
  ["dashboard", "🏠", "Dashboard"], ["roster", "📅", "Roster Planner"], ["employees", "🧑🏻‍💻", "Employees"],
  ["brands", "🏷️", "Brands & Processes"], ["assignments", "🖇️", "Assignments"], ["leaves", "🏜️", "Leave Management"],
  ["conflicts", "🔴", "Conflicts"], ["teams", "👥", "Pods & Teams"], ["reports", "📊", "Reports"], ["settings", "⚙️", "Settings"],
];
$("#nav").innerHTML = NAV.map(([id, ic, label]) => `<a href="#/${id}" data-page="${id}"><span class="ico">${ic}</span><span class="label">${label}</span></a>`).join("");
$("#month").value = state.ym;
$("#month").addEventListener("change", (e) => { if (!e.target.value) return; state.ym = e.target.value; localStorage.setItem("sr_ym", state.ym); state.rv.week = null; render(); });
$("#burger").addEventListener("click", () => $("#app").classList.toggle("open"));
$("#collapse").addEventListener("click", () => $("#app").classList.toggle("collapsed"));
$("#nav").addEventListener("click", () => $("#app").classList.remove("open"));
$("#gsearch").addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  state.ev.q = e.target.value; state.bv.q = e.target.value; location.hash = "#/employees"; render();
});
$("#gen").addEventListener("click", () => generate());
window.addEventListener("hashchange", render);

async function generate(force = false) {
  const { month, year } = my();
  try {
    const r = await api("/rosters/generate", { method: "POST", body: { month, year, force } });
    toast(`Roster for ${monthLabel()} generated - coverage ${r.coverage_percent}%, ${r.conflicts.total} conflict(s)`, "ok");
    if (location.hash === "#/roster") render(); else location.hash = "#/roster";
  } catch (e) {
    if (/published/i.test(e.message) && !force) {
      if (await confirmBox("Overwrite published roster?", e.message, "Re-generate anyway")) generate(true);
    } else fail(e);
  }
}

// ------------------------------------------------------------------ router
const pages = {};
async function render() {
  const page = (location.hash.replace("#/", "") || "dashboard").split("?")[0];
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
  state.charts.forEach((c) => c.destroy()); state.charts = [];
  $("#month").value = state.ym;
  const view = $("#view");
  view.innerHTML = loading();
  try { await (pages[page] || pages.dashboard)(view); } catch (e) { view.innerHTML = empty("😕", "Something went wrong", e.message); }
}
const head = (title, sub, actions = "") => `<div class="page-head"><div><h1>${title}</h1><p>${sub}</p></div><div class="actions">${actions}</div></div>`;

// ------------------------------------------------------------------ dashboard
pages.dashboard = async (view) => {
  const { month, year } = my();
  const d = await api(`/dashboard?month=${month}&year=${year}`);
  const k = d.kpi;
  const kp = (ic, v, l, b) => `<div class="card kpi ${b ? "b" : ""}"><div class="ic">${ic}</div><div><div class="v">${v}</div><div class="l">${l}</div></div></div>`;
  let html = head("Operations Dashboard", "Monitor workforce availability, brand coverage, and monthly roster performance.",
    `<button class="btn" data-act="export-roster">⬇ Export Report</button><button class="btn primary" data-act="gen">⚡ Generate Roster</button>`);
  html += `<div class="grid g4">
    ${kp("👥", k.employees, "Total Employees")}${kp("🏷️", k.brands, "Total Brands", 1)}${kp("🧩", k.pods, "Total Pods")}${kp("✅", k.working_today, "Working Today", 1)}
    ${kp("🌴", k.on_leave, "On Leave Today")}${kp("🛋️", k.weekly_off, "On Weekly Off Today", 1)}
    ${kp("🎯", k.coverage == null ? "–" : k.coverage + "%", `Brand Coverage (${monthLabel()})`)}${kp("⚠️", k.conflicts, "Active Conflicts", 1)}</div>`;
  if (!d.roster) {
    html += `<div style="margin-top:16px">${empty("📅", `No roster for ${monthLabel()} yet`, "Generate one to see coverage, workload and conflicts.", `<button class="btn primary" data-act="gen">⚡ Generate Roster</button>`)}</div>`;
  } else {
    html += `<div class="grid g2" style="margin-top:16px">
      <div class="card"><h2>Employees by Pod</h2><div class="chart-box"><canvas id="ch1"></canvas></div></div>
      <div class="card"><h2>Brands Needing Coverage <span class="muted small">lowest 10</span></h2><div class="chart-box"><canvas id="ch2"></canvas></div></div>
      <div class="card"><h2>Workforce Availability <span class="muted small">per day</span></h2><div class="chart-box"><canvas id="ch3"></canvas></div></div>
      <div class="card"><h2>Monthly Workload <span class="muted small">working days</span></h2><div class="chart-box"><canvas id="ch4"></canvas></div></div></div>`;
  }
  html += `<div class="grid g2" style="margin-top:16px">
    <div class="card"><h2>Recent Conflicts <a href="#/conflicts" class="small">View all</a></h2>
      ${d.recent_conflicts.length ? `<div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Brand</th><th>Process</th><th>Issue</th><th>Severity</th></tr></thead><tbody>
      ${d.recent_conflicts.map((c) => `<tr><td>${c.date ? fmtDate(c.date) : ""}</td><td>${esc(c.brand || c.employee || "-")}</td><td>${esc(c.process || "-")}</td><td>${esc(c.type.replace(/_/g, " ").toLowerCase())}</td><td>${chip(c.severity, c.severity)}</td></tr>`).join("")}</tbody></table></div>` : `<div class="empty">🎉 No conflicts</div>`}</div>
    <div class="card"><h2>Brands Requiring Attention</h2>${d.attention.length ? `<div class="list">${d.attention.map((a) => `<div class="row"><div><b>${esc(a.brand)}</b><div class="muted small">${a.covered}/${a.required} required slots covered</div></div><div style="min-width:110px"><div class="bar ${a.percent < 90 ? "low" : ""}"><i style="width:${a.percent}%"></i></div><div class="small" style="text-align:right">${a.percent}%</div></div></div>`).join("")}</div>` : `<div class="empty">✅ All brands fully covered</div>`}</div>
    <div class="card"><h2>Today's Employee Schedule <span class="muted small">${new Date().toDateString()}</span></h2><div class="list">
      ${d.schedule_today.map((s) => `<div class="row"><div><b>${esc(s.employee)}</b><div class="muted small">${esc(s.brands)}</div></div>${chip(STATUS_NAME[s.status] || s.status, s.status === "W" ? "" : s.status === "L" ? "warn" : "blue")}</div>`).join("")}</div></div>
    <div class="card"><h2>Upcoming Holidays</h2>${d.holidays.length ? `<div class="list">${d.holidays.map((h) => `<div class="row"><b>${esc(h.name)}</b><span class="chip blue">${fmtDate(h.date)}</span></div>`).join("")}</div>` : `<div class="empty">No upcoming holidays configured</div>`}</div></div>`;
  view.innerHTML = html;
  if (!d.roster || !window.Chart) return;
  const mk = (id, cfg) => { const c = new Chart($(id), cfg); state.charts.push(c); };
  const base = { responsive: true, maintainAspectRatio: false, plugins: { legend: { labels: { boxWidth: 12 } } } };
  mk("#ch1", { type: "doughnut", data: { labels: d.pod_distribution.map((p) => p.pod), datasets: [{ data: d.pod_distribution.map((p) => p.count), backgroundColor: COLORS, borderWidth: 2 }] }, options: { ...base, cutout: "62%", plugins: { legend: { position: "right" } } } });
  const low = d.brand_coverage.slice(0, 10);
  mk("#ch2", { type: "bar", data: { labels: low.map((b) => b.brand), datasets: [{ label: "Coverage %", data: low.map((b) => b.percent), backgroundColor: low.map((b) => (b.percent < 90 ? "#E5484D" : "#12C2D6")), borderRadius: 6 }] }, options: { ...base, indexAxis: "y", scales: { x: { min: 0, max: 100 } }, plugins: { legend: { display: false } } } });
  const lab = d.availability.map((a) => +a.date.slice(8));
  mk("#ch3", { type: "bar", data: { labels: lab, datasets: [{ label: "Working", data: d.availability.map((a) => a.working), backgroundColor: "#12C2D6" }, { label: "Weekly off", data: d.availability.map((a) => a.off), backgroundColor: "#9DB9FF" }, { label: "Leave", data: d.availability.map((a) => a.leave), backgroundColor: "#F5B942" }] }, options: { ...base, scales: { x: { stacked: true }, y: { stacked: true } } } });
  mk("#ch4", { type: "bar", data: { labels: d.workload.map((w) => w.employee), datasets: [{ label: "Days worked", data: d.workload.map((w) => w.days), backgroundColor: "#2563EB", borderRadius: 4 }] }, options: { ...base, plugins: { legend: { display: false } } } });
};

// ------------------------------------------------------------------ roster planner
function weeksOf(dates) {
  const weeks = []; let cur = [];
  dates.forEach((d) => { if (wdOf(d) === 0 && cur.length) { weeks.push(cur); cur = []; } cur.push(d); });
  if (cur.length) weeks.push(cur);
  return weeks;
}
pages.roster = async (view) => {
  const ref = await refData();
  const { month, year } = my();
  try { state.grid = await api(`/rosters/by-month?month=${month}&year=${year}`); } catch (e) { state.grid = null; }
  const g = state.grid;
  if (!g) {
    view.innerHTML = head("Roster Planner", `No roster for ${monthLabel()} yet.`) +
      empty("📅", "Nothing generated yet", "The engine will build the roster from assignments, calendars, weekly offs and approved leave.", `<button class="btn primary" data-act="gen">⚡ Generate ${monthLabel()} Roster</button>`);
    return;
  }
  drawRoster(view);
};

function drawRoster(view) {
  const g = state.grid, rv = state.rv, ref = state.ref, r = g.roster;
  const weeks = weeksOf(g.dates);
  if (rv.week == null) {
    const t = new Date().toISOString().slice(0, 10);
    const i = weeks.findIndex((w) => w.includes(t));
    rv.week = i >= 0 ? i : 0;
  }
  rv.week = Math.min(Math.max(rv.week, 0), weeks.length - 1);
  const dates = rv.mode === "week" ? weeks[rv.week] : g.dates;
  const gap = new Set(g.gap_cells);
  const holi = new Set(g.holidays);
  const q = rv.q.toLowerCase();
  const rows = g.rows.filter((row) =>
    (!q || row.employee.toLowerCase().includes(q) || row.brand.toLowerCase().includes(q)) &&
    (!rv.pod || String(row.pod_id) === rv.pod) && (!rv.brand || String(row.brand_id) === rv.brand) &&
    (!rv.process || String(row.process_id) === rv.process) &&
    (!rv.issues || dates.some((d) => gap.has(`${row.brand_id}-${row.process_id}-${d}`))));
  const c = r.conflicts;
  const blocking = c.critical + c.high;
  const wkLabel = rv.mode === "week" ? `Week ${rv.week + 1} · ${fmtDate(weeks[rv.week][0])} – ${fmtDate(weeks[rv.week].slice(-1)[0])}` : monthLabel();
  const th = dates.map((d) => `<th class="${holi.has(d) ? "hol" : ""} ${wdOf(d) === 6 ? "sun" : ""}" title="${holi.has(d) ? "Public holiday" : DAYS[wdOf(d)]}">${rv.mode === "week" ? `${DAYS[wdOf(d)]}<br>${fmtDate(d)}` : `${+d.slice(8)}<br><span style="font-weight:600">${DAYS[wdOf(d)][0]}</span>`}</th>`).join("");
  const body = rows.map((row) => `<tr><td class="sticky">${esc(row.employee)}${row.cover ? ' <span class="chip blue">cover</span>' : ""}</td><td class="sticky s2">${esc(row.brand)}</td><td class="sticky s3">${esc(row.process)}</td>` +
    dates.map((d) => { const cell = row.cells[d]; if (!cell) return `<td class="cell"></td>`;
      return `<td class="cell c-${cell.s} ${gap.has(`${row.brand_id}-${row.process_id}-${d}`) ? "gap" : ""} ${cell.m ? "man" : ""}" data-act="cell" data-id="${cell.id}" data-emp="${esc(row.employee)}" data-bp="${esc(row.brand)} / ${esc(row.process)}" data-date="${d}" data-s="${cell.s}" data-cover="${cell.c ? 1 : 0}" title="${esc(row.employee)} · ${DAYS[wdOf(d)]} ${fmtDate(d)} · ${STATUS_NAME[cell.s]}">${cell.s}</td>`; }).join("") + "</tr>").join("");
  const foot = dates.map((d) => `<td title="Distinct employees working">${new Set(g.rows.filter((x) => x.cells[d] && x.cells[d].s === "W").map((x) => x.employee_id)).size}</td>`).join("");
  view.innerHTML = head("Roster Planner", `${wkLabel} · click any cell to edit; every change is re-validated instantly.`,
    `<div class="seg"><button class="${rv.mode === "week" ? "on" : ""}" data-act="mode" data-v="week">Weekly</button><button class="${rv.mode === "month" ? "on" : ""}" data-act="mode" data-v="month">Monthly</button></div>
     <button class="btn" data-act="validate">✔ Validate</button><button class="btn" data-act="export-roster">⬇ Export CSV</button>
     <button class="btn" data-act="gen">↻ Re-generate</button><button class="btn primary" data-act="publish" ${r.status === "PUBLISHED" ? "disabled" : ""}>🚀 Publish</button>`) +
    `<div class="banner ${blocking ? "warn" : ""}"><span>Status ${chip(r.status.replace("_", " "), r.status)}</span><span class="pill">Coverage ${r.coverage_percent}%</span>
      <span class="pill">🔴 ${c.critical} critical</span><span class="pill">🟠 ${c.high} high</span><span class="pill">🟡 ${c.medium} medium</span><span class="pill">⚪ ${c.low} low</span>
      ${blocking ? `<a href="#/conflicts">Review conflicts →</a>` : "<span>✅ No blocking conflicts</span>"}${r.note ? `<span class="small muted">${esc(r.note)}</span>` : ""}</div>
    <div class="filters">
      ${rv.mode === "week" ? `<button class="btn sm" data-act="wk" data-v="-1" ${rv.week === 0 ? "disabled" : ""}>◀ Prev week</button><button class="btn sm" data-act="wk" data-v="1" ${rv.week === weeks.length - 1 ? "disabled" : ""}>Next week ▶</button>` : ""}
      <input id="rq" placeholder="Search employee or brand" value="${esc(rv.q)}">
      <select id="rpod">${opts(ref.pods, rv.pod, "All pods")}</select>
      <select id="rbrand">${opts(ref.brands, rv.brand, "All brands")}</select>
      <select id="rproc">${opts(ref.processes, rv.process, "All processes")}</select>
      <label class="small"><input type="checkbox" id="rissues" ${rv.issues ? "checked" : ""}> Gaps only</label></div>
    <div class="legend">${Object.entries(STATUS_NAME).map(([k, v]) => `<span><b class="c-${k}">${k}</b>${v}</span>`).join("")}<span><b style="box-shadow:inset 0 0 0 2px var(--bad)"> </b>Coverage gap</span><span><b style="background:#fff;border:1px solid var(--line)">•</b>Manually edited</span></div>
    <div class="roster-wrap"><table class="roster ${rv.mode === "week" ? "weekly" : ""}"><thead><tr><th class="sticky">Employee</th><th class="sticky s2">Brand</th><th class="sticky s3">Process</th>${th}</tr></thead>
      <tbody>${body || `<tr><td colspan="${dates.length + 3}" class="empty">No rows match these filters</td></tr>`}</tbody>
      <tfoot><tr><td class="sticky" style="bottom:0">Employees working</td><td class="sticky s2"></td><td class="sticky s3"></td>${foot}</tr></tfoot></table></div>`;
  const bind = (id, key, ev = "input", fn = (e) => e.target.value) => $(id).addEventListener(ev, (e) => { rv[key] = fn(e); const pos = e.target.selectionStart; drawRoster(view); if (id === "#rq") { const n = $(id); n.focus(); n.setSelectionRange(pos, pos); } });
  bind("#rq", "q"); bind("#rpod", "pod", "change"); bind("#rbrand", "brand", "change"); bind("#rproc", "process", "change"); bind("#rissues", "issues", "change", (e) => e.target.checked);
}

async function editCell(ds) {
  const status = ds.s;
  const m = modal(`Edit shift · ${ds.emp}`, `<p class="muted">${esc(ds.bp)} · ${fmtDate(ds.date)} (${DAYS[wdOf(ds.date)]})</p>
    ${field("Status", `<select id="st">${Object.entries(STATUS_NAME).map(([k, v]) => `<option value="${k}" ${k === status ? "selected" : ""}>${k} - ${v}</option>`).join("")}</select>`)}
    <p class="small muted">The roster is re-checked for coverage, leave, weekly off and capacity as soon as you save. Edited cells are kept when the roster is re-generated.</p>`,
    { okText: "Save & validate", extra: ds.cover === "1" ? `<button class="btn danger" data-del>Remove cover shift</button>` : "",
      onOk: async (ov) => {
        const r = await api(`/rosters/entries/${ds.id}`, { method: "PATCH", body: { status: $("#st", ov).value } });
        toast(r.new_conflicts.length ? `Saved · ${r.new_conflicts.length} issue(s) found: ${r.new_conflicts[0].description}` : "Saved · no conflicts", r.new_conflicts.length ? "" : "ok");
        render();
      } });
  const del = $("[data-del]", m.el);
  if (del) del.addEventListener("click", async () => { try { await api(`/rosters/entries/${ds.id}`, { method: "DELETE" }); toast("Cover shift removed", "ok"); m.close(); render(); } catch (e) { fail(e); } });
}

async function publishRoster() {
  const r = state.grid.roster;
  try {
    let res = await api(`/rosters/${r.id}/publish`, { method: "POST", body: { force: false } });
    if (!res.published) {
      if (!(await confirmBox("Unresolved conflicts", res.message, "Publish anyway"))) return;
      res = await api(`/rosters/${r.id}/publish`, { method: "POST", body: { force: true } });
    }
    toast("Roster published", "ok"); render();
  } catch (e) { fail(e); }
}

// ------------------------------------------------------------------ employees
pages.employees = async (view) => {
  resetRef(); const ref = await refData();
  const f = state.ev;
  const list = ref.employees.filter((e) => (!f.q || (e.name + e.email + e.code).toLowerCase().includes(f.q.toLowerCase())) && (!f.pod || String(e.pod_id) === f.pod) && (!f.status || e.status === f.status));
  view.innerHTML = head("Employees", `${ref.employees.length} people across ${ref.pods.length} pods.`, `<button class="btn primary" data-act="emp-new">＋ Add Employee</button>`) +
    `<div class="filters"><input id="eq" placeholder="Search name, email, ID" value="${esc(f.q)}"><select id="epod">${opts(ref.pods, f.pod, "All pods")}</select>
      <select id="est"><option value="">Any status</option><option ${f.status === "ACTIVE" ? "selected" : ""}>ACTIVE</option><option ${f.status === "INACTIVE" ? "selected" : ""}>INACTIVE</option></select></div>
    <div class="card"><div class="tbl-wrap"><table><thead><tr><th>ID</th><th>Name</th><th>Email</th><th>Pod</th><th>Brands</th><th>Processes</th><th>Weekly off</th><th>Status</th><th></th></tr></thead><tbody>
    ${list.map((e) => `<tr><td>${esc(e.code)}</td><td><b>${esc(e.name)}</b></td><td class="muted">${esc(e.email)}</td><td>${esc(e.pod || "-")}</td><td>${e.brands.length ? e.brands.slice(0, 2).map(esc).join(", ") + (e.brands.length > 2 ? ` +${e.brands.length - 2}` : "") : "-"}</td><td>${e.processes.map((p) => chip(p)).join(" ") || "-"}</td><td>${esc(e.weekly_off_names.join(", ") || "-")}</td><td>${chip(e.status, e.status)}</td>
      <td><button class="btn sm" data-act="emp-edit" data-id="${e.id}">Edit</button> ${e.status === "ACTIVE" ? `<button class="btn sm danger" data-act="emp-off" data-id="${e.id}">Deactivate</button>` : ""}</td></tr>`).join("") || `<tr><td colspan="9" class="empty">No employees match</td></tr>`}</tbody></table></div></div>`;
  const bind = (id, k) => $(id).addEventListener("input", (e) => { f[k] = e.target.value; const p = e.target.selectionStart; pages.employees(view).then(() => { const n = $(id); if (n && n.setSelectionRange && n.type === "text") { n.focus(); try { n.setSelectionRange(p, p); } catch (_) {} } }); });
  bind("#eq", "q"); bind("#epod", "pod"); bind("#est", "status");
};
function empForm(e = {}) {
  const ref = state.ref;
  return field("Full name", `<input id="f_name" value="${esc(e.name)}" required>`) + field("Email", `<input id="f_email" type="email" value="${esc(e.email)}">`) +
    field("Pod", `<select id="f_pod">${opts(ref.pods, e.pod_id, "No pod")}</select>`) +
    field("Status", `<select id="f_status"><option ${e.status !== "INACTIVE" ? "selected" : ""}>ACTIVE</option><option ${e.status === "INACTIVE" ? "selected" : ""}>INACTIVE</option></select>`) +
    field("Weekly off day(s)", `<div class="checks">${DAYS.map((d, i) => `<label><input type="checkbox" class="f_wo" value="${i}" ${(e.weekly_offs || []).includes(i) ? "checked" : ""}>${d}</label>`).join("")}</div>`) +
    field("Max brands handled per day", `<input id="f_cap" type="number" min="1" max="6" value="${e.daily_capacity || 2}">`);
}
const readEmp = (ov) => ({ name: $("#f_name", ov).value.trim(), email: $("#f_email", ov).value.trim() || null, pod_id: $("#f_pod", ov).value ? +$("#f_pod", ov).value : null, status: $("#f_status", ov).value, weekly_offs: [...ov.querySelectorAll(".f_wo:checked")].map((c) => +c.value), daily_capacity: +$("#f_cap", ov).value || 2 });

// ------------------------------------------------------------------ brands & processes
pages.brands = async (view) => {
  resetRef(); const ref = await refData();
  const q = state.bv.q.toLowerCase();
  const list = ref.brands.filter((b) => !q || b.name.toLowerCase().includes(q));
  view.innerHTML = head("Brands & Processes", "Set each brand's operating calendar and minimum staffing per process.",
    `<button class="btn" data-act="proc-new">＋ Process</button><button class="btn primary" data-act="brand-new">＋ Add Brand</button>`) +
    `<div class="card" style="margin-bottom:16px"><h2>Processes</h2><div>${ref.processes.map((p) => `<span class="chip blue" title="${esc(p.description)}" style="margin:2px">${esc(p.name)}</span>`).join(" ")}</div></div>
    <div class="filters"><input id="bq" placeholder="Search brands" value="${esc(state.bv.q)}"></div>
    <div class="grid g3">${list.map((b) => `<div class="card brand-card"><h3>${esc(b.name)}</h3>
      <div class="meta">${chip(b.structure, b.structure === "Single-resource" ? "" : "blue")}${chip(b.status, b.status)}${chip(b.pod || "No pod", "LOW")}</div>
      <div class="muted small" style="margin-bottom:8px">👤 ${esc(b.employees.join(", ") || "No employees assigned")}</div>
      <table>${b.rules.map((r) => `<tr><td><b>${esc(r.process)}</b></td><td><select data-rule="${b.id}:${r.process_id}" data-f="cal">${Object.entries(CAL).map(([k, v]) => `<option value="${k}" ${k === r.calendar_type ? "selected" : ""}>${v}</option>`).join("")}</select></td>
        <td title="Minimum staff"><input type="number" min="0" max="20" value="${r.min_staff}" data-rule="${b.id}:${r.process_id}" data-f="min"></td></tr>`).join("") || `<tr><td class="muted">No processes configured</td></tr>`}</table>
      <div class="actions" style="margin-top:10px"><button class="btn sm" data-act="rule-new" data-id="${b.id}">＋ Process rule</button><button class="btn sm" data-act="brand-edit" data-id="${b.id}">Edit brand</button></div></div>`).join("")}</div>`;
  $("#bq").addEventListener("input", (e) => { state.bv.q = e.target.value; pages.brands(view); });
  view.querySelectorAll("[data-rule]").forEach((inp) => inp.addEventListener("change", async () => {
    const [bid, pid] = inp.dataset.rule.split(":").map(Number);
    const row = inp.closest("tr");
    try { await api("/rules", { method: "PUT", body: { brand_id: bid, process_id: pid, calendar_type: $("[data-f=cal]", row).value, min_staff: +$("[data-f=min]", row).value } }); toast("Rule saved · re-generate the roster to apply", "ok"); } catch (e) { fail(e); }
  }));
};

// ------------------------------------------------------------------ assignments
pages.assignments = async (view) => {
  resetRef(); await refData();
  const rows = await api("/assignments");
  const q = state.av.q.toLowerCase();
  const list = rows.filter((a) => !q || (a.employee + a.brand + a.process).toLowerCase().includes(q));
  view.innerHTML = head("Assignments", "Who handles which process of which brand (many-to-many).", `<button class="btn primary" data-act="as-new">＋ New Assignment</button>`) +
    `<div class="filters"><input id="aq" placeholder="Search employee, brand, process" value="${esc(state.av.q)}"></div>
    <div class="card"><div class="tbl-wrap"><table><thead><tr><th>Employee</th><th>Brand</th><th>Process</th><th>Pod</th><th>Allocation</th><th></th></tr></thead><tbody>
    ${list.map((a) => `<tr><td><b>${esc(a.employee)}</b></td><td>${esc(a.brand)}</td><td>${chip(a.process)}</td><td>${esc(a.pod || "-")}</td><td>${chip(a.status === "ACTIVE" ? "Active" : "Inactive", a.status)}</td><td><button class="btn sm danger" data-act="as-del" data-id="${a.id}">Remove</button></td></tr>`).join("") || `<tr><td colspan="6" class="empty">No assignments</td></tr>`}</tbody></table></div></div>`;
  $("#aq").addEventListener("input", (e) => { state.av.q = e.target.value; const p = e.target.selectionStart; pages.assignments(view).then(() => { const n = $("#aq"); n.focus(); n.setSelectionRange(p, p); }); });
};

// ------------------------------------------------------------------ leave
pages.leaves = async (view) => {
  resetRef(); await refData();
  const all = await api("/leaves");
  const list = state.lv === "ALL" ? all : all.filter((l) => l.status === state.lv);
  const count = (s) => all.filter((l) => l.status === s).length;
  view.innerHTML = head("Leave Management", "Approving leave updates availability and re-checks only the affected roster cells.", `<button class="btn primary" data-act="leave-new">＋ New Leave Request</button>`) +
    `<div class="filters"><div class="seg">${[["PENDING", "Pending"], ["APPROVED", "Approved"], ["REJECTED", "Rejected"], ["ALL", "All"]].map(([k, v]) => `<button class="${state.lv === k ? "on" : ""}" data-act="lv-tab" data-v="${k}">${v}${k !== "ALL" ? ` (${count(k)})` : ""}</button>`).join("")}</div></div>
    <div class="card"><div class="tbl-wrap"><table><thead><tr><th>Employee</th><th>Type</th><th>From</th><th>To</th><th>Days</th><th>Reason</th><th>Status</th><th></th></tr></thead><tbody>
    ${list.map((l) => `<tr><td><b>${esc(l.employee)}</b></td><td>${chip(l.leave_type, "blue")}</td><td>${fmtDate(l.start_date)}</td><td>${fmtDate(l.end_date)}</td><td>${l.days}</td><td class="muted">${esc(l.reason || "")}</td><td>${chip(l.status, l.status)}</td>
      <td>${l.status === "PENDING" ? `<button class="btn sm primary" data-act="lv-approve" data-id="${l.id}">Approve</button> <button class="btn sm danger" data-act="lv-reject" data-id="${l.id}">Reject</button>` : `<button class="btn sm danger" data-act="lv-del" data-id="${l.id}">Delete</button>`}</td></tr>`).join("") || `<tr><td colspan="8" class="empty">Nothing here</td></tr>`}</tbody></table></div></div>`;
};
function showImpact(impact, title = "Roster impact") {
  if (!impact || !impact.affected_entries) { toast("Done · no roster entries were affected", "ok"); return; }
  const nc = impact.new_conflicts;
  modal(title, `<p><b>${impact.affected_entries}</b> roster entr${impact.affected_entries === 1 ? "y was" : "ies were"} updated in ${esc(impact.rosters.join(", "))}. Only those brand-process-days were re-validated.</p>
    ${nc.length ? `<h3 style="margin:12px 0 8px">${nc.length} conflict(s) found</h3><div class="list">${nc.map((c) => `<div class="row" style="align-items:flex-start;flex-direction:column"><div>${chip(c.severity, c.severity)} <b>${esc(c.brand || c.employee || "")}</b> ${esc(c.process || "")} · ${c.date ? fmtDate(c.date) : ""}</div><div class="small muted">${esc(c.description)}</div>
      ${c.backups.length ? `<div class="small">Backup options: ${c.backups.map((b) => `<button class="btn sm" data-act="backup" data-c="${c.id}" data-e="${b.id}">Assign ${esc(b.name)}</button>`).join(" ")}</div>` : ""}</div>`).join("")}</div>` : `<p>✅ Coverage is still met - no conflicts were created.</p>`}`,
    { wide: true, extra: `<a class="btn" href="#/conflicts" data-close>Open Conflicts</a>` });
}

// ------------------------------------------------------------------ conflicts
pages.conflicts = async (view) => {
  const { month, year } = my();
  let roster;
  try { roster = await api(`/rosters/by-month?month=${month}&year=${year}`); } catch (e) { view.innerHTML = head("Conflicts", "") + empty("📅", "No roster yet", `Generate the ${monthLabel()} roster first.`, `<button class="btn primary" data-act="gen">⚡ Generate</button>`); return; }
  const rid = roster.roster.id;
  const all = await api(`/rosters/${rid}/conflicts`);
  const f = state.cv;
  const list = all.filter((c) => (!f.sev || c.severity === f.sev) && (!f.q || JSON.stringify(c).toLowerCase().includes(f.q.toLowerCase())));
  const n = (s) => all.filter((c) => c.severity === s).length;
  view.innerHTML = head("Conflicts", `Explainable validation results for ${monthLabel()}. Acknowledging never hides a conflict from the counts.`, `<button class="btn primary" data-act="revalidate" data-id="${rid}">🔄 Revalidate</button>`) +
    `<div class="grid g4" style="margin-bottom:16px">${[["CRITICAL", "Critical"], ["HIGH", "High"], ["MEDIUM", "Medium"], ["LOW", "Low"]].map(([k, l]) => `<div class="card kpi ${k === "HIGH" || k === "LOW" ? "b" : ""}" style="cursor:pointer" data-act="cv-sev" data-v="${k}"><div class="ic">${{ CRITICAL: "🔴", HIGH: "🟠", MEDIUM: "🟡", LOW: "⚪" }[k]}</div><div><div class="v">${n(k)}</div><div class="l">${l}</div></div></div>`).join("")}</div>
    <div class="filters"><input id="cq" placeholder="Search conflicts" value="${esc(f.q)}"><select id="csev"><option value="">All severities</option>${["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => `<option ${f.sev === s ? "selected" : ""}>${s}</option>`).join("")}</select></div>
    <div class="card"><div class="tbl-wrap"><table><thead><tr><th>Date</th><th>Brand</th><th>Process</th><th>Employee</th><th>Type</th><th>Severity</th><th>Status</th><th></th></tr></thead><tbody>
    ${list.map((c) => `<tr><td>${c.date ? fmtDate(c.date) : ""}</td><td>${esc(c.brand || "-")}</td><td>${esc(c.process || "-")}</td><td>${esc(c.employee || "-")}</td><td>${esc(c.type.replace(/_/g, " ").toLowerCase())}</td><td>${chip(c.severity, c.severity)}</td><td>${chip(c.status, c.status)}</td>
      <td><button class="btn sm" data-act="cv-view" data-id="${c.id}">Details</button></td></tr>`).join("") || `<tr><td colspan="8" class="empty">🎉 No conflicts${f.sev || f.q ? " match" : ""}</td></tr>`}</tbody></table></div></div>`;
  state.cache = all;
  $("#csev").addEventListener("change", (e) => { f.sev = e.target.value; render(); });
  $("#cq").addEventListener("input", (e) => { f.q = e.target.value; const p = e.target.selectionStart; pages.conflicts(view).then(() => { const x = $("#cq"); x.focus(); x.setSelectionRange(p, p); }); });
};
function conflictDetails(id) {
  const c = (state.cache || []).find((x) => String(x.id) === String(id));
  if (!c) return;
  modal(`${c.type.replace(/_/g, " ")}`, `<p>${chip(c.severity, c.severity)} ${chip(c.status, c.status)}</p><p>${esc(c.description)}</p>
    <h3 style="margin:12px 0 6px">Suggested action</h3><p>${esc(c.suggestion)}</p>
    ${c.backups.length ? `<div class="actions">${c.backups.map((b) => `<button class="btn sm primary" data-act="backup" data-c="${c.id}" data-e="${b.id}">Assign ${esc(b.name)} as cover</button>`).join("")}</div>` : ""}`,
    { extra: `<button class="btn" data-act="ack" data-id="${c.id}" data-close>${c.status === "ACKNOWLEDGED" ? "Un-acknowledge" : "Acknowledge"}</button>` });
}

// ------------------------------------------------------------------ teams (pods)
pages.teams = async (view) => {

    resetRef();

    const ref = await refData();
    const pods = await api("/pods");

    // Render one employee row.
    const employeeRow = (emp, included) => {

        const membershipStatus = included
            ? chip("Included", "ok")
            : chip(
                emp.pod_name
                    ? `In ${emp.pod_name}`
                    : "Unassigned",
                emp.pod_name ? "blue" : "LOW"
            );

        return `
            <div class="row">

                <span>
                    <b>${esc(emp.name)}</b>
                    <span class="muted small">
                        ${esc(emp.code || "")}
                    </span>
                </span>

                <span>
                    ${chip(emp.status, emp.status)}
                </span>

            </div>
        `;
    };

    view.innerHTML = head(
        "Pods & Teams",
        "Manage pod leaders, employees and team memberships.",
        `<button class="btn primary" data-act="pod-new">
            ＋ Add Pod
        </button>`
    ) +

    `<div class="grid g3">

        ${pods.map((p) => {

            const employees = p.employees || [];

            // Employees included in this pod.
            const included = employees.filter(
                (e) => e.included
            );

            const notIncluded = employees.filter(
                (e) => !e.included
            );
        
            return `

                <div class="card pod-card">

                    <h2>
                        ${esc(p.name)}

                        <button
                            class="btn sm"
                            data-act="pod-edit"
                            data-id="${p.id}">
                            Edit
                        </button>
                    </h2>

                    <p>
                        👑 <b>Pod Leader:</b>
                        ${esc(p.lead || "No leader assigned")}
                    </p>

                    <p class="muted">
                        ${p.employee_count} active employees
                        · ${p.brands.length} brands
                    </p>

                    <div>
                        ${p.brands.map(
                            (b) => chip(b, "blue")
                        ).join(" ") || "No brands assigned"}
                    </div>

                    <hr>

                    <!-- INCLUDED EMPLOYEES -->

                    <h3>
                        Included Employees (${included.length})
                    </h3>

                    <div class="list pod-employee-list">

                        ${
                            included.length
                                ? included.map(
                                    (e) => employeeRow(e, true)
                                ).join("")
                                : `<p class="muted small">
                                    No employees included.
                                   </p>`
                        }

                    </div>

                    <hr>

                  

                </div>

            `;

        }).join("")}

    </div>`;

    state.pods = pods;
};

// ------------------------------------------------------------------ reports
pages.reports = async (view) => {
  const { month, year } = my();
  const r = await api(`/reports?month=${month}&year=${year}`);
  const bar = (p) => `<div class="bar ${p < 90 ? "low" : ""}"><i style="width:${Math.min(p, 100)}%"></i></div>`;
  view.innerHTML = head("Reports", `Operational analytics for ${monthLabel()}.`, r.roster ? `<button class="btn primary" data-act="export-roster">⬇ Download roster CSV</button>` : "") +
    (!r.roster ? empty("📊", "No roster for this month", "Generate a roster to unlock utilization and coverage reports.", `<button class="btn primary" data-act="gen">⚡ Generate</button>`) :
    `<div class="grid g2"><div class="card"><h2>Brand Coverage</h2><div class="tbl-wrap" style="max-height:360px"><table><thead><tr><th>Brand</th><th>Covered</th><th style="min-width:120px">%</th></tr></thead><tbody>${r.brand_coverage.map((b) => `<tr><td>${esc(b.brand)}</td><td>${b.covered}/${b.required}</td><td>${bar(b.percent)}<span class="small">${b.percent}%</span></td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h2>Process Staffing</h2><table><thead><tr><th>Process</th><th>Covered</th><th>%</th></tr></thead><tbody>${r.process_staffing.map((b) => `<tr><td>${esc(b.process)}</td><td>${b.covered}/${b.required}</td><td>${bar(b.percent)}<span class="small">${b.percent}%</span></td></tr>`).join("")}</tbody></table>
      <h2 style="margin-top:18px">Weekly-off Distribution</h2><table><tbody>${r.weekly_off.map((w) => `<tr><td>${w.day}</td><td style="width:60%">${bar(Math.min(100, w.employees * 100 / Math.max(1, ...r.weekly_off.map((x) => x.employees))))}</td><td>${w.employees}</td></tr>`).join("")}</tbody></table></div>
    <div class="card" style="grid-column:1/-1"><h2>Employee Utilization</h2><div class="tbl-wrap" style="max-height:420px"><table><thead><tr><th>Employee</th><th>Brands</th><th>Working days</th><th>Weekly offs</th><th>Leave days</th><th style="min-width:140px">Utilization</th></tr></thead><tbody>${r.utilization.map((u) => `<tr><td><b>${esc(u.employee)}</b></td><td>${u.brands}</td><td>${u.working}</td><td>${u.weekly_off}</td><td>${u.leave}</td><td>${bar(u.utilization)}<span class="small">${u.utilization}%</span></td></tr>`).join("")}</tbody></table></div></div>
    <div class="card"><h2>Leave Statistics</h2><table><thead><tr><th>Type</th><th>Status</th><th>Days</th></tr></thead><tbody>${r.leave.map((l) => `<tr><td>${esc(l.type)}</td><td>${chip(l.status, l.status)}</td><td>${l.days}</td></tr>`).join("")}</tbody></table></div></div>`);
};

// ------------------------------------------------------------------ settings
pages.settings = async (view) => {
  const hs = await api("/holidays");
  view.innerHTML = head("Settings", "Public holidays drive each brand's operating calendar.", `<button class="btn primary" data-act="hol-new">＋ Add Holiday</button>`) +
    `<div class="grid g2"><div class="card"><h2>Public Holidays</h2><div class="list" style="max-height:420px">${hs.map((h) => `<div class="row"><div><b>${esc(h.name)}</b><div class="muted small">${h.date}</div></div><button class="btn sm danger" data-act="hol-del" data-id="${h.id}">Remove</button></div>`).join("")}</div><p class="small muted">Sample holidays are illustrative - verify them for your region.</p></div>
    <div class="card"><h2>Calendar rules</h2><p><b>365 days</b> - open every day, so holidays and Sundays need coverage.</p><p><b>Closed on public holidays</b> - Sundays are working days.</p><p><b>Closed Sundays &amp; holidays</b> - both are non-working for the client.</p>
      <h2 style="margin-top:18px">Demo data</h2><p class="muted">Reload the sample company (32 employees, 25 brands) and regenerate this and next month's rosters. This erases all current data.</p><button class="btn danger" data-act="reset">Reset demo data</button></div></div>`;
};

// ------------------------------------------------------------------ click actions (event delegation)
const actions = {
  gen: () => generate(),
  mode: (d) => { state.rv.mode = d.v; drawRoster($("#view")); },
  wk: (d) => { state.rv.week += +d.v; drawRoster($("#view")); },
  cell: (d) => editCell(d),
  validate: async () => { try { const r = await api(`/rosters/${state.grid.roster.id}/validate`, { method: "POST" }); toast(`Validated · ${r.summary.conflicts.total} conflict(s)`, r.summary.conflicts.total ? "" : "ok"); render(); } catch (e) { fail(e); } },
  revalidate: async (d) => { try { await api(`/rosters/${d.id}/validate`, { method: "POST" }); toast("Revalidated", "ok"); render(); } catch (e) { fail(e); } },
  publish: publishRoster,
  "export-roster": async () => {
    try { const { month, year } = my(); const g = await api(`/rosters/by-month?month=${month}&year=${year}`); download(`/api/rosters/${g.roster.id}/export.csv`); } catch (e) { fail(e); }
  },
  "emp-new": async () => { await refData(); modal("Add employee", empForm(), { onOk: async (ov) => { await api("/employees", { method: "POST", body: readEmp(ov) }); toast("Employee added", "ok"); render(); } }); },
  "emp-edit": async (d) => { const e = state.ref.employees.find((x) => String(x.id) === d.id); modal("Edit employee", empForm(e), { onOk: async (ov) => { await api(`/employees/${d.id}`, { method: "PUT", body: readEmp(ov) }); toast("Employee updated · re-validate the roster", "ok"); render(); } }); },
  "emp-off": async (d) => { if (await confirmBox("Deactivate employee?", "They will no longer be scheduled when rosters are generated.", "Deactivate")) { try { const r = await api(`/employees/${d.id}`, { method: "DELETE" }); toast(r.message, "ok"); render(); } catch (e) { fail(e); } } },
  "brand-new": () => modal("Add brand", field("Brand name", `<input id="bn">`) + field("Pod", `<select id="bp">${opts(state.ref.pods, "", "No pod")}</select>`), { onOk: async (ov) => { await api("/brands", { method: "POST", body: { name: $("#bn", ov).value.trim(), pod_id: $("#bp", ov).value ? +$("#bp", ov).value : null } }); toast("Brand added · add process rules next", "ok"); render(); } }),
  "brand-edit": (d) => { const b = state.ref.brands.find((x) => String(x.id) === d.id); modal("Edit brand", field("Brand name", `<input id="bn" value="${esc(b.name)}">`) + field("Pod", `<select id="bp">${opts(state.ref.pods, b.pod_id, "No pod")}</select>`) + field("Status", `<select id="bs"><option ${b.status === "ACTIVE" ? "selected" : ""}>ACTIVE</option><option ${b.status === "INACTIVE" ? "selected" : ""}>INACTIVE</option></select>`), { onOk: async (ov) => { await api(`/brands/${d.id}`, { method: "PUT", body: { name: $("#bn", ov).value.trim(), pod_id: $("#bp", ov).value ? +$("#bp", ov).value : null, status: $("#bs", ov).value } }); toast("Brand updated", "ok"); render(); } }); },
  "proc-new": () => modal("Add process", field("Name", `<input id="pn" placeholder="e.g. Reviews">`) + field("Description", `<input id="pd">`), { onOk: async (ov) => { await api("/processes", { method: "POST", body: { name: $("#pn", ov).value.trim(), description: $("#pd", ov).value } }); toast("Process added", "ok"); render(); } }),
  "rule-new": (d) => modal("Add process rule", field("Process", `<select id="rp">${opts(state.ref.processes)}</select>`) + field("Operating calendar", `<select id="rc">${Object.entries(CAL).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select>`) + field("Minimum staff per day", `<input id="rm" type="number" min="0" value="1">`), { onOk: async (ov) => { await api("/rules", { method: "PUT", body: { brand_id: +d.id, process_id: +$("#rp", ov).value, calendar_type: $("#rc", ov).value, min_staff: +$("#rm", ov).value } }); toast("Rule saved", "ok"); render(); } }),
  "as-new": () => modal("New assignment", field("Employee", `<select id="ae">${opts(state.ref.employees.filter((e) => e.status === "ACTIVE"))}</select>`) + field("Brand", `<select id="ab">${opts(state.ref.brands)}</select>`) + field("Process", `<select id="ap">${opts(state.ref.processes)}</select>`), { onOk: async (ov) => { const r = await api("/assignments", { method: "POST", body: { employee_id: +$("#ae", ov).value, brand_id: +$("#ab", ov).value, process_id: +$("#ap", ov).value } }); toast(r.message, "ok"); render(); } }),
  "as-del": async (d) => { if (await confirmBox("Remove assignment?", "The employee will no longer cover this brand-process.", "Remove")) { try { const r = await api(`/assignments/${d.id}`, { method: "DELETE" }); toast(r.message, "ok"); render(); } catch (e) { fail(e); } } },
  "lv-tab": (d) => { state.lv = d.v; render(); },
  "leave-new": () => modal("New leave request", field("Employee", `<select id="le">${opts(state.ref.employees.filter((e) => e.status === "ACTIVE"))}</select>`) + field("Type", `<select id="lt"><option>Casual</option><option>Sick</option><option>Comp-off</option></select>`) + `<div class="grid g2">${field("From", `<input type="date" id="ls">`)}${field("To", `<input type="date" id="lf">`)}</div>` + field("Reason", `<input id="lr">`), { onOk: async (ov) => { const s = $("#ls", ov).value, e = $("#lf", ov).value || s; if (!s) throw new Error("Pick a start date"); await api("/leaves", { method: "POST", body: { employee_id: +$("#le", ov).value, leave_type: $("#lt", ov).value, start_date: s, end_date: e, reason: $("#lr", ov).value } }); toast("Leave request created (pending)", "ok"); render(); } }),
  "lv-approve": async (d) => { try { const r = await api(`/leaves/${d.id}/approve`, { method: "POST" }); await render(); showImpact(r.impact, "Leave approved - roster impact"); } catch (e) { fail(e); } },
  "lv-reject": async (d) => { try { const r = await api(`/leaves/${d.id}/reject`, { method: "POST" }); toast("Leave rejected", "ok"); await render(); if (r.impact) showImpact(r.impact); } catch (e) { fail(e); } },
  "lv-del": async (d) => { if (await confirmBox("Delete leave record?", "If it was approved, affected roster cells will be restored and re-validated.", "Delete")) { try { const r = await api(`/leaves/${d.id}`, { method: "DELETE" }); await render(); if (r.impact) showImpact(r.impact, "Leave removed - roster impact"); } catch (e) { fail(e); } } },
  "cv-sev": (d) => { state.cv.sev = state.cv.sev === d.v ? "" : d.v; render(); },
  "cv-view": (d) => conflictDetails(d.id),
  ack: async (d) => { try { const r = await api(`/conflicts/${d.id}/acknowledge`, { method: "POST" }); toast(r.note, "ok"); render(); } catch (e) { fail(e); } },
  backup: async (d) => { try { const r = await api(`/conflicts/${d.c}/apply-backup`, { method: "POST", body: { employee_id: +d.e } }); document.querySelectorAll(".overlay").forEach((o) => o.remove()); toast(r.remaining.length ? "Cover added, but new issues were found" : "Cover shift added - gap resolved", r.remaining.length ? "" : "ok"); render(); } catch (e) { fail(e); } },
  "pod-new": () => podForm(), "pod-edit": (d) => podForm(state.pods.find((p) => String(p.id) === d.id)),
  "hol-new": () => modal("Add public holiday", field("Date", `<input type="date" id="hd">`) + field("Name", `<input id="hn">`), { onOk: async (ov) => { const r = await api("/holidays", { method: "POST", body: { date: $("#hd", ov).value, name: $("#hn", ov).value.trim() } }); toast(r.message, "ok"); render(); } }),
  "hol-del": async (d) => { try { await api(`/holidays/${d.id}`, { method: "DELETE" }); toast("Holiday removed", "ok"); render(); } catch (e) { fail(e); } },
  reset: async () => { if (await confirmBox("Reset all data?", "This replaces everything with the sample company.", "Reset")) { try { await api("/admin/reset-demo", { method: "POST" }); resetRef(); toast("Demo data reloaded", "ok"); render(); } catch (e) { fail(e); } } },
};
function podForm(p = {}) {

    const employees = state.ref.employees || [];

    // Check whether an employee belongs to this pod.
    const isMember = (e) =>
        Boolean(p.id) &&
        Number(e.pod_id) === Number(p.id);

    // Generate employee membership checkboxes.
    const employeeCheckboxes = employees.map((e) => {

        const included = isMember(e);

        const belongsElsewhere =
            e.pod_id != null && !included;

        const membershipText = belongsElsewhere
            ? `Already in ${e.pod || "another pod"}`
            : included
                ? "Included in this pod"
                : "Unassigned";

        return `

            <label class="member-option">

                <span>

                    <input
                        type="checkbox"
                        class="pod-member"
                        value="${e.id}"
                        ${included ? "checked" : ""}
                        ${belongsElsewhere ? "disabled" : ""}>

                    <b>${esc(e.name)}</b>

                    <span class="muted small">
                        ${esc(e.code || "")}
                    </span>

                </span>

                <span>

                    ${chip(e.status, e.status)}

                    <small>
                        ${esc(membershipText)}
                    </small>

                </span>

            </label>

        `;

    }).join("");


    // Modal content.
    const formContent =

        field(
            "Pod Name",
            `<input
                id="pn"
                value="${esc(p.name || "")}"
                placeholder="Enter pod name">`
        ) +

        field(
            "Employees in this Pod",

            `

                <div class="pod-members">

                    ${employeeCheckboxes || `
                        <p class="muted">
                            No employees available.
                        </p>
                    `}

                </div>

                <p class="muted small">
                    Select employees to include them in this pod.
                    Employees belonging to another pod cannot be selected.
                    Inactive employees can remain members but cannot become leaders.
                </p>

            `
        ) +

        field(
            "Pod Leader",

            `
                <select id="pl">

                    <option value="">
                        No Leader
                    </option>

                </select>

                <small class="muted">
                    Only ACTIVE members of this pod can become leaders.
                </small>
            `
        );


    // Open modal.
    const m = modal(
        p.id ? "Edit Pod" : "Add Pod",
        formContent,
        {
            wide: true,

            onOk: async (ov) => {

                // Get selected employee IDs.
                const member_ids = [
                    ...ov.querySelectorAll(
                        ".pod-member:checked"
                    )
                ].map(
                    (checkbox) => Number(checkbox.value)
                );

                const body = {

                    name: $("#pn", ov).value.trim(),

                    lead_id: $("#pl", ov).value
                        ? Number($("#pl", ov).value)
                        : null,

                    member_ids: member_ids
                };

                if (!body.name) {
                    throw new Error("Pod name is required.");
                }

                // Save pod details.
                await api(
                    p.id ? `/pods/${p.id}` : "/pods",
                    {
                        method: p.id ? "PUT" : "POST",
                        body
                    }
                );

                toast("Pod saved successfully!", "ok");

                resetRef();

                render();
            }
        }
    );


    const ov = m.el;


    // --------------------------------------------------
    // Populate only eligible pod leaders.
    // --------------------------------------------------

    const refreshLeaderOptions = (preferredId = "") => {

        const selectedIds = new Set(

            [...ov.querySelectorAll(".pod-member:checked")]
                .map((checkbox) => Number(checkbox.value))

        );

        // Active members of the currently selected pod.
        const eligibleLeaders = employees.filter(
            (e) =>
                selectedIds.has(Number(e.id)) &&
                e.status === "ACTIVE"
        );

        const select = $("#pl", ov);

        select.innerHTML = `

            <option value="">
                No Leader
            </option>

            ${eligibleLeaders.map((e) => `

                <option value="${e.id}">

                    ${esc(e.name)} (${esc(e.code)})

                </option>

            `).join("")}

        `;

        // Preserve the selected leader if still eligible.
        const validSelection = eligibleLeaders.some(
            (e) => String(e.id) === String(preferredId)
        );

        select.value = validSelection
            ? String(preferredId)
            : "";
    };


    // Initially load eligible leaders.
    refreshLeaderOptions(
        p.lead_id ? String(p.lead_id) : ""
    );


    // Update leader dropdown whenever membership changes.
    ov.addEventListener("change", (event) => {

        if (event.target.matches(".pod-member")) {

            const currentLeader = $("#pl", ov).value;

            refreshLeaderOptions(currentLeader);

        }

    });

}

document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-act]");
  if (!a || !actions[a.dataset.act]) return;
  if (a.tagName === "A") e.preventDefault();
  actions[a.dataset.act](a.dataset, a);
});

render();
