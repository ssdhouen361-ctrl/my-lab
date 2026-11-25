/**
 * Go Live Coach Frontend Core
 * Dual-layer canvas rendering, S-Pen & touch handling, and smart dialogue UI
 */

const GTP_COLS = "ABCDEFGHJKLMNOPQRST";

class GoLiveCoachApp {
  constructor() {
    this.baseCanvas = document.getElementById("base-canvas");
    this.ghostCanvas = document.getElementById("ghost-canvas");
    this.baseCtx = this.baseCanvas.getContext("2d");
    this.ghostCtx = this.ghostCanvas.getContext("2d");

    this.gridPadding = 32;
    this.boardSize = 19;
    this.cellSize = 0;
    this.dpr = window.devicePixelRatio || 2;

    this.gameState = null;
    this.ghostVariations = []; // [{coord: "Q16", step: 1, color: "W"}]
    this.highlightArea = [12, 18, 12, 18]; // Default upper right 6x6

    this.init();
  }

  async init() {
    this.resizeCanvas();
    window.addEventListener("resize", () => this.resizeCanvas());

    this.bindEvents();
    await this.fetchState();

    // Initial greeting
    this.appendAiMessage(
      "白34手目の検討ですね。上辺の競り合いでハネ出すか、ノビて手堅く受けるかが焦点です。「ノビたらどうでしたか？」など、お気軽にお話しください。",
      "白34手目の検討について"
    );
  }

  resizeCanvas() {
    const wrapper = document.getElementById("canvas-wrapper");
    const rect = wrapper.getBoundingClientRect();
    const size = Math.floor(Math.min(rect.width, rect.height));

    this.baseCanvas.width = size * this.dpr;
    this.baseCanvas.height = size * this.dpr;
    this.ghostCanvas.width = size * this.dpr;
    this.ghostCanvas.height = size * this.dpr;

    this.baseCtx.scale(this.dpr, this.dpr);
    this.ghostCtx.scale(this.dpr, this.dpr);

    this.cssSize = size;
    this.cellSize = (size - this.gridPadding * 2) / (this.boardSize - 1);

    this.renderBase();
    this.renderGhost();
  }

  coordToPx(c, r) {
    const x = this.gridPadding + c * this.cellSize;
    const y = this.gridPadding + (18 - r) * this.cellSize;
    return { x, y };
  }

  renderBase() {
    const ctx = this.baseCtx;
    ctx.clearRect(0, 0, this.cssSize, this.cssSize);

    // Board wood
    ctx.fillStyle = "#e6be8a";
    ctx.fillRect(0, 0, this.cssSize, this.cssSize);

    // Grid lines
    ctx.strokeStyle = "#4a341b";
    ctx.lineWidth = 1.2;

    for (let i = 0; i < this.boardSize; i++) {
      // Verticals
      const x = Math.round(this.gridPadding + i * this.cellSize) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, this.gridPadding);
      ctx.lineTo(x, this.cssSize - this.gridPadding);
      ctx.stroke();

      // Horizontals
      const y = Math.round(this.gridPadding + i * this.cellSize) + 0.5;
      ctx.beginPath();
      ctx.moveTo(this.gridPadding, y);
      ctx.lineTo(this.cssSize - this.gridPadding, y);
      ctx.stroke();
    }

    // Star points
    const stars = [3, 9, 15];
    ctx.fillStyle = "#4a341b";
    for (const r of stars) {
      for (const c of stars) {
        const { x, y } = this.coordToPx(c, r);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Stones from game state
    if (!this.gameState || !this.gameState.stones) return;

    for (const [gtp, color] of Object.entries(this.gameState.stones)) {
      const col = GTP_COLS.indexOf(gtp[0]);
      const row = parseInt(gtp.slice(1)) - 1;
      const { x, y } = this.coordToPx(col, row);
      this.drawStone(ctx, x, y, color);
    }
  }

  drawStone(ctx, x, y, color) {
    const radius = this.cellSize * 0.46;
    ctx.save();
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);

    if (color === "B") {
      const grad = ctx.createRadialGradient(x - radius * 0.3, y - radius * 0.3, radius * 0.1, x, y, radius);
      grad.addColorStop(0, "#404040");
      grad.addColorStop(1, "#111111");
      ctx.fillStyle = grad;
      ctx.shadowColor = "rgba(0,0,0,0.4)";
      ctx.shadowBlur = 4;
      ctx.fill();
    } else {
      const grad = ctx.createRadialGradient(x - radius * 0.3, y - radius * 0.3, radius * 0.1, x, y, radius);
      grad.addColorStop(0, "#ffffff");
      grad.addColorStop(1, "#d1d5db");
      ctx.fillStyle = grad;
      ctx.shadowColor = "rgba(0,0,0,0.3)";
      ctx.shadowBlur = 4;
      ctx.fill();
      ctx.strokeStyle = "#9ca3af";
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();
  }

  renderGhost() {
    const ctx = this.ghostCtx;
    ctx.clearRect(0, 0, this.cssSize, this.cssSize);

    // Highlight area box
    if (this.highlightArea) {
      const [cMin, cMax, rMin, rMax] = this.highlightArea;
      const p1 = this.coordToPx(cMin, rMax);
      const p2 = this.coordToPx(cMax, rMin);
      const margin = this.cellSize * 0.55;

      ctx.strokeStyle = "rgba(59, 130, 246, 0.8)";
      ctx.lineWidth = 2.5;
      ctx.fillStyle = "rgba(59, 130, 246, 0.08)";
      ctx.beginPath();
      ctx.roundRect(p1.x - margin, p1.y - margin, (p2.x - p1.x) + margin * 2, (p2.y - p1.y) + margin * 2, 8);
      ctx.fill();
      ctx.stroke();
    }

    // Ghost stones with sequence numbers
    for (const v of this.ghostVariations) {
      const col = GTP_COLS.indexOf(v.coord[0]);
      const row = parseInt(v.coord.slice(1)) - 1;
      const { x, y } = this.coordToPx(col, row);
      const radius = this.cellSize * 0.44;

      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);
      ctx.fillStyle = v.color === "B" ? "rgba(30, 58, 138, 0.6)" : "rgba(191, 219, 254, 0.7)";
      ctx.fill();
      ctx.strokeStyle = "#3b82f6";
      ctx.lineWidth = 2;
      ctx.stroke();

      // Number
      ctx.fillStyle = "#ffffff";
      ctx.font = `bold ${Math.round(this.cellSize * 0.42)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(v.step.toString(), x, y);
      ctx.restore();
    }
  }

  async fetchState() {
    try {
      const res = await fetch("/api/v1/state");
      this.gameState = await res.json();
      this.updateNavUI();
      this.renderBase();
    } catch (e) {
      console.error("Failed to fetch game state", e);
    }
  }

  updateNavUI() {
    if (!this.gameState) return;
    document.getElementById("move-number-display").innerText = `${this.gameState.move_count}手目`;
    const turnStr = this.gameState.turn === "B" ? "黒番" : "白番";
    document.getElementById("move-turn-display").innerText = `（${turnStr} / 本譜）`;
  }

  async navigate(action) {
    try {
      const res = await fetch(`/api/v1/navigate?action=${action}`, { method: "POST" });
      this.gameState = await res.json();
      this.ghostVariations = []; // Clear ghost stones when moving on tree
      this.updateNavUI();
      this.renderBase();
      this.renderGhost();
    } catch (e) {
      console.error("Navigation error", e);
    }
  }

  async sendSpeech(text) {
    if (!text || !text.trim()) return;
    const input = document.getElementById("speech-input");
    input.value = "";

    // Show temporary balloon
    const tempId = this.appendUserBalloon(text);

    try {
      const res = await fetch("/api/v1/dialogue/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          user_speech_raw: text,
          current_node_id: this.gameState ? this.gameState.current_node_id : "root",
          move_count: this.gameState ? this.gameState.move_count : 12,
          selected_area: this.highlightArea
        })
      });
      const data = await res.json();

      // Replace user balloon with cleaned summary
      this.updateUserBalloon(tempId, data.user_intent_summary);
      this.appendAiMessage(data.coach_reply, null, data.board_actions);

      // Execute board actions
      this.executeBoardActions(data.board_actions);
    } catch (e) {
      console.error("Dialogue error", e);
    }
  }

  executeBoardActions(actions) {
    if (!actions) return;
    for (const act of actions) {
      if (act.action === "play_variation" && act.coords) {
        this.ghostVariations = act.coords.map((c, idx) => ({
          coord: c,
          step: idx + 1,
          color: idx % 2 === 0 ? "B" : "W"
        }));
        this.renderGhost();
      }
    }
  }

  appendUserBalloon(rawText) {
    const id = "msg-" + Date.now();
    const history = document.getElementById("chat-history");
    const div = document.createElement("div");
    div.id = id;
    div.className = "chat-card user";
    div.innerHTML = `<div class="card-title">あなた (要約中...)</div><div class="card-text">${this.escape(rawText)}</div>`;
    history.appendChild(div);
    div.scrollIntoView({ behavior: "smooth" });
    return id;
  }

  updateUserBalloon(id, cleanSummary) {
    const el = document.getElementById(id);
    if (!el) return;
    el.innerHTML = `<div class="card-title">あなた</div><div class="card-text">「${this.escape(cleanSummary)}」</div>`;
  }

  appendAiMessage(replyText, summaryTitle, actions) {
    const history = document.getElementById("chat-history");
    const div = document.createElement("div");
    div.className = "chat-card ai";
    let html = `<div class="card-title">AIコーチ (Gemini × KataGo)</div><div class="card-text">${this.escape(replyText)}</div>`;
    if (actions && actions.length > 0) {
      html += `<div class="action-chip" onclick="app.reapplyVariation()">▶ 変化図を盤面に表示 (ゴースト石)</div>`;
    }
    div.innerHTML = html;
    history.appendChild(div);
    div.scrollIntoView({ behavior: "smooth" });
  }

  reapplyVariation() {
    this.renderGhost();
  }

  escape(str) {
    return (str || "").replace(/[&<>"']/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m]));
  }

  bindEvents() {
    document.getElementById("nav-first").addEventListener("click", () => this.navigate("first"));
    document.getElementById("nav-prev10").addEventListener("click", () => this.navigate("prev10"));
    document.getElementById("nav-prev1").addEventListener("click", () => this.navigate("prev1"));
    document.getElementById("nav-next1").addEventListener("click", () => this.navigate("next1"));
    document.getElementById("nav-next10").addEventListener("click", () => this.navigate("next10"));
    document.getElementById("nav-last").addEventListener("click", () => this.navigate("last"));

    document.getElementById("send-speech-btn").addEventListener("click", () => {
      const val = document.getElementById("speech-input").value;
      this.sendSpeech(val);
    });

    document.getElementById("speech-input").addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        this.sendSpeech(e.target.value);
      }
    });

    // Settings drawer
    const drawer = document.getElementById("settings-drawer");
    document.getElementById("settings-btn").addEventListener("click", () => drawer.classList.remove("hidden"));
    document.getElementById("close-settings-btn").addEventListener("click", () => drawer.classList.add("hidden"));
  }
}

const app = new GoLiveCoachApp();
