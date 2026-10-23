// Hand-built SVG five-a-side pitch (40 m x 20 m) with smooth interpolation between states.
const NS = "http://www.w3.org/2000/svg";
const L = 40, W = 20, S = 20, PAD = 16;   // 20 px per metre
const VW = L * S + PAD * 2, VH = W * S + PAD * 2;

const el = (tag, attrs = {}, parent) => {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (parent) parent.appendChild(e);
  return e;
};
// pitch y=0 is bottom; SVG y grows down
const px = (x) => PAD + x * S;
const py = (y) => PAD + (W - y) * S;
const ROLE_LABEL = { GK: "GK", DEF: "D", MID: "M", FWD: "F" };

export class Pitch {
  constructor(container, { editable = false, onChange = null } = {}) {
    this.container = container;
    this.editable = editable;
    this.onChange = onChange;
    this.svg = el("svg", { viewBox: `0 0 ${VW} ${VH}`, role: "img", "aria-label": "Five-a-side pitch" });
    container.innerHTML = "";
    container.appendChild(this.svg);
    this._drawField();
    this.layer = el("g", {}, this.svg);
    this.nodes = {};
    this.cur = null;     // current displayed positions {id: [x,y]}
    this.anim = null;
    this.state = null;
  }

  _drawField() {
    const g = el("g", {}, this.svg);
    el("rect", { x: 0, y: 0, width: VW, height: VH, fill: "#0f3d27", rx: 12 }, g);
    for (let i = 0; i < 8; i++) {
      el("rect", { x: px(i * 5), y: py(W), width: 5 * S, height: W * S, fill: i % 2 ? "var(--pitch-2)" : "var(--pitch)" }, g);
    }
    const line = { fill: "none", stroke: "var(--pitch-line)", "stroke-width": 2 };
    el("rect", { x: px(0), y: py(W), width: L * S, height: W * S, ...line }, g);
    el("line", { x1: px(L / 2), y1: py(W), x2: px(L / 2), y2: py(0), ...line }, g);
    el("circle", { cx: px(L / 2), cy: py(W / 2), r: 3 * S, ...line }, g);
    el("circle", { cx: px(L / 2), cy: py(W / 2), r: 3, fill: "var(--pitch-line)" }, g);
    // penalty areas (6 m semicircle-ish boxes) and goals (3 m wide)
    for (const side of [0, 1]) {
      const x0 = side ? L - 6 : 0;
      el("rect", { x: px(x0), y: py(W / 2 + 5), width: 6 * S, height: 10 * S, ...line }, g);
      const gx = side ? px(L) : px(0) - 10;
      el("rect", { x: gx, y: py(W / 2 + 1.5), width: 10, height: 3 * S, fill: "rgba(255,255,255,.25)", stroke: "#fff", "stroke-width": 2 }, g);
    }
    this.arrow = el("g", { opacity: 0.85 }, this.svg);
    this.arrowText = null;
  }

  _drawArrow(dir) {
    this.arrow.innerHTML = "";
    // goal labels: which goal is whose
    const blueGoalLeft = dir === "right";
    const lab = (x, txt, color) => { const t = el("text", { x, y: py(W / 2) - 3 * S - 8, "text-anchor": "middle", fill: color, "font-size": 11, "font-weight": 700 }, this.arrow); t.textContent = txt; };
    lab(px(3), blueGoalLeft ? "BLUE goal" : "ORANGE goal", blueGoalLeft ? "var(--us)" : "var(--them)");
    lab(px(L - 3), blueGoalLeft ? "ORANGE goal" : "BLUE goal", blueGoalLeft ? "var(--them)" : "var(--us)");
    const y = py(W) - 6 + 4;
    const x1 = px(L / 2 - 4), x2 = px(L / 2 + 4);
    const [a, b] = dir === "left" ? [x2, x1] : [x1, x2];
    el("line", { x1: a, y1: PAD / 2 + 2, x2: b, y2: PAD / 2 + 2, stroke: "var(--us)", "stroke-width": 3 }, this.arrow);
    const tip = dir === "left" ? b + 8 : b - 8;
    el("polygon", { points: `${b},${PAD / 2 + 2} ${tip},${PAD / 2 - 3} ${tip},${PAD / 2 + 7}`, fill: "var(--us)" }, this.arrow);
    const t = el("text", { x: px(L / 2 + 4) + 14, y: PAD / 2 + 6, "text-anchor": "start", fill: "var(--us)", "font-size": 12, "font-weight": 700 }, this.arrow);
    t.textContent = `BLUE attacks ${dir === "left" ? "← this way" : "this way →"}`;
  }

  _ensureNodes(state) {
    const all = [...state.us.map((p) => ["us", p]), ...state.them.map((p) => ["them", p])];
    const want = new Set(all.map(([, p]) => p.id).concat(["ball"]));
    for (const id of Object.keys(this.nodes)) if (!want.has(id)) { this.nodes[id].remove(); delete this.nodes[id]; }
    for (const [team, p] of all) {
      if (this.nodes[p.id]) continue;
      const g = el("g", { class: `player ${team}`, "data-id": p.id, style: this.editable ? "cursor:grab" : "" }, this.layer);
      el("circle", { r: 13, fill: team === "us" ? "var(--us)" : "var(--them)", stroke: p.role === "GK" ? "#fff" : "#0b1215", "stroke-width": p.role === "GK" ? 3 : 2 }, g);
      const t = el("text", { "text-anchor": "middle", dy: 4, "font-size": 11, "font-weight": 800, fill: "#0b1215" }, g);
      t.textContent = ROLE_LABEL[p.role];
      this.nodes[p.id] = g;
      if (this.editable) this._makeDraggable(g, p.id);
    }
    if (!this.nodes.ball) {
      const g = el("g", { class: "ball", style: this.editable ? "cursor:grab" : "" }, this.layer);
      el("circle", { r: 7, fill: "#fff", stroke: "#111", "stroke-width": 2 }, g);
      this.nodes.ball = g;
      if (this.editable) this._makeDraggable(g, "ball");
    } else {
      this.layer.appendChild(this.nodes.ball); // keep ball on top
    }
  }

  _markCarrier(state) {
    const side = state.possession === "us" ? state.us : state.possession === "them" ? state.them : [];
    let best = null, bd = 1e9;
    for (const p of side) { const d = Math.hypot(p.x - state.ball.x, p.y - state.ball.y); if (d < bd) { bd = d; best = p.id; } }
    for (const [id, n] of Object.entries(this.nodes)) {
      if (id === "ball") continue;
      let ring = n.querySelector(".carrier");
      if (id === best && !ring) { ring = el("circle", { r: 18, fill: "none", stroke: "#fde047", "stroke-width": 3, class: "carrier" }); n.insertBefore(ring, n.firstChild); }
      if (id !== best && ring) ring.remove();
    }
  }

  _targets(state) {
    const t = {};
    for (const p of [...state.us, ...state.them]) t[p.id] = [p.x, p.y];
    t.ball = [state.ball.x, state.ball.y];
    return t;
  }

  _place(pos) {
    for (const [id, [x, y]] of Object.entries(pos)) {
      const n = this.nodes[id];
      if (n) n.setAttribute("transform", `translate(${px(x)},${py(y)})`);
    }
  }

  /** Show a state. Players glide over `ms`; the ball moves like a pass, over `ballMs` (default 30% of ms). */
  render(state, ms = 0, ballMs = null) {
    this.state = state;
    this._ensureNodes(state);
    this._drawArrow(state.attack_direction);
    this._markCarrier(state);
    const target = this._targets(state);
    if (this.anim) cancelAnimationFrame(this.anim);
    if (!this.cur || ms <= 0) { this.cur = target; this._place(target); return; }
    const from = { ...this.cur };
    const bms = Math.max(120, Math.min(ballMs ?? ms * 0.3, 500));
    this._trail(from.ball, target.ball);
    const t0 = performance.now();
    const ease = (k) => (k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2);
    const step = (now) => {
      const k = Math.min(1, (now - t0) / ms);
      const kb = Math.min(1, (now - t0) / bms);
      const pos = {};
      for (const [id, [tx, ty]] of Object.entries(target)) {
        const [fx, fy] = from[id] || [tx, ty];
        const e = id === "ball" ? 1 - Math.pow(1 - kb, 3) : ease(k);   // ball: fast start, like a struck pass
        pos[id] = [fx + (tx - fx) * e, fy + (ty - fy) * e];
      }
      this.cur = pos;
      this._place(pos);
      if (k < 1) this.anim = requestAnimationFrame(step);
    };
    this.anim = requestAnimationFrame(step);
  }

  _trail(a, b) {
    if (!a || !b || Math.hypot(a[0] - b[0], a[1] - b[1]) < 1.5) return;
    const line = el("line", { x1: px(a[0]), y1: py(a[1]), x2: px(b[0]), y2: py(b[1]), stroke: "#fff",
      "stroke-width": 2, "stroke-dasharray": "6 5", opacity: 0.7, class: "pass-trail" });
    this.svg.insertBefore(line, this.layer);
    setTimeout(() => line.remove(), 1400);
  }

  _makeDraggable(g, id) {
    const toPitch = (evt) => {
      const pt = this.svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const p = pt.matrixTransform(this.svg.getScreenCTM().inverse());
      const x = Math.min(L - 0.5, Math.max(0.5, (p.x - PAD) / S));
      const y = Math.min(W - 0.5, Math.max(0.5, W - (p.y - PAD) / S));
      return [Math.round(x * 10) / 10, Math.round(y * 10) / 10];
    };
    g.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      g.setPointerCapture(e.pointerId);
      const move = (ev) => {
        const [x, y] = toPitch(ev);
        this.cur[id] = [x, y];
        this._place({ [id]: [x, y] });
        if (id === "ball") { this.state.ball = { x, y }; }
        else for (const p of [...this.state.us, ...this.state.them]) if (p.id === id) { p.x = x; p.y = y; }
      };
      const up = () => {
        g.removeEventListener("pointermove", move);
        g.removeEventListener("pointerup", up);
        if (this.onChange) this.onChange(this.state);
      };
      g.addEventListener("pointermove", move);
      g.addEventListener("pointerup", up);
    });
  }
}
