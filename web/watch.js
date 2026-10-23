// "Watch" tab: the simple story view. Plays the newest stored REAL run (recorded playback, labelled),
// one decision moment at a time: the situation, what each coach chose, right or wrong, how fast, what it cost.
import { Pitch } from "./pitch.js";

const $ = (s) => document.querySelector(s);
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NICE = { HIGH_PRESS: "HIGH PRESS", COUNTERATTACK: "COUNTERATTACK", KEEP_POSSESSION: "KEEP POSSESSION", PROTECT_LEAD: "PROTECT LEAD", LOW_BLOCK: "LOW BLOCK" };
const secs = (ms) => (ms == null ? "—" : ms < 1000 ? `${(ms / 1000).toFixed(2)} s` : `${(ms / 1000).toFixed(1)} s`);
const usd = (v) => `$${(v ?? 0).toFixed(3)}`;

const W = { runs: [], run: null, idx: -1, timer: null, playing: false, deadline: 1000, thr: 0.3 };
const pitch = new Pitch($("#w-pitch"));

async function get(path) {
  const r = await fetch(path);
  const body = await r.json().catch(() => null);
  if (!r.ok) throw new Error(body?.error || `HTTP ${r.status}`);
  return body;
}
function fail(msg) { $("#w-source").textContent = msg; $("#w-source").className = "source-label live"; }

const agentFlow = () => ($("#w-help").checked && W.run?.flows.includes("A2") ? "A2" : "A");
const rival = () => (W.run?.flows.includes("B2") ? "B2" : "B1");

function situation(st, event) {
  if (event === "goal_us") return `<span class="goal">⚽ GOAL for BLUE!</span>`;
  if (event === "goal_them") return `<span class="goal them">⚽ GOAL for ORANGE</span>`;
  const bx = st.attack_direction === "right" ? st.ball.x : 40 - st.ball.x;
  const zone = bx > 23 ? "near ORANGE's goal" : bx < 17 ? "near BLUE's own goal" : "in midfield";
  const who = st.possession === "us" ? `<b class="blue">BLUE has the ball</b>` : st.possession === "them" ? `<b class="orange">ORANGE has the ball</b>` : "The ball is loose";
  const d = st.score_us - st.score_them;
  const sc = d > 0 ? `BLUE leads ${st.score_us}–${st.score_them}` : d < 0 ? `BLUE trails ${st.score_us}–${st.score_them}` : `level at ${st.score_us}–${st.score_them}`;
  return `${who} ${zone} · ${sc} · ${st.time_remaining_s} s to go`;
}

const COLORS = ["HIGH_PRESS", "COUNTERATTACK", "KEEP_POSSESSION", "PROTECT_LEAD", "LOW_BLOCK"];
function sureWord(c) { return c >= 0.6 ? "very sure" : c >= W.thr ? "fairly sure" : "unsure"; }

/** Decider's own confidence: the meter, what it means, and how it weighed all five tactics. */
function confidenceBlock(d) {
  const c = d.decider_confidence;
  if (c == null) return `<div class="conf-box"><b>How sure?</b> <span class="muted">Decider returned no confidence</span></div>`;
  const help = agentFlow() === "A2";
  const pct = Math.round(c * 100);
  const probs = d.decider_probabilities || {};
  const parts = COLORS.map((p) => [p, probs[p] ?? 0]).sort((a, b) => b[1] - a[1]);
  const picked = d.raw_decider_policy;
  const rows = parts.map(([p, v]) => `<div class="opt ${p === picked ? "picked" : ""}">
      <span class="opt-name"><i style="background:var(--${p})"></i>${NICE[p]}${p === picked ? " ← its pick" : ""}</span>
      <span class="opt-bar"><i style="width:${v * 100}%;background:var(--${p})"></i></span>
      <span class="opt-pct">${(v * 100).toFixed(1)}%</span></div>`).join("");
  const rule = help
    ? (c >= W.thr ? `Above the ${Math.round(W.thr * 100)}% bar → its own pick is used.` : `Below the ${Math.round(W.thr * 100)}% bar → <b>Nova Pro is asked instead</b>.`)
    : `Its pick is used either way. Tick "Let Nova Pro help" to hand unsure moments to Nova Pro.`;
  return `<div class="conf-box ${c < W.thr ? "low" : ""}">
      <div class="conf-top"><b>How sure is it?</b><span class="conf-pct">${pct}%</span><span class="conf-word">${sureWord(c)}</span><span class="conf-scale" title="Decider's own confidence: its top choice rescaled so that an even 5-way split is 0% and certainty is 100%. Computed by the model, not by us.">0% = pure guess · 100% = certain ⓘ</span></div>
      <div class="conf-meter"><i style="width:${pct}%"></i><b style="left:${W.thr * 100}%" title="${Math.round(W.thr * 100)}% bar"></b></div>
      <div class="conf-rule">${rule}</div>
      <div class="weighed"><span class="muted">Its probability for every tactic (adds up to 100%):</span>${rows}</div>
    </div>`;
}

/** The coaching plan this coach's team is following at moment `upto` (the latest one written). */
function activePlan(flow, upto) {
  for (let i = upto; i >= 0; i--) {
    const r = W.run.ticks[i].lanes[flow];
    if (r?.plan) return { plan: r.plan, at: i };
  }
  return null;
}

/** What the coach tells the BLUE players right now, from the Nova Pro plan in force. */
function speech(kind) {
  const flow = kind === "a" ? agentFlow() : rival();
  const ap = activePlan(flow, W.idx);
  if (!ap) return `<div class="speech"><span class="speech-who">🗣 Coach says</span><p class="muted">No plan yet.</p></div>`;
  const p = ap.plan;
  const role = (r) => p.outfield_instructions.find((o) => o.role === r)?.instruction;
  const fresh = ap.at === W.idx;
  const when = fresh ? "new plan, just written by Nova Pro" : `same plan as moment ${ap.at + 1} — tactic unchanged, so nothing new to say`;
  return `<div class="speech ${fresh ? "fresh" : ""}">
      <span class="speech-who">🗣 Coach tells BLUE <span class="muted">(${when})</span></span>
      <p class="speech-main">"${esc(p.tactical_objective)}${/[.!?]$/.test(p.tactical_objective) ? "" : "."} ${esc(p.immediate_actions[0] ?? "")}"</p>
      <ul class="speech-roles">
        <li><b>Forward:</b> ${esc(role("FWD") ?? "—")}</li>
        <li><b>Midfield:</b> ${esc(role("MID_LEFT") ?? "—")}</li>
        <li><b>Defender:</b> ${esc(role("DEF") ?? "—")}</li>
        <li><b>Keeper:</b> ${esc(p.goalkeeper_instruction)}</li>
      </ul>
    </div>`;
}

function coachCard(kind, r, ref) {
  if (!r) return "";
  const d = r.decision;
  const p = d.effective_policy;
  const ok = ref == null ? null : p === ref;
  const ms = d.decision_latency_ms;
  const fast = ms != null && ms <= W.deadline;
  const fill = Math.min(100, ((ms ?? 0) / (W.deadline * 5)) * 100);   // bar scale: 0..5 s
  let title, sub, steps;
  const tok = (n) => (n == null ? "" : `${n.toLocaleString()} tokens`);
  if (kind === "a") {
    const helped = d.decided_by === "nova_strong" || d.decided_by === "nova_fast";
    const c = d.decider_confidence;
    title = "Coach 1 · Strands Decider 2B";
    sub = `small decision model${agentFlow() === "A2" ? " · Nova Pro helps when unsure" : ""}`;
    steps = [
      `<b>Read</b> the situation as plain sentences${d.decider_input_tokens ? ` (${tok(d.decider_input_tokens)})` : ""}.`,
      `<b>Answered one multiple-choice question</b> — "which of the 5 tactics?" — by scoring all 5 at once. It writes no text. <span class="muted">${secs(d.decider_latency_ms)}, no LLM call</span>`,
      helped
        ? `<b>Was only ${Math.round((c ?? 0) * 100)}% sure</b> (under the ${Math.round(W.thr * 100)}% bar), so it <b>handed the choice to Nova Pro</b>, which picked ${esc(NICE[d.effective_policy] ?? "—")}. <span class="muted">${secs(d.llm_usage?.latency_ms)}, 1 paid call</span>`
        : d.decided_by === "decider" && d.llm_error
          ? `Was unsure, but Nova Pro failed, so <b>its own pick was used</b>.`
          : `<b>Its pick was used</b> as BLUE's tactic${c != null ? ` (${Math.round(c * 100)}% sure)` : ""}.`,
      r.plan_called
        ? `<b>Tactic changed</b> → asked <b>Nova Pro to write a coaching plan</b> for the players. <span class="muted">${secs(r.plan_usage?.latency_ms)}, 1 paid call — the plan does not delay the decision</span>`
        : `<b>Tactic unchanged</b> → kept the current coaching plan. <span class="muted">no call</span>`,
    ];
  } else {
    const u = r.plan_usage || d.llm_usage;
    title = "Coach 2 · LLM only";
    sub = rival() === "B2" ? "Amazon Nova Pro, asked every moment" : "Amazon Nova Micro, asked every moment";
    steps = rival() === "B2" ? [
      `<b>Read</b> the same situation plus the 5 tactic descriptions and instructions${u ? ` (${tok(u.input_tokens)})` : ""}.`,
      `<b>Wrote a reply</b>: chose the tactic <b>and</b> wrote a full coaching plan${u ? ` (${tok(u.output_tokens)} of text)` : ""}. <span class="muted">${secs(d.decision_latency_ms)}, 1 paid call</span>`,
      `<b>Does this at every moment</b>, even when nothing has changed, and gives no measured confidence — so you cannot tell when to doubt it.`,
    ] : [
      `<b>Read</b> the same situation plus the 5 tactic descriptions${d.llm_usage ? ` (${tok(d.llm_usage.input_tokens)})` : ""}.`,
      `<b>Wrote a short reply</b> choosing the tactic and a reason. <span class="muted">${secs(d.decision_latency_ms)}, 1 paid call</span>`,
      r.plan_called ? `<b>Tactic changed</b> → Nova Pro wrote a coaching plan. <span class="muted">${secs(r.plan_usage?.latency_ms)}, 1 paid call</span>`
        : `<b>Tactic unchanged</b> → kept the current plan.`,
    ];
  }
  const how = `<div class="did"><span class="did-title">What it did at this moment</span><ol>${steps.map((x) => `<li>${x}</li>`).join("")}</ol></div>`;
  const plan = r.plan_called && r.plan
    ? `<button class="plan-chip" data-kind="${kind}">📝 ${kind === "a" ? "Tactic changed → Nova Pro wrote a new coaching plan" : "Nova Pro wrote a plan (it does every moment)"} — view</button>` : "";
  return `
    <div class="coach-head"><div><h3>${title}</h3><span>${sub}</span></div></div>
    <div class="coach-pick" style="--c:var(--${p ?? "none"}, #374151)">${esc(NICE[p] ?? "NO ANSWER")}</div>
    ${speech(kind)}
    ${kind === "a" ? confidenceBlock(d) : ""}
    <div class="coach-verdict ${ok === null ? "na" : ok ? "ok" : "no"}">${ok === null ? "No answer key at this moment" : ok ? "✓ Right tactic" : `✗ Should be ${esc(NICE[ref] ?? ref)}`}</div>
    <div class="coach-time"><span>Answered in <b>${secs(ms)}</b></span>
      <div class="tbar"><i style="width:${fill}%;background:${fast ? "var(--ok)" : "var(--bad)"}"></i><b style="left:20%" title="1-second deadline"></b></div>
      <span class="${fast ? "good" : "bad"}">${fast ? "within the 1 s deadline" : "too slow for the 1 s deadline"}</span></div>
    <div class="coach-cost">${r.bedrock_calls ? `<b>${r.bedrock_calls}</b> paid LLM call${r.bedrock_calls > 1 ? "s" : ""} · ${usd(r.cost_usd)}` : `<b>0</b> paid LLM calls · $0.000`}</div>
    ${how}${plan}`;
}

function totals(upto) {
  const sum = (flow) => {
    let right = 0, keyed = 0, fast = 0, ms = 0, calls = 0, cost = 0;
    for (let i = 0; i <= upto; i++) {
      const ev = W.run.ticks[i], r = ev.lanes[flow];
      if (!r) continue;
      const p = r.decision.effective_policy, t = r.decision.decision_latency_ms ?? 0;
      if (ev.reference_policy) { keyed++; right += p === ev.reference_policy; }
      fast += t <= W.deadline; ms += t; calls += r.bedrock_calls; cost += r.cost_usd;
    }
    const n = upto + 1;
    return { right, keyed, pct: keyed ? right / keyed : 0, fast, n, avg: ms / n, calls, cost };
  };
  const a = sum(agentFlow()), b = sum(rival());
  const row = (label, va, vb, better) => `<tr><th>${label}</th><td class="${better === "a" ? "win" : ""}">${va}</td><td class="${better === "b" ? "win" : ""}">${vb}</td></tr>`;
  const cmp = (x, y, hi) => (x === y ? "" : (hi ? x > y : x < y) ? "a" : "b");
  $("#w-totals-title").textContent = `Score after ${upto + 1} of ${W.run.ticks.length} moments`;
  $("#w-table").innerHTML = `<thead><tr><th></th><th class="ca">Strands Decider 2B</th><th class="cb">LLM only (${rival() === "B2" ? "Nova Pro" : "Nova Micro"})</th></tr></thead><tbody>
    ${row("Right tactic", `${a.right}/${a.keyed} (${Math.round(a.pct * 100)}%)`, `${b.right}/${b.keyed} (${Math.round(b.pct * 100)}%)`, cmp(a.pct, b.pct, true))}
    ${row("Answered within 1 s", `${a.fast}/${a.n}`, `${b.fast}/${b.n}`, cmp(a.fast, b.fast, true))}
    ${row("Average answer time", secs(a.avg), secs(b.avg), cmp(a.avg, b.avg, false))}
    ${row("Paid LLM calls", a.calls, b.calls, cmp(a.calls, b.calls, false))}
    ${row("Bedrock cost", usd(a.cost), usd(b.cost), cmp(a.cost, b.cost, false))}</tbody>`;
}

function show(i, anim = 0) {
  const ev = W.run.ticks[i];
  if (!ev) return;
  W.idx = i;
  const st = ev.state;
  pitch.render(st, anim, Math.min(450, anim * 0.35));
  $("#w-score").textContent = `${st.score_us} – ${st.score_them}`;
  const m = Math.floor(st.time_remaining_s / 60);
  $("#w-clock").textContent = `${m}:${String(st.time_remaining_s % 60).padStart(2, "0")}`;
  $("#w-situation").innerHTML = situation(st, ev.event);
  $("#w-moment").textContent = `Moment ${i + 1} of ${W.run.ticks.length}`;
  $("#w-track").style.width = `${((i + 1) / W.run.ticks.length) * 100}%`;
  $("#w-a").innerHTML = coachCard("a", ev.lanes[agentFlow()], ev.reference_policy);
  $("#w-b").innerHTML = coachCard("b", ev.lanes[rival()], ev.reference_policy);
  totals(i);
  renderIO();
}

// ---------- "what each model received and returned" ----------
const promptCache = new Map();
async function prompts(text, policy) {
  const key = `${policy}|${text}`;
  if (!promptCache.has(key)) {
    const r = await fetch("/api/prompts", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ state_text: text, policy: policy || null }) });
    const body = await r.json();
    if (!r.ok) throw new Error(body?.error || `HTTP ${r.status}`);
    promptCache.set(key, body);
  }
  return promptCache.get(key);
}
const pre = (obj) => `<pre>${esc(typeof obj === "string" ? obj : JSON.stringify(obj, null, 2))}</pre>`;
const usage = (u) => (u ? `${u.input_tokens} tokens in · ${u.output_tokens} out · ${secs(u.latency_ms)} · $${(u.cost_usd ?? 0).toFixed(5)}` : "");
function llmBlock(title, p, output, u, open = false) {
  return `<details class="io-call" ${open ? "open" : ""}><summary>${title} <span class="muted small">${esc(p.model)} · ${usage(u)}</span></summary>
    <h5>Input — system prompt</h5>${pre(p.system)}<h5>Input — message</h5>${pre(p.user)}
    <h5>Output (structured, schema ${esc(p.output_schema)}) — as recorded</h5>${pre(output ?? "(no output recorded)")}</details>`;
}

async function renderIO() {
  const box = $("#w-io-body");
  if (!$("#w-io").open || !W.run || W.idx < 0) return;
  const ev = W.run.ticks[W.idx], a = ev.lanes[agentFlow()], b = ev.lanes[rival()];
  try {
    const P = await prompts(ev.state_text, a?.plan_called ? a.decision.effective_policy : null);
    const PB = b?.plan_called && rival() === "B1" ? await prompts(ev.state_text, b.decision.effective_policy) : null;
    const d = a.decision;
    const decOut = { choice: d.raw_decider_policy, confidence: d.decider_confidence, probabilities: d.decider_probabilities,
      server_latency_ms: d.decider_server_latency_ms, round_trip_ms: d.decider_latency_ms, input_tokens: d.decider_input_tokens,
      ...(d.decider_error ? { error: d.decider_error } : {}) };
    const where = W.run.config?.decider_mode === "local" ? `local (${esc(W.run.config.decider_base_url)})` : "hosted API";
    let left = `<h4>Strands Decider 2B <span class="muted small">· ${where} · ${esc(W.run.config?.decider_model_id ?? "")}</span></h4>
      <details class="io-call" open><summary>Decider call <span class="muted small">one typed choice question · no text generated · ${secs(d.decider_latency_ms)}</span></summary>
        <h5>Input — ${esc(P.decider.endpoint)}</h5>${pre(P.decider.body)}
        <h5>Output — as recorded</h5>${pre(decOut)}</details>`;
    if (d.decided_by === "nova_strong" || d.llm_error)
      left += llmBlock("Then Nova Pro was asked (Decider was under the bar)", P.nova_pro_choose,
        d.llm_policy ? { policy: d.llm_policy, reason: d.llm_reason } : { error: d.llm_error }, d.llm_usage);
    if (a.plan_called) left += llmBlock("Nova Pro wrote the coaching plan (tactic changed)", P.nova_pro_plan, a.plan ?? { error: a.plan_error }, a.plan_usage);
    else left += `<p class="muted small">No plan call at this moment: the tactic did not change.</p>`;

    let right = `<h4>LLM only <span class="muted small">· ${rival() === "B2" ? "Nova Pro" : "Nova Micro"} asked every moment</span></h4>`;
    if (rival() === "B2") {
      right += llmBlock("Nova Pro picks the tactic and writes the plan (one call)", P.nova_pro_choose_and_plan,
        b.plan ? { plan: b.plan } : { error: b.plan_error ?? b.decision.llm_error }, b.plan_usage, true);
    } else {
      right += llmBlock("Nova Micro picks the tactic", P.nova_micro_choose,
        b.decision.llm_policy ? { policy: b.decision.llm_policy, reason: b.decision.llm_reason } : { error: b.decision.llm_error }, b.decision.llm_usage, true);
      if (b.plan_called && PB) right += llmBlock("Nova Pro wrote the coaching plan (tactic changed)", PB.nova_pro_plan, b.plan ?? { error: b.plan_error }, b.plan_usage);
    }
    box.innerHTML = `<p class="muted small io-note">Both received the same situation text. Outputs, timings and token counts are exactly as recorded in this run.
      Nova's prompts are rebuilt from the recorded situation text by the same code that sent them (the run stores outputs, not prompts).</p>
      <div class="io-col a">${left}</div><div class="io-col b">${right}</div>`;
  } catch (e) { box.innerHTML = `<p class="bad">Could not build the inputs: ${esc(e.message)}</p>`; }
}
$("#w-io").addEventListener("toggle", renderIO);

function stop() { W.playing = false; clearTimeout(W.timer); $("#w-play").textContent = "▶ Play"; }
function loop() {
  if (!W.playing) return;
  if (W.idx >= W.run.ticks.length - 1) { stop(); return; }
  const ms = 2000 / +$("#w-speed").value;
  show(W.idx + 1, ms * 0.95);
  W.timer = setTimeout(loop, ms);
}
$("#w-play").addEventListener("click", () => {
  if (!W.run) return;
  if (W.playing) { stop(); return; }
  if (W.idx >= W.run.ticks.length - 1) W.idx = -1;
  W.playing = true; $("#w-play").textContent = "❚❚ Pause"; loop();
});
$("#w-restart").addEventListener("click", () => { if (!W.run) return; stop(); pitch.cur = null; show(0); });
$("#w-help").addEventListener("change", () => W.run && show(Math.max(0, W.idx)));
$("#w-match").addEventListener("change", () => load($("#w-match").value));

document.addEventListener("click", (e) => {
  const chip = e.target.closest?.(".plan-chip");
  if (!chip || !W.run) return;
  const r = W.run.ticks[W.idx].lanes[chip.dataset.kind === "a" ? agentFlow() : rival()];
  const p = r?.plan;
  if (!p) return;
  const li = (xs) => xs.map((x) => `<li>${esc(x)}</li>`).join("");
  $("#w-plan-body").innerHTML = `<h3>Coaching plan: ${esc(NICE[p.policy])}</h3>
    <p class="plan-label">Written by Amazon Nova Pro — a model-generated recommendation, not proven strategy.</p>
    <p><b>Goal:</b> ${esc(p.tactical_objective)}</p><p><b>Why:</b> ${esc(p.why_this_policy)}</p>
    <p><b>Goalkeeper:</b> ${esc(p.goalkeeper_instruction)}</p>
    <ul>${p.outfield_instructions.map((o) => `<li><b>${esc(o.role.replace("_", " "))}:</b> ${esc(o.instruction)}</li>`).join("")}</ul>
    <p><b>Do now:</b></p><ul>${li(p.immediate_actions)}</ul>
    <p><b>Risk:</b> ${esc(p.main_risk)} — <b>so:</b> ${esc(p.mitigation)}</p>`;
  $("#w-plan").showModal();
});

async function load(matchId) {
  stop();
  const run = W.runs.find((r) => r.match_id === matchId);
  if (!run) { fail("No recorded real run for this match yet — use Detailed replay → Run live."); return; }
  try {
    W.run = await get(`/api/replay/${run.run_id}`);
  } catch (e) { fail(`Could not load the recorded run: ${e.message}`); return; }
  $("#w-help").disabled = !W.run.flows.includes("A2");
  $("#w-help").parentElement.title = W.run.flows.includes("A2") ? "Nova Pro decides instead when Decider is less than 30% sure"
    : "This recorded run has no 'Nova Pro helps' agent";
  const when = new Date(W.run.started_at).toLocaleString();
  $("#w-source").textContent = `Recorded ${W.run.mode.toUpperCase()} run · ${when}`;
  $("#w-source").className = "source-label recorded";
  pitch.cur = null;
  show(0);
}

(async () => {
  try {
    const h = await get("/api/health?bedrock=false");
    W.deadline = (h.config.decision_deadline_s ?? 1) * 1000;
    W.thr = h.config.confidence_threshold ?? 0.3;
    const reps = (await get("/api/replays")).items.filter((x) => x.status === "done" && (x.flows || []).includes("A"));
    // per match: prefer a real run that has every agent (so the "Nova Pro helps" switch works), newest first
    const score = (r) => (r.mode === "real" ? 4 : 0) + ((r.flows || []).includes("A2") ? 2 : 0);
    const byMatch = {};
    for (const r of reps) {   // reps are newest first
      const cur = byMatch[r.match_id];
      if (!cur || score(r) > score(cur)) byMatch[r.match_id] = r;
    }
    W.runs = Object.values(byMatch);
    const ms = (await get("/api/matches")).items;
    $("#w-match").innerHTML = ms.map((m) => `<option value="${esc(m.id)}">${esc(m.title)}</option>`).join("");
    if (!W.runs.length) { fail("No recorded run yet — open Detailed replay and press Run live."); return; }
    await load(ms.find((m) => byMatch[m.id])?.id ?? ms[0].id);
    $("#w-match").value = W.run.match_id;
  } catch (e) { fail(e.message); }
})();
