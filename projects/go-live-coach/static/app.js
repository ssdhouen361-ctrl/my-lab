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
    this.highlightArea = null; // デフォルトは全盤表示（固定の青枠を完全撤廃）
    this.voiceMode = "ptt"; // "ptt" (押してる間のみ) または "continuous" (常に集音)
    this.recognition = null;
    this.isRecording = false;

    this.init();
    this.initSpeechRecognition();
  }

  initSpeechRecognition() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("Web Speech API is not supported in this browser.");
      return;
    }
    this.recognition = new SpeechRecognition();
    this.recognition.lang = "ja-JP";
    this.recognition.continuous = true; // 途中で勝手に切れないよう常時ストリーム
    this.recognition.interimResults = true;
    this.silenceTimer = null;

    this.recognition.onstart = () => {
      this.isRecording = true;
      const btn = document.getElementById("mic-btn");
      if (btn) {
        btn.classList.add("recording");
        btn.innerText = "🛑 聴取中...";
      }
    };

    this.recognition.onresult = (event) => {
      let transcript = "";
      for (let i = 0; i < event.results.length; ++i) {
        transcript += event.results[i][0].transcript;
      }
      const input = document.getElementById("speech-input");
      if (input) input.value = transcript;

      // 無音タイマー（2秒間沈黙したら送信。早すぎる打ち切りを防止）
      if (this.silenceTimer) clearTimeout(this.silenceTimer);
      if (this.voiceMode === "continuous") {
        this.silenceTimer = setTimeout(() => {
          if (this.isRecording && transcript.trim()) {
            this.stopRecording();
            this.sendSpeech(transcript.trim());
          }
        }, 2200); // 2.2秒の余裕を持たせる
      }
    };

    this.recognition.onerror = (event) => {
      console.error("Speech recognition error", event.error);
      this.stopRecording();
    };

    this.recognition.onend = () => {
      if (this.silenceTimer) clearTimeout(this.silenceTimer);
      const isStillRecording = this.isRecording;
      this.stopRecording();
      const input = document.getElementById("speech-input");
      if (this.voiceMode === "ptt" && input && input.value.trim() && isStillRecording) {
        this.sendSpeech(input.value.trim());
      }
    };
  }

  toggleRecording() {
    if (!this.recognition) {
      alert("お使いのブラウザは音声認識に対応していません。ChromeまたはSafariの最新版をご利用ください。");
      return;
    }
    if (this.isRecording) {
      this.recognition.stop();
    } else {
      try {
        this.recognition.start();
      } catch (e) {
        console.error("Failed to start speech recognition", e);
      }
    }
  }

  stopRecording() {
    this.isRecording = false;
    const btn = document.getElementById("mic-btn");
    if (btn) {
      btn.classList.remove("recording");
      btn.innerText = "🎤 話す";
    }
  }

  async init() {
    this.resizeCanvas();
    window.addEventListener("resize", () => this.resizeCanvas());

    this.bindEvents();
    await this.fetchState();

    // Initial greeting
    this.appendAiMessage(
      "白12手目の検討局面です。右上の定石や全体の布石方針など、気になる部分があればいつでもお話しください。「右上のワカレはどう？」「ノビてたらどうだった？」など、自由に対話できます。"
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

    // Ghost stones with clear Black / White distinction and sequence numbers
    for (const v of this.ghostVariations) {
      const col = GTP_COLS.indexOf(v.coord[0]);
      const row = parseInt(v.coord.slice(1)) - 1;
      const { x, y } = this.coordToPx(col, row);
      const radius = this.cellSize * 0.44;

      ctx.save();
      ctx.beginPath();
      ctx.arc(x, y, radius, 0, Math.PI * 2);

      const isBlack = v.color === "B";
      if (isBlack) {
        // 黒の変化手（濃い半透明黒石 ＋ 青ネオン枠）
        ctx.fillStyle = "rgba(20, 25, 35, 0.82)";
        ctx.fill();
        ctx.strokeStyle = "#38bdf8"; // 明るいシアン青枠
        ctx.lineWidth = 2.5;
        ctx.stroke();
        ctx.fillStyle = "#ffffff"; // 白文字
      } else {
        // 白の変化手（明るい半透明白石 ＋ オレンジ枠）
        ctx.fillStyle = "rgba(250, 250, 250, 0.88)";
        ctx.fill();
        ctx.strokeStyle = "#f97316"; // 鮮やかなオレンジ枠
        ctx.lineWidth = 2.5;
        ctx.stroke();
        ctx.fillStyle = "#1e293b"; // 黒文字
      }

      // 手順番号（1, 2, 3...）
      ctx.font = `bold ${Math.round(this.cellSize * 0.45)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(v.step.toString(), x, y);

      // 上部に極小で「黒①」「白②」のラベル
      ctx.font = `bold ${Math.round(this.cellSize * 0.22)}px sans-serif`;
      ctx.fillStyle = isBlack ? "#38bdf8" : "#ea580c";
      ctx.fillText(isBlack ? "黒" : "白", x, y - radius * 0.58);

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
    const currentTurn = (this.gameState && this.gameState.turn) ? this.gameState.turn : "W";

    for (const act of actions) {
      if (act.action === "play_variation" && act.coords) {
        // 次の手番（白番の検討なら白から交互に着手）
        this.ghostVariations = act.coords.map((c, idx) => {
          let stoneColor;
          if (currentTurn === "W") {
            stoneColor = (idx % 2 === 0) ? "W" : "B";
          } else {
            stoneColor = (idx % 2 === 0) ? "B" : "W";
          }
          return {
            coord: c,
            step: idx + 1,
            color: stoneColor
          };
        });
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
    el.innerHTML = `<div class="card-title">あなた</div><div class="card-text">${this.escape(cleanSummary)}</div>`;
  }

  appendAiMessage(replyText, summaryTitle, actions) {
    const history = document.getElementById("chat-history");
    const div = document.createElement("div");
    div.className = "chat-card ai";
    let html = `<div class="card-title">AIコーチ (Gemini × KataGo)</div><div class="card-text">${this.escape(replyText)}</div>`;
    if (actions && actions.length > 0) {
      const coordsJson = JSON.stringify(actions[0].coords || []).replace(/"/g, '&quot;');
      html += `<div class="action-chip" onclick="app.reapplyVariation(${coordsJson})">▶ 変化手順を盤面に表示 (ゴースト石)</div>`;
    }
    div.innerHTML = html;
    history.appendChild(div);
    div.scrollIntoView({ behavior: "smooth" });
  }

  reapplyVariation(coords) {
    if (coords && coords.length > 0) {
      this.executeBoardActions([{ action: "play_variation", coords: coords }]);
    } else {
      this.renderGhost();
    }
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

    // Mic mode switch (PTT vs Continuous)
    const modeBtn = document.getElementById("mic-mode-btn");
    if (modeBtn) {
      modeBtn.addEventListener("click", () => {
        if (this.voiceMode === "ptt") {
          this.voiceMode = "continuous";
          modeBtn.innerText = "常時集音中";
          modeBtn.classList.add("active-vad");
        } else {
          this.voiceMode = "ptt";
          modeBtn.innerText = "押してる間のみ";
          modeBtn.classList.remove("active-vad");
        }
      });
    }

    const micBtn = document.getElementById("mic-btn");
    if (micBtn) {
      // Click for toggle, or hold for PTT
      micBtn.addEventListener("mousedown", () => {
        if (this.voiceMode === "ptt" && !this.isRecording) {
          this.toggleRecording();
        }
      });
      micBtn.addEventListener("mouseup", () => {
        if (this.voiceMode === "ptt" && this.isRecording) {
          this.toggleRecording();
        }
      });
      micBtn.addEventListener("touchstart", (e) => {
        e.preventDefault();
        if (this.voiceMode === "ptt" && !this.isRecording) {
          this.toggleRecording();
        }
      });
      micBtn.addEventListener("touchend", (e) => {
        e.preventDefault();
        if (this.voiceMode === "ptt" && this.isRecording) {
          this.toggleRecording();
        }
      });
      micBtn.addEventListener("click", () => {
        if (this.voiceMode === "continuous") {
          this.toggleRecording();
        }
      });
    }

    // Board Click-to-Play Event (盤面クリックで着手＆分岐作成)
    const handleBoardClick = async (e) => {
      e.preventDefault();
      const rect = this.ghostCanvas.getBoundingClientRect();
      const clientX = e.clientX ?? (e.touches && e.touches[0] ? e.touches[0].clientX : null);
      const clientY = e.clientY ?? (e.touches && e.touches[0] ? e.touches[0].clientY : null);
      if (clientX === null || clientY === null) return;

      const x = clientX - rect.left;
      const y = clientY - rect.top;

      // クリック位置から最も近い交点を高精度に算出
      const col = Math.round((x - this.gridPadding) / this.cellSize);
      const row = 18 - Math.round((y - this.gridPadding) / this.cellSize);

      console.log(`[BoardClick] raw: (${x.toFixed(1)}, ${y.toFixed(1)}), col: ${col}, row: ${row}`);

      if (col >= 0 && col < 19 && row >= 0 && row < 19) {
        const gtp = `${GTP_COLS[col]}${row + 1}`;
        console.log(`[BoardClick] Target GTP: ${gtp}`);
        try {
          const res = await fetch(`/api/v1/play?gtp=${gtp}`, { method: "POST" });
          if (res.ok) {
            this.gameState = await res.json();
            this.ghostVariations = []; // 確定着手したらゴーストを消去
            this.updateNavUI();
            this.renderBase();
            this.renderGhost();
          } else {
            const err = await res.json();
            console.warn("着手不可:", err.detail);
          }
        } catch (err) {
          console.error("着手通信エラー", err);
        }
      }
    };

    // 碁盤へのイベント登録（pointerdown, click, touchend を wrapper/canvas 両方に設定）
    this.ghostCanvas.addEventListener("pointerdown", handleBoardClick);
    this.ghostCanvas.addEventListener("click", handleBoardClick);
    this.ghostCanvas.addEventListener("touchend", handleBoardClick);
    const wrapper = document.getElementById("canvas-wrapper");
    if (wrapper) {
      wrapper.addEventListener("pointerdown", handleBoardClick);
      wrapper.addEventListener("click", handleBoardClick);
      wrapper.addEventListener("touchend", handleBoardClick);
    }

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
