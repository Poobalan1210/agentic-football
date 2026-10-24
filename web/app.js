// MatchSense frontend: tabs, API calls, SSE live replay, recorded playback, lab, benchmark.
import { Pitch } from "./pitch.js";

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtMs = (v) => (v == null ? "—" : `${Math.round(v)} ms`);
const fmtUsd = (v) => (v == null ? "—" : `$${Number(v).toFixed(v < 0.01 ? 5 : 4)}`);
const POLICIES = ["HIGH_PRESS", "COUNTERATTACK", "KEEP_POSSESSION", "PROTECT_LEAD", "LOW_BLOCK"];
const pColor = (p) => (p ? `var(--${p})` : "#374151");
const FLOW_NAME = { A: "Brain 1 · our agent — Decider decides", A2: "Brain 1 · our agent — Decider + Nova Pro when unsure",
  B1: "Brain 2 · LLM-only — Nova Micro asked every moment", B2: "Brain 2 · LLM-only — Nova Pro asked every moment" };
const SHORT = { A: "Decider", A2: "Decider + Nova Pro", B1: "Nova Micro only", B2: "Nova Pro only" };
const isOurs = (f) => f === "A" || f === "A2";

let CONFIG = {};
let MODE = "real";

// ---------------------------------------------------------------- errors & fetch
function showError(msg) {
  const box = $("#error-box");
  box.textContent = msg;
  box.hidden = false;
  clearTimeout(showError.t);
  showError.t = setTimeout(() => (box.hidden = true), 12000);
}
async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "content-type": "application/json" }, ...opts });
  let body = null;
  try { body = await res.json(); } catch { /* not json */ }
  if (!res.ok) {
    const msg = body?.error ? `${body.error}${body.details ? "\n" + JSON.stringify(body.details, null, 1) : ""}` : `HTTP ${res.status}`;
    throw new Error(`${path}: ${msg}`);
  }
  return body;
}
async function withLoading(btn, fn) {
  btn.classList.add("loading"); btn.disabled = true;
  try { return await fn(); } catch (e) { showError(e.message); } finally { btn.classList.remove("loading"); btn.disabled = false; }
}

// ---------------------------------------------------------------- tabs
document.querySelectorAll(".tab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach((x) => { x.classList.toggle("active", x === t); x.setAttribute("aria-selected", x === t); });
  document.querySelectorAll(".tabpanel").forEach((p) => (p.hidden = p.id !== `tab-${t.dataset.tab}`));
  if (t.dataset.tab === "lab" && labPitch && labPitch.state) labPitch.render(labPitch.state);
}));

// ---------------------------------------------------------------- health
async function loadHealth() {
  try {
    const h = await api("/api/health");
    CONFIG = h.config; MODE = h.mode;
    const b = $("#mode-badge");
    b.textContent = MODE.toUpperCase(); b.className = `badge mode ${MODE}`;
    $("#mock-banner").hidden = MODE !== "mock";
    const d = $("#decider-status");
    d.textContent = h.decider.ok ? `Decider ✓ ${h.decider.where === "local" ? "LOCAL " + (h.decider.models?.[0]?.device ?? "") : "hosted"} · ${h.decider.models?.[0]?.id ?? ""}` : `Decider ✕ ${(h.decider.error ?? "not ready").slice(0, 60)}`;
    d.className = `pill ${h.decider.ok ? "ok" : "bad"}`;
    const br = $("#bedrock-status");
    br.textContent = h.bedrock.ok ? `Nova on Bedrock ✓ ${CONFIG.aws_region}` : `Bedrock ✕ ${(h.bedrock.error ?? "").slice(0, 60)}`;
    br.className = `pill ${h.bedrock.ok ? "ok" : "bad"}`;
    br.title = `Planner ${CONFIG.nova_planner_model_id} · Fast ${CONFIG.nova_fast_model_id}`;
    $("#b-models").textContent = `Decider: ${CONFIG.decider_model_id} @ ${CONFIG.decider_base_url} · Nova planner: ${CONFIG.nova_planner_model_id} · Nova fast: ${CONFIG.nova_fast_model_id} · region ${CONFIG.aws_region} · deadline ${CONFIG.decision_deadline_s}s (read-only, from .env)`;
    $("#b-threshold").value = CONFIG.confidence_threshold;
    document.querySelectorAll(".thr-pct").forEach((e) => (e.textContent = `${Math.round(CONFIG.confidence_threshold * 100)}%`));
  } catch (e) { showError(e.message); }
}

// ---------------------------------------------------------------- lane rendering (shared)
const pctTxt = (c) => (c == null ? "?" : `${Math.round(c * 100)}%`);
const FB_NAME = { nova_micro: "Nova Micro", nova_pro: "Nova Pro" };

/** One plain-English sentence: what this lane did this tick and why. */
function storyHTML(flow, r) {
  const d = r.decision;
  const pol = (p) => `<b style="color:${pColor(p)}">${esc(p ?? "—")}</b>`;
  let who;
  if (flow === "A") {
    const conf = d.decider_confidence;
    if (d.decider_error) who = `Decider failed (${esc(d.decider_error.split(":")[0])}) → the team keeps ${pol(d.effective_policy)}.`;
    else who = `Decider picked ${pol(d.raw_decider_policy)} (${pctTxt(conf)} sure) — used directly, <b>no LLM call</b>.`;
  } else if (flow === "A2") {
    const conf = d.decider_confidence;
    if (d.decider_error) who = `Decider failed (${esc(d.decider_error.split(":")[0])}).`;
    else who = `Decider picked ${pol(d.raw_decider_policy)}, ${pctTxt(conf)} sure.`;
    if (d.decided_by === "decider" && !d.fallback) who += ` That is above the ${pctTxt(CONFIG.confidence_threshold)} bar, so it is used directly — <b>no LLM needed</b>.`;
    else if (d.decided_by === "decider" && d.llm_error) who += ` Below the bar, but Nova Pro failed, so <b>Decider's pick is used</b>.`;
    else if (d.decided_by === "decider") who += ` Decider's pick is used.`;
    else if (d.decided_by === "hold") who += ` Too unsure, so the team <b>keeps its current tactic</b> ${pol(d.effective_policy)}.`;
    else if (d.decided_by === "nova_fast" || d.decided_by === "nova_strong") who += ` Below the ${pctTxt(CONFIG.confidence_threshold)} bar, so <b>${d.decided_by === "nova_strong" ? "Nova Pro" : "Nova Micro"} decided</b> → ${pol(d.effective_policy)}.`;
    else if (!d.effective_policy) who += " No decision at this moment.";
  } else if (flow === "B1") {
    who = d.effective_policy ? `Nova Micro picked ${pol(d.effective_policy)} (an LLM call at every moment).` : "Nova Micro failed at this moment.";
  } else {
    who = d.effective_policy ? `Nova Pro picked ${pol(d.effective_policy)} <b>and rewrote the whole plan</b> (it does this at every moment).` : "Nova Pro failed at this moment.";
  }
  let plan = "";
  if (flow !== "B2") {
    plan = r.plan_called ? (r.policy_changed ? " Tactic changed → <b>Nova Pro wrote a new coaching plan</b>." : " Nova Pro refreshed the plan.")
                         : " Tactic unchanged → the current plan stays (no plan call).";
  }
  return `<p class="story">${who}${plan}</p>`;
}

function laneHTML(flow, r, totals, { showProbs = false, reference = undefined } = {}) {
  if (!r) return `<div class="lane-head"><h3>${esc(FLOW_NAME[flow] || flow)}</h3></div><p class="muted">Waiting for the first moment…</p>`;
  const d = r.decision;
  const conf = d.decider_confidence;
  const thr = CONFIG.confidence_threshold ?? 0.3;
  const dl = (CONFIG.decision_deadline_s ?? 1) * 1000;
  const err = d.decider_error || d.llm_error || r.plan_error;
  const gate = flow === "A2";
  const confBar = isOurs(flow) && conf != null ? `<div class="confrow"><span class="small muted">Decider sure:</span><div class="confbar" title="Decider confidence${gate ? `; yellow marker = Nova Pro takes over below ${thr}` : ""}"><i style="width:${conf * 100}%;background:${!gate || conf >= thr ? "var(--lane-a)" : "var(--warn)"}"></i>${gate ? `<b style="left:${thr * 100}%"></b>` : ""}</div><span class="small">${pctTxt(conf)}</span></div>` : "";
  const t = totals;
  const counters = t ? `<div class="counters">
      <div class="counter"><b>${t.bedrock_calls}</b><span>LLM (Bedrock) calls so far</span></div>
      <div class="counter"><b>${fmtUsd(t.cost_usd)}</b><span>Bedrock cost so far</span></div>
      <div class="counter"><b>${t.policy_switches}</b><span>tactic changes</span></div>
      <div class="counter"><b>${t.ticks - t.deadline_misses}/${t.ticks}</b><span>decided within ${dl / 1000} s</span></div>
    </div>` : "";
  let probs = "";
  if (showProbs && d.decider_probabilities) {
    probs = `<div class="probs">${POLICIES.map((p) => { const v = d.decider_probabilities[p] ?? 0; return `<span>${p}</span><i style="width:${v * 100}%;background:${pColor(p)}"></i><span>${v.toFixed(3)}</span>`; }).join("")}</div>`;
  }
  const tech = `<details class="tech"><summary>Technical details</summary>
    <dl class="kv">
      <dt>Decided by</dt><dd>${esc(d.decided_by)}${d.fallback_reason ? ` · fallback reason: ${esc(d.fallback_reason)}` : ""}</dd>
      ${isOurs(flow) ? `<dt>Decider raw</dt><dd>${esc(d.raw_decider_policy ?? "—")} · confidence ${conf == null ? "none returned" : conf.toFixed(3)}</dd>
      <dt>Decider time</dt><dd>${fmtMs(d.decider_latency_ms)} <span class="muted">(model ${fmtMs(d.decider_server_latency_ms)})</span></dd>` : ""}
      ${d.llm_reason ? `<dt>LLM reason</dt><dd>${esc(d.llm_reason).slice(0, 160)}</dd>` : ""}
      <dt>Whole moment (incl. plan)</dt><dd>${fmtMs(r.tick_latency_ms)}</dd>
      <dt>This moment</dt><dd>${r.bedrock_calls} Bedrock call(s) · ${r.input_tokens + r.output_tokens} tokens · ${fmtUsd(r.cost_usd)}</dd>
      ${t ? `<dt>Totals</dt><dd>${(t.input_tokens + t.output_tokens).toLocaleString()} tokens · ${t.plan_calls} plan calls${flow === "A2" ? ` · ${t.fallbacks} moments handed to Nova Pro` : ""}</dd>` : ""}
    </dl>${probs}</details>`;
  const fast = d.decision_latency_ms != null && d.decision_latency_ms <= dl;
  return `<div class="lane-head"><h3>${esc(FLOW_NAME[flow] || flow)}</h3><span class="muted small">moment ${r.tick + 1}</span></div>
    <div class="row wrap" style="gap:8px">
      <span class="policy ${r.policy_changed ? "switched" : ""}" style="background:${pColor(d.effective_policy)}">${esc(d.effective_policy ?? "NO DECISION")}</span>
      <span class="flag ${fast ? "ok" : "miss"}" title="time to an effective tactic, deadline ${dl} ms">decided in ${fmtMs(d.decision_latency_ms)}</span>
      ${r.plan_called ? `<span class="flag nova">Nova plan written</span>` : ""}
      ${reference === undefined ? "" : reference === null ? `<span class="flag">no answer key here</span>`
        : d.effective_policy === reference ? `<span class="flag ok">✓ matches answer key</span>` : `<span class="flag miss">✗ answer key: ${esc(reference)}</span>`}
    </div>
    ${confBar}
    ${storyHTML(flow, r)}
    ${err ? `<p class="small" style="color:var(--bad)">Error: ${esc(err).slice(0, 200)}</p>` : ""}
    ${counters}${tech}`;
}
function planHTML(plan, tick, open = false) {
  if (!plan) return "";
  const li = (xs) => xs.map((x) => `<li>${esc(x)}</li>`).join("");
  return `<details class="plan" ${open ? "open" : ""}><summary><span class="policy" style="background:${pColor(plan.policy)};font-size:11px;padding:2px 8px;margin:0 6px 0 0">${esc(plan.policy)}</span>moment ${tick + 1} — ${esc(plan.tactical_objective)}</summary>
    <p class="plan-label">Model-generated recommendation (Amazon Nova), not proven strategy.</p>
    <p><b>Why:</b> ${esc(plan.why_this_policy)}</p>
    <p><b>GK:</b> ${esc(plan.goalkeeper_instruction)}</p>
    <ul>${plan.outfield_instructions.map((o) => `<li><b>${esc(o.role)}:</b> ${esc(o.instruction)}</li>`).join("")}</ul>
    <p><b>Immediate actions</b></p><ul>${li(plan.immediate_actions)}</ul>
    <p><b>Passing / movement:</b> ${esc(plan.passing_movement)}</p>
    <p><b>Main risk:</b> ${esc(plan.main_risk)} — <b>mitigation:</b> ${esc(plan.mitigation)}</p>
    <p><b>Reassess when</b></p><ul>${li(plan.reassess_signals)}</ul>
    <p><b>Alternative:</b> ${esc(plan.alternative_if_changes)}</p></details>`;
}

// ---------------------------------------------------------------- MATCH REPLAY
const rpPitch = new Pitch($("#rp-pitch"));
const RP = { ticks: [], idx: -1, baseline: "B2", agent: "A", source: null, timer: null, playing: false, es: null, runId: null };

/** The decision flow for one moment, as boxes that light up for the steps that happened. */
function renderFlow(ev) {
  const step = (on, n, title, body, kind = "") => `<div class="step ${on ? "on" : "off"} ${kind}"><span class="n">${n}</span><b>${title}</b><span>${body}</span></div>`;
  const arrow = `<span class="arr">→</span>`;
  const pol = (p) => `<b style="color:${pColor(p)}">${esc(p ?? "—")}</b>`;
  const secs = (ms) => (ms == null ? "—" : ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(1)} s`);
  const verdict = (r) => (ev.reference_policy == null ? `<span class="muted">no answer key</span>`
    : r.decision.effective_policy === ev.reference_policy ? `<span class="good">✓ right</span>` : `<span class="bad">✗ answer key: ${esc(ev.reference_policy)}</span>`);
  const plan = (r) => (r.plan_called ? step(true, "", "Nova Pro writes a plan", "the tactic changed, so the coach explains it", "nova")
    : step(false, "", "No new plan", "tactic unchanged — the current plan stays"));
  const result = (r) => `<div class="step result"><b>BLUE plays ${pol(r.decision.effective_policy)}</b><span>${verdict(r)} · ${r.bedrock_calls} paid LLM call${r.bedrock_calls === 1 ? "" : "s"} · decided in ${secs(r.decision.decision_latency_ms)}</span></div>`;

  const a = ev.lanes[RP.agent], b = ev.lanes[RP.baseline];
  const sit = step(true, "1", "Situation → sentences", "code describes the pitch in plain words");
  let row1 = "";
  if (a) {
    const d = a.decision;
    const dec = step(true, "2", "Decider picks a tactic", d.raw_decider_policy ? `${pol(d.raw_decider_policy)} · ${pctTxt(d.decider_confidence)} sure · ${secs(d.decider_latency_ms)} · free (no LLM)` : "failed", "decider");
    let help = "";
    if (RP.agent === "A2") {
      const asked = d.decided_by === "nova_strong" || d.decided_by === "nova_fast" || !!d.llm_error;
      help = arrow + step(asked, "3", asked ? "Decider unsure → ask Nova Pro" : `Decider sure enough (≥ ${pctTxt(CONFIG.confidence_threshold)})`,
        asked ? (d.llm_policy ? `Nova Pro says ${pol(d.llm_policy)} · ${secs(d.llm_usage?.latency_ms)}` : "Nova Pro failed → Decider's pick is used") : "Nova Pro not needed", "nova");
    }
    row1 = `<div class="flow-row a"><div class="who">Brain 1 · our agent<br><small>${esc(SHORT[RP.agent])}</small></div>${sit}${arrow}${dec}${help}${arrow}${plan(a)}${arrow}${result(a)}</div>`;
  }
  let row2 = "";
  if (b) {
    const d = b.decision;
    const llm = RP.baseline === "B2"
      ? step(true, "2", "Nova Pro picks a tactic and writes a full plan", `${pol(d.effective_policy)} · ${secs(d.decision_latency_ms)} · every moment`, "nova")
      : step(true, "2", "Nova Micro picks a tactic", `${pol(d.effective_policy)} · ${secs(d.decision_latency_ms)} · every moment`, "nova");
    row2 = `<div class="flow-row b"><div class="who">Brain 2 · LLM-only<br><small>${esc(SHORT[RP.baseline])}</small></div>${sit}${arrow}${llm}${RP.baseline === "B1" ? arrow + plan(b) : ""}${arrow}${result(b)}</div>`;
  }
  $("#rp-flow").innerHTML = row1 + row2;
  const total = RP.ticks.length && ev.totals ? Math.max(RP.ticks.length, 60) : 60;
  $("#rp-moment").textContent = `Decision moment ${ev.tick + 1} of ${total} · ${clock(ev.state.time_remaining_s)} left — how it was decided`;
}

/** One plain headline for the moment, from BLUE's point of view. */
function situation(st, event) {
  if (event === "goal_us") return `<span class="goal">⚽ GOAL for BLUE!</span>`;
  if (event === "goal_them") return `<span class="goal them">⚽ GOAL for ORANGE</span>`;
  const bx = st.attack_direction === "right" ? st.ball.x : 40 - st.ball.x;
  const zone = bx > 23 ? "in ORANGE's half (near their goal)" : bx < 17 ? "in BLUE's own half (near our goal)" : "around the halfway line";
  const who = st.possession === "us" ? `<b class="blue">BLUE has the ball</b>` : st.possession === "them" ? `<b class="orange">ORANGE has the ball</b>` : "The ball is loose";
  const d = st.score_us - st.score_them;
  const score = d > 0 ? `BLUE is winning ${st.score_us}–${st.score_them}` : d < 0 ? `BLUE is losing ${st.score_us}–${st.score_them}` : `level ${st.score_us}–${st.score_them}`;
  return `${who} ${zone} · ${score} · ${st.time_remaining_s} s left`;
}

function clock(s) { const m = Math.floor(s / 60); return `${m}:${String(s % 60).padStart(2, "0")}`; }

function showTick(i, animMs = 0, ballMs = null) {
  const ev = RP.ticks[i];
  if (!ev) return;
  RP.idx = i;
  const st = ev.state;
  rpPitch.render(st, animMs, ballMs);
  $("#rp-score").textContent = `${st.score_us} – ${st.score_them}`;
  $("#rp-clock").textContent = clock(st.time_remaining_s);
  $("#rp-situation").innerHTML = situation(st, ev.event);
  renderFlow(ev);
  $("#rp-state-text").textContent = ev.state_text;
  $("#rp-state-text").classList.remove("muted");
  
  $("#rp-ref").textContent = ev.reference_policy ?? "unlabelled (ambiguous)";
  $("#rp-ref-reason").textContent = ev.reference_reason ? `— ${ev.reference_reason}` : "";
  if (!ev.lanes[RP.agent]) RP.agent = ev.lanes.A ? "A" : "A2";
  $("#lane-A").innerHTML = laneHTML(RP.agent, ev.lanes[RP.agent], ev.totals[RP.agent], { showProbs: true, reference: ev.reference_policy });
  $("#lane-B").innerHTML = laneHTML(RP.baseline, ev.lanes[RP.baseline], ev.totals[RP.baseline], { reference: ev.reference_policy });
  $("#rp-scrub").max = Math.max(0, RP.ticks.length - 1);
  $("#rp-scrub").value = i;
  renderTimeline();
  renderPlans(i);
}

function renderTimeline() {
  const row = (flow) => `<div class="tl-row"><span>${isOurs(flow) ? "Brain 1" : "Brain 2"}: ${SHORT[flow]}</span><div class="tl-cells">${
    RP.ticks.map((ev, i) => { const r = ev.lanes[flow]; const p = r?.decision.effective_policy;
      return `<span data-i="${i}" class="${i === RP.idx ? "cur" : ""}" style="background:${pColor(p)}" title="moment ${ev.tick + 1}: ${p ?? "none"}${r?.plan_called ? " · Nova plan" : ""}${r?.deadline_missed ? " · deadline missed" : ""}">${r?.plan_called ? "●" : r?.deadline_missed ? "✕" : ""}</span>`; }).join("")}</div></div>`;
  const ref = `<div class="tl-row"><span>Answer key</span><div class="tl-cells">${RP.ticks.map((ev, i) => `<span data-i="${i}" style="background:${pColor(ev.reference_policy)};opacity:.6" title="moment ${ev.tick + 1}: answer key ${ev.reference_policy ?? "none"}"></span>`).join("")}</div></div>`;
  $("#rp-timeline").innerHTML = row(RP.agent) + row(RP.baseline) + ref +
    `<div class="legend"><span><i style="background:#374151"></i>grey = no decision / no answer key for that moment</span></div>`;
}
$("#rp-timeline").addEventListener("click", (e) => { const i = e.target?.dataset?.i; if (i != null && !RP.es) { stopPlayback(); showTick(+i); } });

function renderPlans(upto) {
  for (const [flow, box] of [[RP.agent, "#plans-A"], [RP.baseline, "#plans-B"]]) {
    const items = [];
    for (let i = 0; i <= upto; i++) {
      const r = RP.ticks[i].lanes[flow];
      if (r?.plan && (flow !== "B2" || r.policy_changed || i === 0)) items.push(planHTML(r.plan, RP.ticks[i].tick, false));
    }
    items.reverse();
    if (items.length) items[0] = items[0].replace("<details class=\"plan\" ", "<details class=\"plan\" open ");
    $(box).innerHTML = items.join("") || `<p class="muted">No plan yet.</p>`;
  }
  $("#plans-A-title").firstChild.textContent = `${SHORT[RP.agent]} — Nova plans (one per tactic change) `;
  $("#plans-B-title").firstChild.textContent = `${SHORT[RP.baseline]} — Nova plans ${RP.baseline === "B2" ? "(shown on tactic change; it writes one at every moment) " : ""}`;
}

function setSource(kind, text) {
  const s = $("#rp-source");
  s.textContent = text; s.className = `source-label ${kind}`;
}
function setPlaybackEnabled(on) { ["#rp-play", "#rp-step", "#rp-scrub"].forEach((s) => ($(s).disabled = !on)); }
function stopPlayback() { RP.playing = false; clearTimeout(RP.timer); $("#rp-play").textContent = "▶ Play"; }

function playLoop() {
  if (!RP.playing) return;
  if (RP.idx >= RP.ticks.length - 1) { stopPlayback(); return; }
  const speed = +$("#rp-speed").value;
  const ms = ((CONFIG.tick_seconds ?? 2) * 1000) / speed;
  showTick(RP.idx + 1, ms * 0.95, Math.min(450, ms * 0.35));
  RP.timer = setTimeout(playLoop, ms);
}
$("#rp-play").addEventListener("click", () => {
  if (RP.playing) { stopPlayback(); return; }
  if (RP.idx >= RP.ticks.length - 1) RP.idx = -1;
  RP.playing = true; $("#rp-play").textContent = "❚❚ Pause"; playLoop();
});
$("#rp-step").addEventListener("click", () => { stopPlayback(); if (RP.idx < RP.ticks.length - 1) showTick(RP.idx + 1, 600); });
$("#rp-scrub").addEventListener("input", (e) => { stopPlayback(); showTick(+e.target.value); });

async function loadMatches() {
  const m = await api("/api/matches");
  $("#rp-match").innerHTML = m.items.map((x) => `<option value="${esc(x.id)}">${esc(x.title)} (${x.ticks} decision moments)</option>`).join("");
  rpPreview();
}
async function rpPreview() {
  if (RP.es || RP.ticks.length) return;
  try { const m = await api(`/api/matches/${$("#rp-match").value}`); rpPitch.render(m.ticks[0].state); } catch (e) { showError(e.message); }
}
$("#rp-match").addEventListener("change", () => { if (!RP.es) { RP.ticks = []; rpPreview(); } });
$("#rp-agent").addEventListener("change", (e) => {
  const f = e.target.value;
  if (!RP.es && RP.ticks.length && RP.ticks[0].lanes[f]) { RP.agent = f; showTick(Math.max(0, RP.idx)); }
  else if (!RP.es && RP.ticks.length) showError("This stored run does not include that agent; run it live or pick another run.");
});
$("#rp-baseline").addEventListener("change", (e) => {
  const f = e.target.value;
  if (!RP.es && RP.ticks.length && RP.ticks[0].lanes[f]) { RP.baseline = f; showTick(Math.max(0, RP.idx)); }
});

async function loadStored() {
  try {
    const r = await api("/api/replays");
    $("#rp-stored").innerHTML = `<option value="">—</option>` + r.items.filter((x) => x.status !== "running").map((x) =>
      `<option value="${esc(x.run_id)}">[${x.mode.toUpperCase()}] ${esc(x.match_title ?? x.match_id)} · ${esc((x.flows || [x.baseline]).join("+"))} · ${esc(x.started_at)}${x.status !== "done" ? " (" + esc(x.status) + ")" : ""}</option>`).join("");
  } catch (e) { showError(e.message); }
}

$("#rp-live").addEventListener("click", () => withLoading($("#rp-live"), async () => {
  stopPlayback();
  if (RP.es) RP.es.close();
  RP.baseline = $("#rp-baseline").value; RP.agent = $("#rp-agent").value;
  const r = await api("/api/replay/run", { method: "POST", body: JSON.stringify({ match_id: $("#rp-match").value, agent: RP.agent, baseline: RP.baseline, paced: $("#rp-paced").checked }) });
  RP.ticks = []; RP.idx = -1; RP.runId = r.run_id;
  setPlaybackEnabled(false);
  $("#rp-stop").disabled = false;
  setSource("live", r.mode === "mock" ? `● LIVE MOCK run — fixtures, NOT real model results (${r.run_id})` : `● LIVE REAL run — real Decider + Nova calls, real timing (${r.run_id})`);
  const es = new EventSource(`/api/replay/${r.run_id}/stream`);
  RP.es = es;
  es.addEventListener("tick", (msg) => {
    const ev = JSON.parse(msg.data);
    RP.ticks.push(ev);
    showTick(RP.ticks.length - 1, Math.min(1800, (CONFIG.tick_seconds ?? 2) * 900));
  });
  es.addEventListener("end", (msg) => {
    const ev = JSON.parse(msg.data);
    es.close(); RP.es = null;
    $("#rp-stop").disabled = true;
    setPlaybackEnabled(true);
    if (ev.status === "error") showError(`Run failed: ${ev.error}`);
    setSource("recorded", `Live run finished (${ev.status}) — now stored as ${RP.runId}`);
    loadStored();
  });
  es.onerror = () => { if (RP.es) { showError("Live stream disconnected. The run continues on the server; open it from Stored runs when it finishes."); es.close(); RP.es = null; $("#rp-stop").disabled = true; setPlaybackEnabled(true); } };
}));
$("#rp-stop").addEventListener("click", async () => { if (RP.runId) { try { await api(`/api/replay/${RP.runId}/stop`, { method: "POST" }); } catch (e) { showError(e.message); } } });

$("#rp-load").addEventListener("click", () => withLoading($("#rp-load"), async () => {
  const id = $("#rp-stored").value;
  if (!id) throw new Error("pick a stored run first");
  if (RP.es) { RP.es.close(); RP.es = null; }
  stopPlayback();
  const run = await api(`/api/replay/${id}`);
  RP.ticks = run.ticks; RP.baseline = run.baseline || run.flows.find((f) => !isOurs(f)); RP.runId = id;
  RP.agent = run.flows.includes($("#rp-agent").value) ? $("#rp-agent").value : (run.agent || run.flows.find(isOurs));
  $("#rp-agent").value = RP.agent;
  if (run.flows.includes($("#rp-baseline").value)) RP.baseline = $("#rp-baseline").value; else $("#rp-baseline").value = RP.baseline;
  setSource("recorded", `Recorded ${run.mode.toUpperCase()} run — ${run.started_at} · ${run.match_title}${run.note ? " · " + run.note.replace("ticks run back to back", "moments run back to back") : ""} · latencies shown are as measured then`);
  setPlaybackEnabled(true);
  rpPitch.cur = null;
  showTick(0);
}));

// ---------------------------------------------------------------- MATCH LAB
let SCEN = [];
let labPitch = null;
let OPTIONS = {}; let QUESTION = "";
let labState = null; let labRef = null;

function fillForm(st) {
  $("#f-score-us").value = st.score_us; $("#f-score-them").value = st.score_them;
  $("#f-time").value = st.time_remaining_s; $("#f-poss").value = st.possession;
  $("#f-stamina").value = st.stamina; $("#f-density").value = st.opponent_density_near_ball ?? "";
  $("#f-objective").value = st.objective; $("#f-press").checked = !!st.opponent_pressing; $("#f-block").checked = !!st.opponent_low_block;
}
function readForm() {
  const st = structuredClone(labState);
  st.score_us = +$("#f-score-us").value; st.score_them = +$("#f-score-them").value;
  st.time_remaining_s = +$("#f-time").value; st.possession = $("#f-poss").value;
  st.stamina = +$("#f-stamina").value;
  const dn = $("#f-density").value; st.opponent_density_near_ball = dn === "" ? null : +dn;
  st.objective = $("#f-objective").value; st.opponent_pressing = $("#f-press").checked; st.opponent_low_block = $("#f-block").checked;
  return st;
}
let textTimer = null;
function labEdited(fromPitch) {
  if (fromPitch) labState = structuredClone(labPitch.state);
  labState = readForm();
  labRef = null;
  $("#lab-ref").textContent = "— (edited state; no reference label)"; $("#lab-ref-reason").textContent = "";
  clearTimeout(textTimer);
  textTimer = setTimeout(updateLabText, 200);
}
async function updateLabText() {
  try { const r = await api("/api/state_text", { method: "POST", body: JSON.stringify({ state: labState }) }); $("#lab-text").textContent = r.state_text; }
  catch (e) { $("#lab-text").textContent = ""; showError(e.message); }
}
function selectScenario(id) {
  const s = SCEN.find((x) => x.id === id);
  labState = structuredClone(s.state); labRef = s.reference;
  fillForm(labState);
  labPitch.cur = null; labPitch.render(labState);
  $("#lab-ref").textContent = labRef?.policy ?? "unlabelled"; $("#lab-ref-reason").textContent = labRef?.reason ? `— ${labRef.reason}` : "";
  updateLabText();
}
async function loadScenarios() {
  const r = await api("/api/scenarios");
  SCEN = r.items; OPTIONS = r.options; QUESTION = r.question;
  const base = SCEN.filter((s) => s.kind === "base");
  $("#lab-scenario").innerHTML = base.map((b) => `<optgroup label="${esc(b.title)}">${SCEN.filter((s) => s.base_id === b.id).map((s) =>
    `<option value="${esc(s.id)}">${s.kind === "base" ? "★ " : ""}${esc(s.kind === "base" ? s.title : s.title.split(" — ")[1] || s.title)}</option>`).join("")}</optgroup>`).join("");
  labPitch = new Pitch($("#lab-pitch"), { editable: true, onChange: () => labEdited(true) });
  selectScenario(SCEN[0].id);
}
$("#lab-scenario").addEventListener("change", (e) => selectScenario(e.target.value));
["#f-score-us", "#f-score-them", "#f-time", "#f-poss", "#f-stamina", "#f-density", "#f-objective", "#f-press", "#f-block"].forEach((s) => $(s).addEventListener("change", () => labEdited(false)));

async function labRun(flows, btn) {
  const bl = $("#lab-baseline").value;
  for (const f of flows) {
    const box = isOurs(f) ? "#lab-A" : "#lab-B";
    $(box).innerHTML = `<div class="lane-head"><h3>${esc(FLOW_NAME[f])}</h3></div><p class="muted">Running… (real calls in REAL mode)</p>`;
  }
  await withLoading(btn, async () => {
    const usesScenario = labRef !== null;
    const body = usesScenario ? { scenario_id: $("#lab-scenario").value, flows } : { state: labState, flows };
    const r = await api("/api/lab/run", { method: "POST", body: JSON.stringify(body) });
    for (const f of flows) {
      const res = r.results[f];
      const box = isOurs(f) ? "#lab-A" : "#lab-B";
      $(box).innerHTML = laneHTML(f, res, null, { showProbs: isOurs(f) }) +
        (res.plan ? `<h4>Nova plan</h4>${planHTML(res.plan, 0, true)}` : res.plan_called ? "" : `<p class="muted small">No plan call.</p>`) +
        `<p class="muted small">${r.mode === "mock" ? "MOCK MODE — NOT A REAL MODEL RESULT" : "Real model result"}${r.reference ? ` · reference: ${esc(r.reference.policy)}` : ""}</p>`;
      if (isOurs(f)) renderExplain(r, res);
    }
  });
}
function renderExplain(r, res) {
  const d = res.decision;
  const request = { state: r.state_text, questions: { policy: { type: "choice", instructions: r.question, criteria: r.options } } };
  $("#lab-explain-body").innerHTML = `
    <ol>
      <li><b>State → sentences.</b> Code computes the geometry; Decider reads plain text.</li>
      <li><b>One typed choice question</b> goes to Strands Decider 2B (<code>POST /v1/decide</code>). It never writes text.</li>
      <li><b>Confidence gate.</b> Decider's own confidence ≥ ${CONFIG.confidence_threshold} → use it; otherwise Nova Micro picks from the same options and state (fallback).</li>
      <li><b>Nova Pro writes a plan only when the effective policy changes</b> (or a fallback fired).</li>
    </ol>
    <h4>Request sent to Decider</h4><pre>${esc(JSON.stringify(request, null, 1))}</pre>
    <h4>Decider answer (as recorded)</h4><pre>${esc(JSON.stringify({ choice: d.raw_decider_policy, confidence: d.decider_confidence, probabilities: d.decider_probabilities, client_latency_ms: d.decider_latency_ms, server_latency_ms: d.decider_server_latency_ms, error: d.decider_error }, null, 1))}</pre>
    <h4>Outcome</h4><pre>${esc(JSON.stringify({ effective_policy: d.effective_policy, decided_by: d.decided_by, fallback: d.fallback, fallback_reason: d.fallback_reason, nova_fallback_policy: d.llm_policy, plan_called: res.plan_called }, null, 1))}</pre>`;
}
$("#lab-run-a").addEventListener("click", (e) => labRun([$("#lab-agent").value], e.currentTarget));
$("#lab-run-b").addEventListener("click", (e) => labRun([$("#lab-baseline").value], e.currentTarget));
$("#lab-run-both").addEventListener("click", (e) => labRun([$("#lab-agent").value, $("#lab-baseline").value], e.currentTarget));

// ---------------------------------------------------------------- BENCHMARK
const charts = {};
function chart(id, cfg) {
  if (!window.Chart) { return; }
  charts[id]?.destroy();
  Chart.defaults.color = "#8ea3aa"; Chart.defaults.borderColor = "#27383f";
  charts[id] = new Chart(document.getElementById(id), cfg);
}
const FLOW_COLORS = { A: "#22d3a6", A2: "#38bdf8", B1: "#a78bfa", B2: "#f472b6" };
const pct = (r) => (r?.value == null ? "—" : `${(r.value * 100).toFixed(1)}%`);
const nTag = (n) => `<span class="nval"> n=${n}</span>`;

function renderBench(res, jobId) {
  $("#b-results").hidden = false;
  const s = res.summary;
  if (!s) { $("#b-table").innerHTML = "<tr><td>No rows.</td></tr>"; return; }
  $("#b-title").textContent = `Results — ${res.mode.toUpperCase()} · ${res.finished_at} · ${s.n_rows} trial rows`;
  $("#b-csv").href = `/api/export/${jobId}.csv`; $("#b-json").href = `/api/export/${jobId}.json`;
  const flows = Object.keys(s.flows);
  const small = flows.filter((f) => s.flows[f].small_n_warning);
  $("#b-warn").hidden = !small.length && res.mode !== "mock";
  $("#b-warn").textContent = (res.mode === "mock" ? "MOCK MODE — NOT A REAL MODEL RESULT. " : "") + (small.length ? `Small sample: fewer than ${s.small_n_threshold} labelled items for ${small.join(", ")}. Treat differences as indicative only.` : "");
  const F = s.flows;
  const rows = [
    ["Effective accuracy", (f) => pct(F[f].accuracy) + nTag(F[f].accuracy.n)],
    ["Decider's own pick accuracy", (f) => (F[f].raw_decider_accuracy ? pct(F[f].raw_decider_accuracy) + nTag(F[f].raw_decider_accuracy.n) : "—")],
    ["Moments handed to Nova Pro", (f) => (f === "A2" && F[f].fallback_rate ? pct(F[f].fallback_rate) + nTag(F[f].fallback_rate.n) : "—")],
    ["Decision latency p50", (f) => fmtMs(F[f].decision_latency_p50_ms) + nTag(F[f].n)],
    ["Decision latency p95", (f) => fmtMs(F[f].decision_latency_p95_ms) + nTag(F[f].n)],
    ["Decider-only latency p50 / p95", (f) => (F[f].decider_latency_p50_ms != null ? `${fmtMs(F[f].decider_latency_p50_ms)} / ${fmtMs(F[f].decider_latency_p95_ms)}` : "—")],
    ["Whole moment incl. plan p50 / p95", (f) => `${fmtMs(F[f].tick_latency_p50_ms)} / ${fmtMs(F[f].tick_latency_p95_ms)}`],
    ["Deadline-miss rate", (f) => pct(F[f].deadline_miss_rate) + nTag(F[f].deadline_miss_rate.n)],
    ["Bedrock calls (total)", (f) => F[f].bedrock_calls],
    ["Plan calls (total)", (f) => F[f].plan_calls],
    ["Plan-schema valid rate", (f) => pct(F[f].plan_schema_valid_rate) + nTag(F[f].plan_schema_valid_rate.n)],
    ["Tokens in / out", (f) => `${F[f].input_tokens.toLocaleString()} / ${F[f].output_tokens.toLocaleString()}`],
    ["Bedrock cost (total)", (f) => fmtUsd(F[f].cost_usd)],
    ["Bedrock cost per 1,000 decisions", (f) => fmtUsd(F[f].bedrock_cost_per_1000_decisions_usd)],
    ["Per match: Bedrock calls", (f) => (F[f].per_match ? F[f].per_match.bedrock_calls + nTag(F[f].per_match.n_matches) : "—")],
    ["Per match: tokens", (f) => (F[f].per_match ? F[f].per_match.tokens.toLocaleString() : "—")],
    ["Per match: cost", (f) => (F[f].per_match ? fmtUsd(F[f].per_match.cost_usd) : "—")],
    ["Errors / incomplete", (f) => `${F[f].errors} / ${F[f].incomplete}`],
  ];
  $("#b-table").innerHTML = `<thead><tr><th>Metric</th>${flows.map((f) => `<th style="color:${FLOW_COLORS[f]}" title="${esc(FLOW_NAME[f])}">${esc(SHORT[f])}</th>`).join("")}</tr></thead><tbody>` +
    rows.map(([name, fn]) => `<tr><td>${name}</td>${flows.map((f) => `<td>${fn(f)}</td>`).join("")}</tr>`).join("") +
    `<tr><td>Agreement</td><td colspan="${flows.length}">${Object.entries(s.agreement).map(([k, v]) => `${k}: ${pct(v)}${nTag(v.n)}`).join(" · ")}</td></tr></tbody>`;
  $("#b-buckets").innerHTML = `<table class="metrics"><thead><tr><th>Confidence</th><th>Accuracy</th></tr></thead><tbody>${s.confidence_buckets.map((b) => `<tr><td>${b.range}</td><td>${pct(b)}${nTag(b.n)}</td></tr>`).join("")}</tbody></table>`;
  $("#b-sweep").innerHTML = `<table class="metrics"><thead><tr><th>Threshold</th><th>Accuracy</th><th>Decider share</th></tr></thead><tbody>${s.threshold_sweep.map((t) => `<tr><td>${t.threshold}</td><td>${t.accuracy == null ? "—" : (t.accuracy * 100).toFixed(1) + "%"}${nTag(t.n)}</td><td>${t.decider_share == null ? "—" : (t.decider_share * 100).toFixed(0) + "%"}</td></tr>`).join("")}</tbody></table>`;
  const ds = (label, fn, i) => ({ label, data: flows.map(fn), backgroundColor: flows.map((f) => FLOW_COLORS[f] + (i ? "88" : "")) });
  const opts = { plugins: { legend: { display: true } }, scales: { y: { beginAtZero: true } } };
  chart("c-lat", { type: "bar", data: { labels: flows.map((f) => SHORT[f]), datasets: [ds("p50", (f) => F[f].decision_latency_p50_ms, 0), ds("p95", (f) => F[f].decision_latency_p95_ms, 1)] }, options: opts });
  chart("c-acc", { type: "bar", data: { labels: flows.map((f) => SHORT[f]),
    datasets: [{ label: "accuracy %", data: flows.map((f) => (F[f].accuracy.value == null ? null : F[f].accuracy.value * 100)),
      backgroundColor: flows.map((f) => FLOW_COLORS[f]) }] }, options: { ...opts, scales: { y: { beginAtZero: true, max: 100 } } } });
  const hasMatch = flows.some((f) => F[f].per_match);
  chart("c-calls", { type: "bar", data: { labels: flows.map((f) => SHORT[f]), datasets: [{ label: hasMatch ? "Bedrock calls / match" : "run matches suite to fill", data: flows.map((f) => F[f].per_match?.bedrock_calls ?? null), backgroundColor: flows.map((f) => FLOW_COLORS[f]) }] }, options: opts });
  chart("c-cost", { type: "bar", data: { labels: flows.map((f) => SHORT[f]), datasets: [{ label: hasMatch ? "USD / match (Bedrock only)" : "run matches suite to fill", data: flows.map((f) => F[f].per_match?.cost_usd ?? null), backgroundColor: flows.map((f) => FLOW_COLORS[f]) }] }, options: opts });
}

async function pollBench(jobId) {
  const j = await api(`/api/benchmark/${jobId}`);
  $("#b-bar").style.width = `${(j.progress ?? 0) * 100}%`;
  $("#b-progress").textContent = `${j.status} · ${j.done ?? 0}/${j.total ?? "?"} items${j.error ? " · " + j.error : ""}`;
  if (j.status === "error") { showError(`Benchmark failed: ${j.error}`); $("#b-run").disabled = false; return; }
  if (j.result) { renderBench(j.result, jobId); $("#b-run").disabled = false; loadBenchList(); return; }
  setTimeout(() => pollBench(jobId).catch((e) => showError(e.message)), 1500);
}
$("#b-run").addEventListener("click", async () => {
  const suites = [$("#b-variants").checked && "variants", $("#b-matches").checked && "matches"].filter(Boolean);
  if (!suites.length) { showError("Pick at least one suite."); return; }
  const body = { suites, flows: ["A", "A2", "B1", "B2"], trials: +$("#b-trials").value || 1, threshold: +$("#b-threshold").value };
  if ($("#b-max").value) body.max_items = +$("#b-max").value;
  try {
    $("#b-run").disabled = true;
    const r = await api("/api/benchmark/run", { method: "POST", body: JSON.stringify(body) });
    $("#b-progress").textContent = `started ${r.job_id} (${r.mode})`;
    pollBench(r.job_id);
  } catch (e) { showError(e.message); $("#b-run").disabled = false; }
});
async function loadBenchList() {
  try {
    const r = await api("/api/benchmarks");
    $("#b-stored").innerHTML = `<option value="">—</option>` + r.items.map((x) => `<option value="${esc(x.job_id)}">[${x.mode.toUpperCase()}] ${esc(x.finished_at)} · ${esc((x.config?.suites || []).join("+"))}</option>`).join("");
    // show the newest real benchmark that has all four agents, without a click (handy for demos)
    const best = r.items.find((x) => x.mode === "real" && (x.config?.flows || []).length >= 4) || r.items.find((x) => x.mode === "real");
    if (best && $("#b-results").hidden) {
      $("#b-stored").value = best.job_id;
      api(`/api/benchmark/${best.job_id}`).then((j) => j.result && renderBench(j.result, best.job_id)).catch((e) => showError(e.message));
    }
  } catch (e) { showError(e.message); }
}
$("#b-load").addEventListener("click", () => withLoading($("#b-load"), async () => {
  const id = $("#b-stored").value; if (!id) throw new Error("pick a stored benchmark");
  const j = await api(`/api/benchmark/${id}`); renderBench(j.result, id);
}));

// ---------------------------------------------------------------- boot
(async () => {
  await loadHealth();
  await Promise.all([loadMatches(), loadScenarios(), loadStored(), loadBenchList()].map((p) => p.catch((e) => showError(e.message))));
})();
