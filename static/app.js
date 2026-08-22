const state = {
  authUser: null,
  activeView: "chat",
  history: [],
  memories: { layers: { observation: [], reflection: [], strategy: [] }, unread: { total: 0 } },
  selectedLayer: "observation",
  selectedMemoryId: "",
  aiDiaryBatches: [],
  revisionTarget: null,
  sidebarCollapsed: false,
  lastInteractionAt: Date.now(),
  proactiveEnabled: true,
  chatPending: false,
  chatAbortController: null,
  recording: false,
  mediaRecorder: null,
  mediaStream: null,
  audioChunks: [],
  pendingFiles: [], sentMedia: [], pendingVoiceAudio: "",
  emotionPinned: true, emotionPosition: null,
  trajectory: { range: "one_day", anchor: "", records: [], memories: [], strategies: [], summary: {} },
  trajectoryTopic: "all",
};

const els = Object.fromEntries(
  [
    "introScreen", "enterAppButton", "authToggleButton", "authForm", "authUsername",
    "authPassword", "authLoginButton", "authRegisterButton", "authStatus", "appShell",
    "appSidebar", "sidebarToggle", "mobileSidebarToggle", "sidebarScrim", "activeViewTitle",
    "backendStatus", "agentStatus", "sidebarChatTab", "sidebarDiaryTab", "sidebarMemoryTab", "sidebarTrajectoryTab",
    "sidebarSettingsTab", "diaryNewBadge", "memoryNewBadge", "chatView", "diaryView", "trajectoryView",
    "memoryView", "settingsView", "emotionWidget", "emotionToggle", "emotionPin", "emotionDragHandle", "textScore",
    "fusionScore", "audioScore", "chatList", "chatForm", "messageInput", "voiceButton", "sendButton", "diaryUserModeTab",
    "diaryAiModeTab", "userDiaryPane", "aiDiaryPane", "userDiaryDate", "userDiary",
    "userDiaryStatus", "diaryDeleteButton", "diarySaveButton", "aiDiaryList",
    "memoryLayers", "memoryItems", "memoryDetail", "proactiveReplyToggle", "clearDataButton",
    "revisionModal", "revisionInput", "revisionCancel", "revisionSubmit",
    "attachmentInput", "attachmentButton", "pendingAttachments", "sentMediaToggle", "sentMediaPanel", "sentMediaList", "sentMediaCount", "sentMediaClose", "dropOverlay",
    "trajectoryAnchor", "trajectoryAverage", "trajectoryChange", "trajectoryRecordCount", "trajectoryAudioCount", "trajectoryPeriodLabel", "trajectoryChart", "trajectoryChanges", "trajectoryStrategies", "trajectoryTopicFilters", "trajectoryMemoryList",
  ].map((id) => [id, document.getElementById(id)]),
);

const CHINA_TIME_ZONE = "Asia/Shanghai";
const API_BASE = resolveApiBase();
const VIEW_TITLES = { chat: "聊天", diary: "日记", memory: "长期记忆", trajectory: "情绪轨迹", settings: "设置" };
const LAYER_LABELS = { observation: "观察", reflection: "反思", strategy: "策略" };
const TOPIC_LABELS = { event: "事件", preference: "偏好", routine: "习惯", relationship: "关系" };
const REVIEW_LABELS = { pending: "待审查", confirmed: "已确认", revised: "已修改", deleted: "已删除" };
const USER_ICON = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="8" r="4"></circle>
    <path d="M4.5 21a7.5 7.5 0 0 1 15 0"></path>
  </svg>`;

function resolveApiBase() {
  const host = window.location.hostname;
  if (["127.0.0.1", "localhost", "0.0.0.0", "::1", ""].includes(host)) return "";
  return document.querySelector('meta[name="app-api-base"]')?.content?.trim().replace(/\/$/, "") || "";
}

function apiUrl(path) {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalized}`;
}

function authRequired() {
  return Boolean(API_BASE);
}

async function requestJson(path, options = {}) {
  const { timeoutMs = 30000, signal: externalSignal, ...fetchOptions } = options;
  const controller = new AbortController();
  const relayAbort = () => controller.abort(externalSignal?.reason);
  if (externalSignal?.aborted) relayAbort(); else externalSignal?.addEventListener("abort", relayAbort, { once: true });
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch(apiUrl(path), {
      credentials: "include",
      headers: { "Content-Type": "application/json", ...(fetchOptions.headers || {}) },
      ...fetchOptions,
      signal: controller.signal,
    });
  } finally {
    window.clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", relayAbort);
  }
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) { const error = new Error(payload.error || `请求失败（${response.status}）`); error.status = response.status; throw error; }
  return payload;
}

function chinaDateKey(date = new Date()) {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: CHINA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const values = Object.fromEntries(parts.map((item) => [item.type, item.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function chinaTimestamp() {
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: CHINA_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).formatToParts(new Date());
  const values = Object.fromEntries(parts.map((item) => [item.type, item.value]));
  return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}:${values.second}+08:00`;
}

function setBackendOnline(online) {
  els.backendStatus.classList.toggle("is-online", online);
  els.backendStatus.lastChild.textContent = online ? "在线" : "离线";
}

function setView(view) {
  state.activeView = view;
  const map = {
    chat: [els.sidebarChatTab, els.chatView],
    diary: [els.sidebarDiaryTab, els.diaryView],
    memory: [els.sidebarMemoryTab, els.memoryView],
    trajectory: [els.sidebarTrajectoryTab, els.trajectoryView],
    settings: [els.sidebarSettingsTab, els.settingsView],
  };
  Object.entries(map).forEach(([key, [tab, panel]]) => {
    tab.classList.toggle("is-active", key === view);
    panel.classList.toggle("is-active", key === view);
  });
  els.activeViewTitle.textContent = VIEW_TITLES[view];
  els.appShell.classList.remove("is-mobile-menu-open");
  if (view === "memory") fetchMemories();
  if (view === "diary") fetchAiDiary();
  if (view === "trajectory") fetchTrajectory();
}

function setChatPending(pending, activity = "生成") {
  state.chatPending = pending;
  els.sendButton.classList.toggle("is-stop", pending);
  els.sendButton.setAttribute("aria-label", pending ? `停止${activity}` : "发送");
  els.sendButton.title = pending ? `停止${activity}` : "发送";
  els.sendButton.innerHTML = pending ? '<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1.5"></rect></svg>' : '<svg viewBox="0 0 24 24"><path d="m4 4 17 8-17 8 3-8-3-8zM7 12h14"></path></svg>';
}

function setSidebarCollapsed(value) {
  state.sidebarCollapsed = Boolean(value);
  els.appShell.classList.toggle("is-sidebar-collapsed", state.sidebarCollapsed);
  try {
    localStorage.setItem("yunque.web.sidebar.collapsed.v2", state.sidebarCollapsed ? "1" : "0");
  } catch {
    // Layout remains functional without storage.
  }
}

function showApp() {
  els.introScreen.classList.add("is-hidden");
  els.appShell.classList.remove("is-hidden");
  Promise.allSettled([loadChatHistory(), fetchMemories(), fetchAiDiary(), loadUserDiary()]);
}

async function checkAuth() {
  if (!authRequired()) {
    state.authUser = { id: "local_user", username: "本地用户" };
    els.authToggleButton.textContent = "本地开发模式";
    els.enterAppButton.disabled = false;
    return;
  }
  try {
    const payload = await requestJson("/api/auth/me");
    state.authUser = payload.user || null;
  } catch {
    state.authUser = null;
  }
  els.authToggleButton.textContent = state.authUser ? `已登录：${state.authUser.username}` : "登录 / 注册";
  els.enterAppButton.disabled = !state.authUser;
  els.authStatus.textContent = state.authUser ? "登录成功。" : "请先登录或注册。";
}

async function submitAuth(mode) {
  const username = els.authUsername.value.trim();
  const password = els.authPassword.value;
  if (!username || password.length < 8) {
    els.authStatus.textContent = "请输入用户名和至少 8 位密码。";
    return;
  }
  try {
    const payload = await requestJson(`/api/auth/${mode}`, {
      method: "POST",
      body: JSON.stringify({ username, password }),
    });
    state.authUser = payload.user || null;
    els.authForm.hidden = true;
    await checkAuth();
  } catch (error) {
    els.authStatus.textContent = error.message;
  }
}

function createAvatar(role) {
  const avatar = document.createElement("span");
  avatar.className = "avatar";
  if (role === "assistant") {
    const image = document.createElement("img");
    image.src = "branding/lark-icon.png";
    image.alt = "";
    avatar.append(image);
  } else {
    avatar.innerHTML = USER_ICON;
  }
  return avatar;
}

function appendMessage(role, content, { typing = false } = {}) {
  const message = document.createElement("article");
  message.className = `message ${role === "user" ? "is-user" : "is-agent"}${typing ? " typing" : ""}`;
  message.append(createAvatar(role));
  const wrap = document.createElement("div");
  wrap.className = "message-content";
  const label = document.createElement("span");
  label.className = "message-role";
  label.textContent = role === "user" ? "你" : "云雀";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = content;
  wrap.append(label, bubble);
  message.append(wrap);
  els.chatList.append(message);
  els.chatList.scrollTop = els.chatList.scrollHeight;
  return message;
}

function renderChatHistory() {
  els.chatList.textContent = "";
  if (!state.history.length) {
    appendMessage("assistant", "你好，我是云雀。今天有什么想和我聊聊的吗？");
    return;
  }
  state.history.forEach((item) => appendMessage(item.role, item.content));
}

async function loadChatHistory() {
  try {
    const payload = await requestJson("/api/chat/history?limit=20");
    state.history = payload.items || [];
    renderChatHistory();
    rebuildSentMedia();
    setBackendOnline(true);
  } catch {
    setBackendOnline(false);
    renderChatHistory();
  }
}

function updateScores(scores = {}) {
  els.textScore.textContent = Number(scores.text || 0).toFixed(3);
  els.fusionScore.textContent = Number(scores.fusion || 0).toFixed(3);
  els.audioScore.textContent = Number.isFinite(Number(scores.audio))
    ? Number(scores.audio).toFixed(3)
    : "--";
}

async function sendChat(message, { proactive = false } = {}) {
  if (state.chatPending) return;
  const abortController = new AbortController(); state.chatAbortController = abortController; setChatPending(true);
  let typing = null;
  if (!proactive && message) {
    appendMessage("user", message);
  }
  typing = appendMessage("assistant", "···", { typing: true });
  els.agentStatus.textContent = "云雀正在思考";
  try {
    const attachments = proactive ? [] : [...state.pendingFiles];
    const voiceAudio = proactive ? "" : state.pendingVoiceAudio;
    const payload = await requestJson("/api/chat", {
      method: "POST",
      timeoutMs: voiceAudio ? 120000 : 30000, signal: abortController.signal,
      body: JSON.stringify({
        message: proactive ? "" : message,
        proactive,
        proactive_reason: proactive ? "用户一段时间没有继续输入" : "",
        audio_data: voiceAudio, attachments,
        timestamp: chinaTimestamp(),
      }),
    });
    typing.remove();
    updateScores(payload.scores);
    const reply = payload.agent?.reply;
    if (!reply) throw new Error("模型没有返回回复内容");
    appendMessage("assistant", reply);
    state.history = payload.chat_history || state.history;
    state.pendingFiles = []; state.pendingVoiceAudio = ""; renderPendingFiles(); rebuildSentMedia();
    els.agentStatus.textContent = payload.modal_inputs?.audio_available ? "文本与音频陪伴模式" : "文本陪伴模式";
    setBackendOnline(true);
    state.lastInteractionAt = Date.now();
    await Promise.allSettled([fetchMemories(), fetchAiDiary()]);
  } catch (error) {
    typing?.remove();
    if (abortController.signal.aborted) { els.agentStatus.textContent = "已停止生成"; return; }
    window.alert(error.message); els.agentStatus.textContent = Number(error.status || 0) >= 500 ? "模型调用失败" : "连接失败";
    setBackendOnline(Number(error.status || 0) >= 500);
  } finally {
    if (state.chatAbortController === abortController) state.chatAbortController = null; setChatPending(false);
  }
}

function renderPendingFiles() {
  els.pendingAttachments.textContent = "";
  els.pendingAttachments.hidden = !state.pendingFiles.length && !state.pendingVoiceAudio;
  const entries = state.pendingVoiceAudio ? [{ name: "录音已暂存 · 发送时分析情绪", voice: true }, ...state.pendingFiles] : state.pendingFiles;
  entries.forEach((item) => {
    const chip = document.createElement("span"); chip.className = "pending-file";
    const name = document.createElement("span"); name.textContent = item.name;
    const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "×";
    remove.onclick = () => { if (item.voice) state.pendingVoiceAudio = ""; else state.pendingFiles = state.pendingFiles.filter((entry) => entry !== item); renderPendingFiles(); };
    chip.append(name, remove); els.pendingAttachments.append(chip);
  });
}

async function addFiles(fileList) {
  const files = [...fileList].filter((file) => file.type.startsWith("image/") || file.type.startsWith("audio/"));
  const available = 9 - state.pendingFiles.length;
  if (files.length > available) window.alert("每次最多选择 9 个文件。");
  const additions = [];
  for (const file of files.slice(0, available)) {
    if (file.size > 10 * 1024 * 1024) { window.alert(`${file.name} 超过 10 MB`); continue; }
    additions.push({ name: file.name, type: file.type, size: file.size, data: await blobToDataUrl(file) });
  }
  state.pendingFiles.push(...additions); renderPendingFiles();
}

function rebuildSentMedia() {
  state.sentMedia = state.history.flatMap((item) => item.role === "user" ? (item.attachments || []) : []);
  els.sentMediaCount.textContent = String(state.sentMedia.length); els.sentMediaList.textContent = "";
  if (!state.sentMedia.length) { els.sentMediaList.innerHTML = '<span class="empty-note">还没有发送过媒体</span>'; return; }
  state.sentMedia.forEach((item) => { const node = document.createElement("article"); node.className = "sent-media-item"; node.textContent = `${item.name} · ${item.type} · ${Math.ceil(Number(item.size || 0) / 1024)} KB`; els.sentMediaList.append(node); });
}

async function analyzeVoiceInput(audioData) {
  if (state.chatPending) return;
  const controller = new AbortController(); state.chatAbortController = controller; setChatPending(true, "识别");
  els.agentStatus.textContent = "正在识别语音";
  try {
    const payload = await requestJson("/api/audio/input", { method: "POST", timeoutMs: 120000, signal: controller.signal, body: JSON.stringify({ audio_data: audioData, timestamp: chinaTimestamp() }) });
    const transcript = String(payload.transcript || "").trim(); if (!transcript) throw new Error("没有识别到语音文字");
    const existing = els.messageInput.value.trim(); els.messageInput.value = existing ? `${existing} ${transcript}` : transcript;
    state.pendingVoiceAudio = audioData; renderPendingFiles(); els.messageInput.focus(); els.agentStatus.textContent = "语音识别完成 · 录音等待发送"; setBackendOnline(true);
  } catch (error) { if (!controller.signal.aborted) window.alert(`语音识别失败：${error.message}`); }
  finally { if (state.chatAbortController === controller) state.chatAbortController = null; setChatPending(false); }
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("读取录音失败"));
    reader.readAsDataURL(blob);
  });
}

async function toggleVoiceRecording() {
  if (state.chatPending) return;
  if (state.recording) {
    state.mediaRecorder?.stop();
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
    window.alert("当前浏览器不支持录音，请使用最新版 Chrome、Edge 或 Safari。");
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const preferred = ["audio/webm;codecs=opus", "audio/mp4", "audio/webm"]
      .find((type) => MediaRecorder.isTypeSupported(type));
    const recorder = new MediaRecorder(stream, preferred ? { mimeType: preferred } : undefined);
    state.mediaStream = stream;
    state.mediaRecorder = recorder;
    state.audioChunks = [];
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size) state.audioChunks.push(event.data);
    });
    recorder.addEventListener("stop", async () => {
      const blob = new Blob(state.audioChunks, { type: recorder.mimeType || "audio/webm" });
      stream.getTracks().forEach((track) => track.stop());
      state.recording = false;
      state.mediaRecorder = null;
      state.mediaStream = null;
      els.voiceButton.classList.remove("is-recording");
      els.voiceButton.setAttribute("aria-label", "开始录音");
      els.agentStatus.textContent = "正在识别语音";
      try {
        await analyzeVoiceInput(await blobToDataUrl(blob));
      } catch (error) {
        window.alert(`录音发送失败：${error.message}`);
      }
    }, { once: true });
    recorder.start();
    state.recording = true;
    els.voiceButton.classList.add("is-recording");
    els.voiceButton.setAttribute("aria-label", "停止并识别录音");
    els.agentStatus.textContent = "正在录音，点击麦克风结束识别";
  } catch (error) {
    window.alert(`无法使用麦克风：${error.message}`);
  }
}

function layerIcon(layer) {
  const paths = {
    observation: '<circle cx="12" cy="12" r="8"></circle><path d="M8 12h8M12 8v8"></path>',
    reflection: '<path d="M9 18h6M10 22h4"></path><path d="M8.4 14.5A6 6 0 1 1 15.6 14.5c-1 .7-1.6 1.6-1.6 2.5h-4c0-.9-.6-1.8-1.6-2.5z"></path>',
    strategy: '<path d="M4 19h16M6 16l4-4 3 2 5-7"></path><circle cx="18" cy="7" r="2"></circle>',
  };
  return `<svg viewBox="0 0 24 24">${paths[layer]}</svg>`;
}

function updateEmotionPinState() {
  els.emotionWidget.classList.toggle("is-pinned", state.emotionPinned);
  els.emotionPin.classList.toggle("is-active", state.emotionPinned);
  els.emotionPin.setAttribute("aria-pressed", String(state.emotionPinned));
  const label = state.emotionPinned ? "取消固定，可拖动卡片" : "固定当前位置";
  els.emotionPin.setAttribute("aria-label", label);
  els.emotionPin.title = label;
}

function clampEmotionWidgetPosition(persist = false) {
  if (els.emotionWidget.hidden || !els.emotionWidget.style.left) return;
  const panel = els.emotionWidget.closest(".chat-panel");
  const maxLeft = Math.max(0, panel.clientWidth - els.emotionWidget.offsetWidth);
  const maxTop = Math.max(0, panel.clientHeight - els.emotionWidget.offsetHeight);
  const left = Math.max(0, Math.min(parseFloat(els.emotionWidget.style.left) || 0, maxLeft));
  const top = Math.max(0, Math.min(parseFloat(els.emotionWidget.style.top) || 0, maxTop));
  els.emotionWidget.style.left = `${left}px`;
  els.emotionWidget.style.top = `${top}px`;
  state.emotionPosition = { left, top };
  if (persist) localStorage.setItem("yunque.web.emotion.position.v1", JSON.stringify(state.emotionPosition));
}

function showEmotionWidget(visible) {
  els.emotionWidget.hidden = !visible;
  els.emotionToggle.setAttribute("aria-expanded", String(visible));
  if (visible) requestAnimationFrame(() => clampEmotionWidgetPosition(true));
}
function initializeEmotionDragging() {
  let drag = null;
  els.emotionDragHandle.addEventListener("pointerdown", (event) => { if (state.emotionPinned || event.target.closest("button")) return; const panel = els.emotionWidget.closest(".chat-panel").getBoundingClientRect(); const card = els.emotionWidget.getBoundingClientRect(); drag = { panel, x: event.clientX - card.left, y: event.clientY - card.top }; els.emotionDragHandle.setPointerCapture(event.pointerId); });
  els.emotionDragHandle.addEventListener("pointermove", (event) => { if (!drag) return; const left = Math.max(0, Math.min(event.clientX - drag.panel.left - drag.x, drag.panel.width - els.emotionWidget.offsetWidth)); const top = Math.max(0, Math.min(event.clientY - drag.panel.top - drag.y, drag.panel.height - els.emotionWidget.offsetHeight)); els.emotionWidget.style.left = `${left}px`; els.emotionWidget.style.top = `${top}px`; els.emotionWidget.style.right = "auto"; state.emotionPosition = { left, top }; });
  els.emotionDragHandle.addEventListener("pointerup", () => { drag = null; localStorage.setItem("yunque.web.emotion.position.v1", JSON.stringify(state.emotionPosition)); });
  els.emotionPin.onclick = () => { state.emotionPinned = !state.emotionPinned; updateEmotionPinState(); localStorage.setItem("yunque.web.emotion.pinned.v1", state.emotionPinned ? "1" : "0"); };
  window.addEventListener("resize", () => clampEmotionWidgetPosition(true));
}

function configureTrajectoryAnchor(reset = false) { const mode = state.trajectory.range; const label = els.trajectoryAnchor.closest("label").querySelector("span"); const today = chinaDateKey(); if (mode === "one_day") { els.trajectoryAnchor.type = "date"; if (reset || !els.trajectoryAnchor.value) els.trajectoryAnchor.value = today; label.textContent = "选择日期"; } else if (mode === "daily") { els.trajectoryAnchor.type = "month"; if (reset || !/^\d{4}-\d{2}$/.test(els.trajectoryAnchor.value)) els.trajectoryAnchor.value = today.slice(0,7); label.textContent = "选择月份"; } else { els.trajectoryAnchor.type = "number"; if (reset || !/^\d{4}$/.test(els.trajectoryAnchor.value)) els.trajectoryAnchor.value = today.slice(0,4); label.textContent = "选择年份"; } }
function trendLabel() { return { one_day:"当天原始记录", daily:"每日 24h 平均值", weekly:"每周 7 天平均值", monthly:"每个自然月平均值" }[state.trajectory.range]; }
function trendTime(item) { return item.period_label || new Date(item.created_at).toLocaleTimeString("zh-CN", { hour12:false }); }
function renderTrajectory() {
  const data = state.trajectory, summary = data.summary || {}, records = data.records || [];
  els.trajectoryAverage.textContent = Number(summary.average || 0).toFixed(3); els.trajectoryChange.textContent = `${Number(summary.change || 0) > 0 ? "+" : ""}${Number(summary.change || 0).toFixed(3)}`; els.trajectoryRecordCount.textContent = String(summary.raw_count || 0); els.trajectoryAudioCount.textContent = String(summary.audio_count || 0); els.trajectoryPeriodLabel.textContent = trendLabel();
  if (!records.length) els.trajectoryChart.innerHTML = '<div class="trajectory-empty"><strong>还没有情绪记录</strong><span>完成一次对话后会显示在这里。</span></div>';
  else { const w=760,h=280,p={l:42,r:18,t:18,b:34}, pw=w-p.l-p.r,ph=h-p.t-p.b, vals=records.flatMap(x=>[x.text,x.fusion,...(x.audio_available?[x.audio]:[])]),lo=Math.min(0,...vals)-.15,hi=Math.max(0,...vals)+.15,x=i=>p.l+(records.length===1?pw/2:i*pw/(records.length-1)),y=v=>p.t+(hi-v)*ph/(hi-lo),path=(k,ok=()=>true)=>records.map((v,i)=>ok(v)?`${i?"L":"M"}${x(i)},${y(v[k])}`:"").filter(Boolean).join(" ").replace(/^L/,"M"),grid=[0,1,2,3,4].map(i=>{const yy=p.t+i*ph/4;return `<line class="chart-grid" x1="${p.l}" y1="${yy}" x2="${w-p.r}" y2="${yy}"/>`}).join(""),labels=[0,Math.floor((records.length-1)/2),records.length-1].filter((v,i,a)=>a.indexOf(v)===i).map(i=>`<text class="chart-axis-label" x="${x(i)}" y="${h-8}" text-anchor="middle">${trendTime(records[i])}</text>`).join(""); els.trajectoryChart.innerHTML=`<svg viewBox="0 0 ${w} ${h}">${grid}<path class="chart-line is-text" d="${path("text")}"/><path class="chart-line is-audio" d="${path("audio",v=>v.audio_available)}"/><path class="chart-line is-fusion" d="${path("fusion")}"/>${records.map((v,i)=>`<circle class="chart-point" cx="${x(i)}" cy="${y(v.fusion)}" r="4"><title>${trendTime(v)} ${v.fusion.toFixed(3)}</title></circle>`).join("")}${labels}</svg>`; }
  els.trajectoryChanges.textContent=""; records.slice(1).map((v,i)=>({v,d:v.fusion-records[i].fusion})).sort((a,b)=>Math.abs(b.d)-Math.abs(a.d)).slice(0,4).forEach(({v,d})=>{const n=document.createElement("article");n.className=`trajectory-change-item ${d>=0?"is-up":"is-down"}`;n.innerHTML=`<strong>${d>=0?"上升":"下降"} ${Math.abs(d).toFixed(3)}</strong><span>${trendTime(v)}</span>`;els.trajectoryChanges.append(n)}); if(!els.trajectoryChanges.children.length)els.trajectoryChanges.innerHTML='<span class="empty-note">至少需要两次记录</span>';
  els.trajectoryStrategies.textContent="";(data.strategies||[]).slice(0,3).forEach(v=>{const n=document.createElement("article");n.className="trajectory-strategy-item";const a=document.createElement("strong"),b=document.createElement("span");a.textContent=v.scene||"陪伴策略";b.textContent=v.description;n.append(a,b);els.trajectoryStrategies.append(n)});if(!els.trajectoryStrategies.children.length)els.trajectoryStrategies.innerHTML='<span class="empty-note">暂无已生成策略</span>';
  renderTrajectoryMemories();
}
function renderTrajectoryMemories(){els.trajectoryMemoryList.textContent="";(state.trajectory.memories||[]).filter(v=>state.trajectoryTopic==="all"||(v.topics||[]).includes(state.trajectoryTopic)).forEach(v=>{const n=document.createElement("article");n.className="trajectory-memory-item";const tags=(v.topics||[]).map(t=>`<span class="trajectory-topic">${TOPIC_LABELS[t]||t}</span>`).join("");n.innerHTML=`<div>${tags}<span class="trajectory-layer">${v.layer==="reflection"?"反思":"观察"}</span></div>`;const p=document.createElement("p"),s=document.createElement("small");p.textContent=v.description;s.textContent=`${new Date(v.created_at).toLocaleString("zh-CN")} · 重要度 ${Number(v.importance).toFixed(1)}`;n.append(p,s);els.trajectoryMemoryList.append(n)});if(!els.trajectoryMemoryList.children.length)els.trajectoryMemoryList.innerHTML='<span class="empty-note">当前范围内暂无关联记忆</span>'}
async function fetchTrajectory(){try{state.trajectory=await requestJson(`/api/emotion/trends?range=${state.trajectory.range}&anchor=${encodeURIComponent(els.trajectoryAnchor.value)}`);renderTrajectory();setBackendOnline(true)}catch{state.trajectory={range:state.trajectory.range,records:[],memories:[],strategies:[],summary:{}};renderTrajectory()}}

function updateNewBadges() {
  const unread = state.memories.unread || {};
  els.memoryNewBadge.hidden = !Number(unread.total || 0);
  const pendingDiary = state.aiDiaryBatches.reduce((total, batch) => total + Number(batch.pending_count || 0), 0);
  els.diaryNewBadge.hidden = pendingDiary === 0;
}

function renderMemoryLayers() {
  els.memoryLayers.textContent = "";
  const title = document.createElement("div");
  title.className = "memory-section-label";
  title.textContent = "记忆层级";
  els.memoryLayers.append(title);
  Object.entries(LAYER_LABELS).forEach(([layer, label]) => {
    const button = document.createElement("button");
    button.className = `memory-nav-button${state.selectedLayer === layer ? " is-active" : ""}`;
    button.type = "button";
    button.innerHTML = layerIcon(layer);
    const text = document.createElement("span");
    text.textContent = label;
    button.append(text);
    if (Number(state.memories.unread?.[layer] || 0) > 0) {
      const badge = document.createElement("span");
      badge.className = "new-badge";
      badge.textContent = "NEW";
      button.append(badge);
    }
    button.addEventListener("click", () => {
      state.selectedLayer = layer;
      state.selectedMemoryId = "";
      renderMemoryBrowser();
    });
    els.memoryLayers.append(button);
  });
}

function renderMemoryItems() {
  els.memoryItems.textContent = "";
  const title = document.createElement("div");
  title.className = "memory-section-label";
  title.textContent = LAYER_LABELS[state.selectedLayer];
  els.memoryItems.append(title);
  const items = state.memories.layers?.[state.selectedLayer] || [];
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty-note";
    empty.textContent = "暂无记忆";
    els.memoryItems.append(empty);
    return;
  }
  items.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `memory-item-button${state.selectedMemoryId === item.id ? " is-active" : ""}`;
    const row = document.createElement("span");
    row.style.display = "flex";
    row.style.alignItems = "center";
    row.style.gap = "8px";
    const id = document.createElement("strong");
    id.textContent = item.id;
    row.append(id);
    if (item.is_new) {
      const badge = document.createElement("span");
      badge.className = "new-badge";
      badge.textContent = "NEW";
      row.append(badge);
    }
    const preview = document.createElement("small");
    preview.textContent = item.scene || item.description;
    button.append(row, preview);
    button.addEventListener("click", () => selectMemory(item));
    els.memoryItems.append(button);
  });
}

function renderMemoryDetail() {
  const item = (state.memories.layers?.[state.selectedLayer] || [])
    .find((entry) => entry.id === state.selectedMemoryId);
  els.memoryDetail.textContent = "";
  if (!item) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.innerHTML = '<svg viewBox="0 0 24 24"><ellipse cx="12" cy="5" rx="8" ry="3"></ellipse><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"></path></svg><p>选择一条记忆查看详情</p>';
    els.memoryDetail.append(empty);
    return;
  }
  const card = document.createElement("article");
  card.className = "memory-detail-card";
  const heading = document.createElement("h3");
  heading.textContent = item.id;
  const meta = document.createElement("div");
  meta.className = "detail-meta";
  [
    `层级：${LAYER_LABELS[item.layer]}`,
    ...(item.topics || []).map((topic) => `主题：${TOPIC_LABELS[topic] || topic}`),
    `重要度：${Number(item.importance).toFixed(1)}`,
    `置信度：${Number(item.confidence).toFixed(1)}`,
    item.review_status ? `审查：${REVIEW_LABELS[item.review_status] || item.review_status}` : "",
  ].filter(Boolean).forEach((value) => {
    const span = document.createElement("span");
    span.textContent = value;
    meta.append(span);
  });
  if (item.scene) {
    const scene = document.createElement("div");
    scene.className = "detail-content";
    scene.textContent = `适用场景：${item.scene}`;
    card.append(heading, meta, scene);
  } else {
    card.append(heading, meta);
  }
  const content = document.createElement("div");
  content.className = "detail-content";
  content.textContent = item.description;
  card.append(content);
  if (item.linked_memory_ids?.length) {
    const linksTitle = document.createElement("strong");
    linksTitle.textContent = "来源记忆";
    const links = document.createElement("div");
    links.className = "linked-list";
    item.linked_memory_ids.forEach((value) => {
      const span = document.createElement("span");
      span.textContent = value;
      links.append(span);
    });
    card.append(linksTitle, links);
  }
  els.memoryDetail.append(card);
}

function renderMemoryBrowser() {
  renderMemoryLayers();
  renderMemoryItems();
  renderMemoryDetail();
  updateNewBadges();
}

async function fetchMemories() {
  try {
    state.memories = await requestJson("/api/memory/v2");
    renderMemoryBrowser();
    setBackendOnline(true);
  } catch {
    setBackendOnline(false);
  }
}

async function selectMemory(item) {
  state.selectedMemoryId = item.id;
  renderMemoryBrowser();
  if (!item.is_new) return;
  try {
    state.memories = await requestJson("/api/memory/v2/read", {
      method: "POST",
      body: JSON.stringify({ layer: item.layer, id: item.id }),
    });
    state.selectedMemoryId = item.id;
    renderMemoryBrowser();
  } catch {
    // Reading the item still works if the seen-state update fails.
  }
}

function renderAiDiary() {
  els.aiDiaryList.textContent = "";
  if (!state.aiDiaryBatches.length) {
    const empty = document.createElement("div");
    empty.className = "empty-note";
    empty.textContent = "完成 30 个交互轮次后会生成第一份 AI记。";
    els.aiDiaryList.append(empty);
    updateNewBadges();
    return;
  }
  state.aiDiaryBatches.forEach((batch) => {
    const batchCard = document.createElement("article");
    batchCard.className = "diary-batch";
    const head = document.createElement("header");
    head.className = "batch-head";
    const title = document.createElement("strong");
    title.textContent = `AI记 · ${batch.batch_id}`;
    const status = document.createElement("span");
    status.textContent = batch.status === "reviewed" ? "已完成审查" : `待审查 ${batch.pending_count} 条`;
    head.append(title, status);
    batchCard.append(head);
    (batch.items || []).forEach((item) => {
      const card = document.createElement("section");
      card.className = "review-card";
      const top = document.createElement("div");
      top.className = "review-card-top";
      const id = document.createElement("span");
      id.className = "memory-id";
      id.textContent = item.id;
      top.append(id);
      (item.topics || []).forEach((topic) => {
        const chip = document.createElement("span");
        chip.className = "topic-chip";
        chip.textContent = TOPIC_LABELS[topic] || topic;
        top.append(chip);
      });
      const content = document.createElement("p");
      content.textContent = item.description;
      card.append(top, content);
      if (item.review_status === "pending") {
        const actions = document.createElement("div");
        actions.className = "review-actions";
        [
          ["确认", "confirm", "button-primary"],
          ["修改", "revise", ""],
          ["删除", "delete", "button-danger"],
        ].forEach(([label, action, className]) => {
          const button = document.createElement("button");
          button.type = "button";
          button.className = `button ${className}`.trim();
          button.textContent = label;
          button.addEventListener("click", () => reviewObservation(batch, item, action));
          actions.append(button);
        });
        card.append(actions);
      } else {
        const reviewed = document.createElement("span");
        reviewed.className = "review-status";
        reviewed.textContent = REVIEW_LABELS[item.review_status] || item.review_status;
        card.append(reviewed);
      }
      batchCard.append(card);
    });
    els.aiDiaryList.append(batchCard);
  });
  updateNewBadges();
}

async function fetchAiDiary() {
  try {
    const payload = await requestJson("/api/ai-diary/v2");
    state.aiDiaryBatches = payload.batches || [];
    renderAiDiary();
  } catch {
    state.aiDiaryBatches = [];
    renderAiDiary();
  }
}

async function reviewObservation(batch, item, action) {
  if (action === "revise") {
    state.revisionTarget = { batch, item };
    els.revisionInput.value = item.description;
    els.revisionModal.hidden = false;
    els.revisionInput.focus();
    return;
  }
  if (action === "delete" && !window.confirm(`确认删除 ${item.id}？这条观察将不参与反思和策略。`)) return;
  await submitObservationReview(batch.batch_id, item.id, action);
}

async function submitObservationReview(batchId, observationId, action, revisedContent = "") {
  try {
    await requestJson("/api/ai-diary/v2/review", {
      method: "POST",
      body: JSON.stringify({
        batch_id: batchId,
        observation_id: observationId,
        action,
        revised_content: revisedContent,
      }),
    });
    await Promise.all([fetchAiDiary(), fetchMemories()]);
  } catch (error) {
    window.alert(`审查失败：${error.message}`);
  }
}

function setDiaryMode(mode) {
  const ai = mode === "ai";
  els.diaryAiModeTab.classList.toggle("is-active", ai);
  els.diaryUserModeTab.classList.toggle("is-active", !ai);
  els.aiDiaryPane.classList.toggle("is-active", ai);
  els.userDiaryPane.classList.toggle("is-active", !ai);
  if (ai) fetchAiDiary();
}

async function loadUserDiary() {
  const date = els.userDiaryDate.value || chinaDateKey();
  els.userDiaryDate.value = date;
  try {
    const payload = await requestJson(`/api/diary?date=${encodeURIComponent(date)}`);
    const selected = payload.selected || {};
    els.userDiary.value = selected.date === date ? selected.user_markdown || "" : "";
    els.userDiaryStatus.textContent = "";
  } catch (error) {
    els.userDiaryStatus.textContent = error.message;
  }
}

async function saveUserDiary() {
  const markdown = els.userDiary.value.trim();
  if (!markdown) return;
  try {
    await requestJson("/api/diary/user", {
      method: "POST",
      body: JSON.stringify({ date: els.userDiaryDate.value, markdown }),
    });
    els.userDiaryStatus.textContent = "已保存";
  } catch (error) {
    els.userDiaryStatus.textContent = error.message;
  }
}

async function deleteUserDiary() {
  if (!window.confirm("确认删除这篇用户记？")) return;
  try {
    await requestJson("/api/diary/user/delete", {
      method: "POST",
      body: JSON.stringify({ date: els.userDiaryDate.value }),
    });
    els.userDiary.value = "";
    els.userDiaryStatus.textContent = "已删除";
  } catch (error) {
    els.userDiaryStatus.textContent = error.message;
  }
}

async function clearDevelopmentData() {
  if (!window.confirm("确认清空当前开发用户的聊天、日记和全部记忆？此操作不可撤销。")) return;
  try {
    await requestJson("/api/user/clear", {
      method: "POST",
      body: JSON.stringify({ include_local_user: true }),
    });
    state.history = [];
    state.memories = { layers: { observation: [], reflection: [], strategy: [] }, unread: { total: 0 } };
    state.aiDiaryBatches = [];
    state.selectedMemoryId = "";
    state.pendingFiles = [];
    state.pendingVoiceAudio = null;
    state.sentMedia = [];
    state.trajectory.data = null;
    renderChatHistory();
    renderPendingFiles();
    rebuildSentMedia();
    renderTrajectory();
    renderMemoryBrowser();
    renderAiDiary();
    els.userDiary.value = "";
    window.alert("开发数据已清空。");
  } catch (error) {
    window.alert(`清空失败：${error.message}`);
  }
}

els.enterAppButton.addEventListener("click", showApp);
els.authToggleButton.addEventListener("click", () => {
  if (!authRequired()) return;
  els.authForm.hidden = !els.authForm.hidden;
});
els.authForm.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth("login");
});
els.authRegisterButton.addEventListener("click", () => submitAuth("register"));

[els.sidebarChatTab, els.sidebarDiaryTab, els.sidebarMemoryTab, els.sidebarTrajectoryTab, els.sidebarSettingsTab]
  .forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
els.sidebarToggle.addEventListener("click", () => setSidebarCollapsed(!state.sidebarCollapsed));
els.mobileSidebarToggle.addEventListener("click", () => els.appShell.classList.add("is-mobile-menu-open"));
els.sidebarScrim.addEventListener("click", () => els.appShell.classList.remove("is-mobile-menu-open"));
els.emotionToggle.addEventListener("click", () => {
  showEmotionWidget(els.emotionWidget.hidden);
});
els.sentMediaToggle.onclick=()=>{const open=els.sentMediaPanel.hidden;els.sentMediaPanel.hidden=!open;els.sentMediaToggle.setAttribute("aria-expanded",String(open));els.chatView.classList.toggle("has-media-sidebar",open);requestAnimationFrame(()=>clampEmotionWidgetPosition(true))};
els.sentMediaClose.onclick=()=>{els.sentMediaPanel.hidden=true;els.sentMediaToggle.setAttribute("aria-expanded","false");els.chatView.classList.remove("has-media-sidebar");requestAnimationFrame(()=>clampEmotionWidgetPosition(true))};
els.attachmentButton.onclick=()=>els.attachmentInput.click(); els.attachmentInput.onchange=async()=>{await addFiles(els.attachmentInput.files||[]);els.attachmentInput.value=""};
let dragDepth=0;const chatPanel=els.chatForm.closest(".chat-panel"); chatPanel.ondragenter=e=>{e.preventDefault();dragDepth++;chatPanel.classList.add("is-dragging")};chatPanel.ondragover=e=>e.preventDefault();chatPanel.ondragleave=()=>{if(--dragDepth<=0){dragDepth=0;chatPanel.classList.remove("is-dragging")}};chatPanel.ondrop=async e=>{e.preventDefault();dragDepth=0;chatPanel.classList.remove("is-dragging");await addFiles(e.dataTransfer?.files||[])};
document.querySelectorAll(".trajectory-range button").forEach(button=>button.onclick=()=>{document.querySelectorAll(".trajectory-range button").forEach(v=>v.classList.toggle("is-active",v===button));state.trajectory.range=button.dataset.range||"one_day";configureTrajectoryAnchor(true);fetchTrajectory()});
els.trajectoryAnchor.onchange=fetchTrajectory;els.trajectoryTopicFilters.querySelectorAll("button").forEach(button=>button.onclick=()=>{els.trajectoryTopicFilters.querySelectorAll("button").forEach(v=>v.classList.toggle("is-active",v===button));state.trajectoryTopic=button.dataset.topic||"all";renderTrajectoryMemories()});
els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if(state.chatPending){state.chatAbortController?.abort("user_cancelled");return}
  let message = els.messageInput.value.trim();
  if(!message&&state.pendingFiles.length)message="请结合我发送的媒体回应我。";
  if (!message) return;
  els.messageInput.value = "";
  els.messageInput.dispatchEvent(new Event("input", { bubbles: true }));
  sendChat(message);
});
els.voiceButton.addEventListener("click", toggleVoiceRecording);
els.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    els.chatForm.requestSubmit();
  }
});
els.diaryUserModeTab.addEventListener("click", () => setDiaryMode("user"));
els.diaryAiModeTab.addEventListener("click", () => setDiaryMode("ai"));
els.userDiaryDate.addEventListener("change", loadUserDiary);
els.diarySaveButton.addEventListener("click", saveUserDiary);
els.diaryDeleteButton.addEventListener("click", deleteUserDiary);
els.proactiveReplyToggle.addEventListener("change", () => {
  state.proactiveEnabled = els.proactiveReplyToggle.checked;
  localStorage.setItem("yunque.web.proactive.v2", state.proactiveEnabled ? "1" : "0");
});
els.clearDataButton.addEventListener("click", clearDevelopmentData);
els.revisionCancel.addEventListener("click", () => {
  state.revisionTarget = null;
  els.revisionModal.hidden = true;
});
els.revisionSubmit.addEventListener("click", async () => {
  const target = state.revisionTarget;
  const content = els.revisionInput.value.trim();
  if (!target || !content) return;
  els.revisionModal.hidden = true;
  state.revisionTarget = null;
  await submitObservationReview(target.batch.batch_id, target.item.id, "revise", content);
});

setInterval(() => {
  const idleMs = Date.now() - state.lastInteractionAt;
  if (state.proactiveEnabled && idleMs >= 2 * 60 * 1000 && !state.chatPending && state.activeView === "chat") {
    sendChat("", { proactive: true });
    state.lastInteractionAt = Date.now();
  }
}, 30_000);

async function initialize() {
  els.userDiaryDate.value = chinaDateKey();
  configureTrajectoryAnchor(true);
  try {
    state.sidebarCollapsed = localStorage.getItem("yunque.web.sidebar.collapsed.v2") === "1";
    state.proactiveEnabled = localStorage.getItem("yunque.web.proactive.v2") !== "0";
    state.emotionPinned = localStorage.getItem("yunque.web.emotion.pinned.v1") !== "0";
    state.emotionPosition = JSON.parse(localStorage.getItem("yunque.web.emotion.position.v1")||"null");
  } catch {
    state.sidebarCollapsed = false;
    state.proactiveEnabled = true;
  }
  setSidebarCollapsed(state.sidebarCollapsed);
  els.proactiveReplyToggle.checked = state.proactiveEnabled;
  renderChatHistory();
  renderMemoryBrowser();
  renderAiDiary();
  renderPendingFiles(); rebuildSentMedia(); renderTrajectory(); initializeEmotionDragging();
  updateEmotionPinState(); if(state.emotionPosition){els.emotionWidget.style.left=`${state.emotionPosition.left}px`;els.emotionWidget.style.top=`${state.emotionPosition.top}px`;els.emotionWidget.style.right="auto"}
  await checkAuth();
}

initialize();
