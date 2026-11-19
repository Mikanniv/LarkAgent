// Route 1 Realtime Voice Call: Client Adaptive VAD + Single-Turn SSE (ASR -> Stream LLM -> Stream TTS) + Instant Barge-in

const toggleBtn = document.getElementById("voiceCallToggle");
const callBar = document.getElementById("voiceCallBar");
const statusTextEl = document.getElementById("voiceCallStatusText");
const hintEl = document.getElementById("voiceCallHint");
const meterFillEl = document.getElementById("voiceCallMeterFill");
const interruptBtn = document.getElementById("voiceCallInterruptBtn");
const hangupBtn = document.getElementById("voiceCallHangupBtn");
const voiceChoiceGroup = document.getElementById("voiceChoiceGroup");
const VOICE_STORAGE_KEY = "lark.voice.tts_voice.v1";

if (toggleBtn && callBar) {
  let active = false;
  let selectedVoice = localStorage.getItem(VOICE_STORAGE_KEY) || "zh-CN-XiaoyiNeural";
  if (!["zh-CN-XiaoyiNeural", "zh-CN-XiaoxiaoNeural"].includes(selectedVoice)) {
    selectedVoice = "zh-CN-XiaoyiNeural";
  }

  function syncVoiceChoiceUi() {
    if (!voiceChoiceGroup) return;
    voiceChoiceGroup.querySelectorAll(".voice-choice-btn").forEach((btn) => {
      const isMatch = btn.dataset.voice === selectedVoice;
      btn.classList.toggle("is-active", isMatch);
      btn.setAttribute("aria-pressed", String(isMatch));
    });
  }
  syncVoiceChoiceUi();
  voiceChoiceGroup?.addEventListener("click", (ev) => {
    const btn = ev.target.closest(".voice-choice-btn");
    if (!btn || !btn.dataset.voice) return;
    selectedVoice = btn.dataset.voice;
    try {
      localStorage.setItem(VOICE_STORAGE_KEY, selectedVoice);
    } catch {}
    syncVoiceChoiceUi();
  });
  let mediaStream = null;
  let audioCtx = null;
  let analyser = null;
  let vadTimer = null;

  let recorder = null;
  let recordedChunks = [];
  let isSpeaking = false;
  let speechStartAt = 0;
  let lastVoiceAt = 0;
  let noiseFloor = 0.012;
  let calibrationSamples = 0;

  let turnAbortCtrl = null;
  let assistantBusy = false;
  let audioQueue = [];
  let currentAudio = null;
  let playingAudio = false;
  let playbackEndedAt = 0;
  let loudStreak = 0;
  let ttsGen = 0;

  function resolveApiUrl(path) {
    if (window.yunqueDesktop?.apiBase) {
      return `${window.yunqueDesktop.apiBase.replace(/\/$/, "")}${path}`;
    }
    const loc = window.location;
    if (loc.hostname === "127.0.0.1" || loc.hostname === "localhost") {
      return path;
    }
    const meta = document.querySelector('meta[name="app-api-base"]')?.content?.trim();
    if (meta && loc.origin !== meta) return `${meta.replace(/\/$/, "")}${path}`;
    return path;
  }

  function setStatus(label, mode = "listening") {
    if (statusTextEl) statusTextEl.textContent = label;
    callBar.dataset.state = mode;
    if (interruptBtn) interruptBtn.hidden = !(mode === "speaking" || mode === "thinking");
  }

  function setHint(text) {
    if (hintEl) hintEl.textContent = text || "";
  }

  function getVoiceCallGreeting() {
    const h = new Date().getHours();
    if (h >= 5 && h < 11) return "早上好呀，我在这儿呢，准备开始今天的学习或者聊聊天吗？";
    if (h >= 11 && h < 14) return "中午好呀，我接通啦，今天上午过得怎么样？";
    if (h >= 14 && h < 18) return "下午好呀，我在听呢，随时跟我说吧。";
    if (h >= 18 && h < 22) return "晚上好呀，今天辛苦啦，想和我聊聊什么？";
    return "这么晚还没睡呀，我陪你聊一会儿，说完早点休息哦。";
  }

  function playHangupTone(existingCtx = null) {
    try {
      const Ctor = window.AudioContext || window.webkitAudioContext;
      if (!Ctor && !existingCtx) return;
      const ctx = existingCtx || new Ctor();
      const ownsCtx = !existingCtx;
      const fire = () => {
        const now = ctx.currentTime + 0.01;
        const playBeep = (freq, startOffset, duration) => {
          const osc = ctx.createOscillator();
          const gain = ctx.createGain();
          osc.type = "sine";
          osc.frequency.setValueAtTime(freq, now + startOffset);
          gain.gain.setValueAtTime(0.0001, now + startOffset);
          gain.gain.exponentialRampToValueAtTime(0.28, now + startOffset + 0.015);
          gain.gain.exponentialRampToValueAtTime(0.0001, now + startOffset + duration);
          osc.connect(gain);
          gain.connect(ctx.destination);
          osc.start(now + startOffset);
          osc.stop(now + startOffset + duration + 0.02);
        };
        // 经典双音下行挂断音效
        playBeep(520, 0.0, 0.12);
        playBeep(360, 0.13, 0.18);
        setTimeout(() => {
          try {
            ctx.close();
          } catch {}
        }, ownsCtx ? 500 : 450);
      };
      if (ctx.state === "suspended") {
        ctx.resume().then(fire).catch(() => {});
      } else {
        fire();
      }
    } catch {}
  }

  async function speakOpeningGreeting() {
    const text = getVoiceCallGreeting();
    window.dispatchEvent(new CustomEvent("lark:voice-greeting", { detail: { text } }));
    const myGen = ttsGen;
    assistantBusy = true;
    setStatus("云雀正在向你打招呼…", "thinking");
    try {
      const resp = await fetch(resolveApiUrl("/api/voice/tts"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, voice: selectedVoice }),
      });
      if (!active || myGen !== ttsGen) return;
      if (resp.ok) {
        const data = await resp.json();
        if (data?.audio_b64) {
          const voiceLabel = selectedVoice === "zh-CN-XiaoxiaoNeural" ? "晓晓" : "晓伊";
          setHint(`语音播报：${data.tts_provider === "edge_tts" ? `Edge ${voiceLabel}` : "云端语音"}`);
          assistantBusy = false;
          enqueueAudioItem({
            kind: "audio",
            audio_b64: data.audio_b64,
            mime: data.mime || "audio/mpeg",
            text,
          });
          return;
        }
      }
    } catch {}
    if (!active || myGen !== ttsGen) {
      assistantBusy = false;
      return;
    }
    assistantBusy = false;
    setHint("语音播报：浏览器朗读（后端未装 edge-tts 或网络波动）");
    enqueueAudioItem({ kind: "browser", text });
  }

  function pickChineseVoice() {
    try {
      const voices = window.speechSynthesis?.getVoices?.() || [];
      return (
        voices.find((v) => /zh[-_]?CN/i.test(v.lang) && /Tingting|Xiaoxiao|Google|Meijia|Sinji/i.test(v.name)) ||
        voices.find((v) => /zh[-_]?CN/i.test(v.lang)) ||
        voices.find((v) => /^zh/i.test(v.lang)) ||
        null
      );
    } catch {
      return null;
    }
  }

  function pickRecorderMime() {
    const candidates = [
      "audio/webm;codecs=opus",
      "audio/webm",
      "audio/mp4",
      "audio/ogg;codecs=opus",
    ];
    for (const mime of candidates) {
      if (window.MediaRecorder && MediaRecorder.isTypeSupported(mime)) return mime;
    }
    return "";
  }

  function stopPlaybackAndAbort() {
    ttsGen += 1;
    audioQueue = [];
    playingAudio = false;
    if (currentAudio) {
      try {
        currentAudio.pause();
        currentAudio.src = "";
      } catch {}
      currentAudio = null;
    }
    try {
      window.speechSynthesis?.cancel();
    } catch {}
    if (turnAbortCtrl) {
      try {
        turnAbortCtrl.abort();
      } catch {}
      turnAbortCtrl = null;
    }
    assistantBusy = false;
  }

  function enqueueAudioItem(item) {
    audioQueue.push({ ...item, gen: ttsGen });
    if (!playingAudio) drainAudioQueue();
  }

  function drainAudioQueue() {
    if (playingAudio) return;
    const next = audioQueue.shift();
    if (!next) {
      playbackEndedAt = Date.now();
      if (active && !assistantBusy) setStatus("聆听中… 直接开口说话即可", "listening");
      return;
    }
    if (next.gen !== ttsGen) {
      drainAudioQueue();
      return;
    }

    playingAudio = true;
    setStatus("云雀说话中…", "speaking");

    if (next.kind === "audio" && next.audio_b64) {
      const done = () => {
        if (currentAudio) {
          try {
            currentAudio.onended = null;
            currentAudio.onerror = null;
          } catch {}
          currentAudio = null;
        }
        playingAudio = false;
        drainAudioQueue();
      };
      const playViaWebAudio = async () => {
        try {
          const raw = atob(next.audio_b64);
          const bytes = new Uint8Array(raw.length);
          for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
          const Ctor = window.AudioContext || window.webkitAudioContext;
          const ctx = audioCtx || new Ctor();
          if (ctx.state === "suspended") await ctx.resume();
          const decoded = await ctx.decodeAudioData(bytes.buffer.slice(0));
          if (next.gen !== ttsGen) {
            done();
            return;
          }
          const src = ctx.createBufferSource();
          src.buffer = decoded;
          src.connect(ctx.destination);
          currentAudio = { pause: () => { try { src.stop(); } catch {} } };
          src.onended = done;
          src.start(0);
        } catch {
          done();
        }
      };
      const url = `data:${next.mime || "audio/mpeg"};base64,${next.audio_b64}`;
      const audio = new Audio(url);
      currentAudio = audio;
      audio.onended = done;
      audio.onerror = () => playViaWebAudio();
      audio.play().catch(() => playViaWebAudio());
      return;
    }

    if (next.kind === "browser" && next.text && "speechSynthesis" in window) {
      const utter = new SpeechSynthesisUtterance(next.text);
      utter.lang = "zh-CN";
      const zhVoice = pickChineseVoice();
      if (zhVoice) utter.voice = zhVoice;
      utter.rate = 1.04;
      const done = () => {
        playingAudio = false;
        drainAudioQueue();
      };
      utter.onend = done;
      utter.onerror = done;
      window.speechSynthesis.speak(utter);
      return;
    }

    playingAudio = false;
    drainAudioQueue();
  }

  function blobToBase64(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const res = String(reader.result || "");
        resolve(res.includes(",") ? res.split(",", 2)[1] : res);
      };
      reader.onerror = reject;
      reader.readAsDataURL(blob);
    });
  }

  async function sendVoiceUtterance(blob, mimeType) {
    if (!active || !blob || blob.size < 1200) {
      if (active) setStatus("聆听中… 直接开口说话即可", "listening");
      return;
    }

    stopPlaybackAndAbort();
    const myGen = ttsGen;
    assistantBusy = true;
    setStatus("正在识别你的语音…", "thinking");

    const ctrl = new AbortController();
    turnAbortCtrl = ctrl;

    try {
      const b64 = await blobToBase64(blob);
      const ext = (mimeType || "").includes("mp4")
        ? "m4a"
        : (mimeType || "").includes("ogg")
          ? "ogg"
          : "webm";

      const resp = await fetch(resolveApiUrl("/api/voice/turn/stream"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          audio_b64: b64,
          mime_type: mimeType || "audio/webm",
          filename: `voice.${ext}`,
          voice: selectedVoice,
        }),
        signal: ctrl.signal,
      });

      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      let replyText = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        if (myGen !== ttsGen) break;
        buf += decoder.decode(value, { stream: true });
        const parts = buf.split("\n\n");
        buf = parts.pop() || "";

        for (const rawEvent of parts) {
          const line = rawEvent
            .split("\n")
            .find((ln) => ln.startsWith("data:"));
          if (!line) continue;
          let ev;
          try {
            ev = JSON.parse(line.slice(5).trim());
          } catch {
            continue;
          }
          if (ev.type === "empty") {
            setStatus(ev.error || "没听清，请再说一次", "listening");
          } else if (ev.type === "transcript") {
            setStatus("云雀思考中…", "thinking");
            window.dispatchEvent(
              new CustomEvent("lark:voice-user-transcript", { detail: { text: ev.text || "" } }),
            );
          } else if (ev.type === "delta") {
            replyText += ev.delta || "";
            window.dispatchEvent(
              new CustomEvent("lark:voice-assistant-delta", { detail: { text: replyText } }),
            );
          } else if (ev.type === "audio") {
            const voiceLabel = selectedVoice === "zh-CN-XiaoxiaoNeural" ? "晓晓" : "晓伊";
            setHint(`语音播报：${ev.tts_provider === "edge_tts" ? `Edge ${voiceLabel}` : "云端语音"}`);
            enqueueAudioItem({
              kind: "audio",
              audio_b64: ev.audio_b64,
              mime: ev.mime,
              text: ev.text,
            });
          } else if (ev.type === "tts_sentence") {
            setHint("语音播报：浏览器朗读");
            enqueueAudioItem({ kind: "browser", text: ev.text });
          } else if (ev.type === "done") {
            window.dispatchEvent(
              new CustomEvent("lark:voice-turn-done", { detail: ev }),
            );
          } else if (ev.type === "error") {
            setStatus(`通话波动：${ev.error || "未知错误"}`, "listening");
            window.dispatchEvent(
              new CustomEvent("lark:voice-turn-error", { detail: { error: ev.error || "未知错误" } }),
            );
          }
        }
      }
    } catch (err) {
      if (err?.name !== "AbortError") {
        setStatus(`语音连接失败：${err.message || err}`, "listening");
      }
    } finally {
      if (turnAbortCtrl === ctrl) turnAbortCtrl = null;
      assistantBusy = false;
      if (active && !playingAudio && audioQueue.length === 0) {
        setStatus("聆听中… 直接开口说话即可", "listening");
      }
    }
  }

  function startUtteranceRecording() {
    if (!mediaStream || isSpeaking) return;
    const mime = pickRecorderMime();
    recordedChunks = [];
    try {
      recorder = mime
        ? new MediaRecorder(mediaStream, { mimeType: mime })
        : new MediaRecorder(mediaStream);
    } catch {
      recorder = new MediaRecorder(mediaStream);
    }
    const chosenMime = recorder.mimeType || mime || "audio/webm";
    recorder.ondataavailable = (ev) => {
      if (ev.data && ev.data.size > 0) recordedChunks.push(ev.data);
    };
    recorder.onstop = () => {
      const duration = Date.now() - speechStartAt;
      const chunks = recordedChunks;
      recordedChunks = [];
      if (active && duration >= 320 && chunks.length > 0) {
        const blob = new Blob(chunks, { type: chosenMime });
        sendVoiceUtterance(blob, chosenMime);
      }
    };
    isSpeaking = true;
    speechStartAt = Date.now();
    lastVoiceAt = speechStartAt;
    recorder.start(120);
    setStatus("正在听你说话…", "recording");
  }

  function stopUtteranceRecording() {
    if (!isSpeaking) return;
    isSpeaking = false;
    if (recorder && recorder.state !== "inactive") {
      try {
        recorder.stop();
      } catch {}
    }
  }

  function startVadLoop() {
    const samples = new Float32Array(analyser.fftSize);
    vadTimer = setInterval(() => {
      if (!active || !analyser) return;
      analyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i++) sum += samples[i] * samples[i];
      const rms = Math.sqrt(sum / samples.length);

      if (meterFillEl) {
        const pct = Math.min(100, Math.round(rms * 550));
        meterFillEl.style.width = `${pct}%`;
      }

      // 前 400ms 自适应环境底噪
      if (calibrationSamples < 8 && !playingAudio && !assistantBusy) {
        noiseFloor = noiseFloor * 0.7 + rms * 0.3;
        calibrationSamples += 1;
        return;
      }

      const startThreshold = Math.max(0.025, noiseFloor * 2.8);
      const now = Date.now();

      // 云雀说话或思考期间暂停自动收音，避免扬声器回声误打断（需要打断时点击「打断」按钮）
      if (playingAudio || assistantBusy) {
        loudStreak = 0;
        return;
      }

      // 刚播报结束留 500ms 尾音冷却，避免把云雀尾音当成用户说话
      if (now - playbackEndedAt < 500) {
        loudStreak = 0;
        return;
      }

      if (rms > startThreshold) {
        loudStreak += 1;
        if (!isSpeaking && loudStreak >= 2) {
          startUtteranceRecording();
        }
        if (isSpeaking) lastVoiceAt = now;
      } else {
        loudStreak = 0;
        if (isSpeaking) {
          // 静音超过 800ms 或单句超过 20s，自动截断发送
          if (now - lastVoiceAt >= 800 || now - speechStartAt >= 20000) {
            stopUtteranceRecording();
          }
        } else {
          // 缓慢跟踪环境底噪
          noiseFloor = noiseFloor * 0.96 + rms * 0.04;
        }
      }
    }, 50);
  }

  async function startVoiceCall() {
    if (active) return;
    if (!navigator.mediaDevices?.getUserMedia) {
      window.alert("当前浏览器不支持麦克风实时通话。");
      return;
    }
    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      audioCtx = new AudioContextCtor();
      if (audioCtx.state === "suspended") {
        await audioCtx.resume().catch(() => {});
      }
      const source = audioCtx.createMediaStreamSource(mediaStream);
      analyser = audioCtx.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);

      active = true;
      calibrationSamples = 0;
      noiseFloor = 0.012;
      try {
        // 在用户点击手势内预热浏览器语音合成，避免异步播报被拦截
        window.speechSynthesis?.getVoices?.();
        window.speechSynthesis?.cancel?.();
      } catch {}
      callBar.hidden = false;
      toggleBtn.classList.add("is-active");
      toggleBtn.setAttribute("aria-pressed", "true");
      setStatus("聆听中… 直接开口说话即可", "listening");
      setHint("说完停顿自动发送 · 开口即可打断");
      startVadLoop();
      speakOpeningGreeting();
    } catch (err) {
      window.alert(`无法开启麦克风：${err.message || err}`);
      stopVoiceCall(false);
    }
  }

  function stopVoiceCall(withTone = true) {
    const wasActive = active;
    active = false;
    stopPlaybackAndAbort();
    stopUtteranceRecording();
    if (vadTimer) {
      clearInterval(vadTimer);
      vadTimer = null;
    }
    const ctxToClose = audioCtx;
    audioCtx = null;
    analyser = null;
    if (mediaStream) {
      mediaStream.getTracks().forEach((t) => t.stop());
      mediaStream = null;
    }
    callBar.hidden = true;
    toggleBtn.classList.remove("is-active");
    toggleBtn.setAttribute("aria-pressed", "false");
    if (meterFillEl) meterFillEl.style.width = "0%";
    if (withTone && wasActive) {
      playHangupTone(ctxToClose);
    } else if (ctxToClose) {
      try {
        ctxToClose.close();
      } catch {}
    }
  }

  toggleBtn.addEventListener("click", () => {
    if (active) stopVoiceCall(true);
    else startVoiceCall();
  });
  interruptBtn?.addEventListener("click", () => {
    stopPlaybackAndAbort();
    if (active) setStatus("已打断，请继续说…", "listening");
  });
  hangupBtn?.addEventListener("click", () => stopVoiceCall(true));
  window.addEventListener("yunque:view", (ev) => {
    if (active && ev?.detail?.view !== "chat") stopVoiceCall(true);
  });
}
