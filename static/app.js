const state = {
  authUser: null,
  backendOnline: false,
  activeView: "home",
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
  expandedViews: { chat: false, study: false },
};

const els = Object.fromEntries(
  [
    "introScreen", "enterAppButton", "authToggleButton", "authForm", "authUsername",
    "authPassword", "authLoginButton", "authRegisterButton", "authStatus", "appShell",
    "appSidebar", "sidebarToggle", "mobileSidebarToggle", "sidebarScrim", "activeViewTitle",
    "backendStatus", "agentStatus", "sidebarHomeTab", "sidebarChatTab", "sidebarStudyTab", "sidebarProfileTab", "sidebarGrowthTab", "sidebarDiaryTab", "sidebarMemoryTab", "sidebarTrajectoryTab",
    "sidebarSettingsTab", "diaryNewBadge", "memoryNewBadge", "homeView", "chatView", "studyView", "profileView", "growthView", "diaryView", "trajectoryView",
    "memoryView", "settingsView", "emotionWidget", "emotionToggle", "emotionPin", "emotionDragHandle", "textScore",
    "fusionScore", "audioScore", "chatList", "chatForm", "messageInput", "voiceButton", "sendButton", "diaryUserModeTab",
    "diaryAiModeTab", "userDiaryPane", "aiDiaryPane", "userDiaryDate", "userDiary",
    "userDiaryStatus", "diaryDeleteButton", "diarySaveButton", "aiDiaryList",
    "memoryLayers", "memoryItems", "memoryDetail", "proactiveReplyToggle", "clearDataButton",
    "revisionModal", "revisionInput", "revisionCancel", "revisionSubmit",
    "attachmentInput", "attachmentButton", "pendingAttachments", "sentMediaToggle", "sentMediaPanel", "sentMediaList", "sentMediaCount", "sentMediaClose", "dropOverlay",
    "trajectoryAnchor", "trajectoryAverage", "trajectoryChange", "trajectoryRecordCount", "trajectoryAudioCount", "trajectoryPeriodLabel", "trajectoryChart", "trajectoryChanges", "trajectoryStrategies", "trajectoryTopicFilters", "trajectoryMemoryList",
    "currentStudySessionTitle", "currentStudySubject", "studySessionSelect", "newStudySessionBtn",
    "studyChatList", "studyForm", "studyMessageInput", "studySendButton",
    "newStudySessionModal", "newStudySessionForm", "newStudySubjectInput", "newStudyTopicInput", "newStudySeedInput", "newStudyCancelBtn", "newStudyConfirmBtn",
    "openNewProfileModalBtn", "profileCardsGrid", "currentActiveProfileBadge",
    "editProfileName", "editProfileStage", "editProfileGrade", "editProfileSubCategory", "editProfileProvince",
    "editProfileCurrentSchool", "editProfileTargetSchool", "editProfileTargetGoal", "editProfileScore", "editProfileRank", "editProfileExtra",
    "saveActiveProfileBtn", "deleteActiveProfileBtn", "profileSaveStatus",
    "newProfileModal", "newProfileForm", "newProfileStage", "newProfileName", "newProfileGrade", "newProfileSubCategory",
    "newProfileProvince", "newProfileCurrentSchool", "newProfileTargetSchool", "newProfileTargetGoal", "newProfileScore", "newProfileRank",
    "newProfileCancelBtn", "newProfileSubmitBtn",
  ].map((id) => [id, document.getElementById(id)]),
);

const CHINA_TIME_ZONE = "Asia/Shanghai";
const API_BASE = resolveApiBase();
const VIEW_TITLES = { home: "主界面", chat: "聊聊天", study: "开始学习！", profile: "用户画像", growth: "学业成长", diary: "日记", memory: "长期记忆", trajectory: "情绪轨迹", settings: "设置" };
const LAYER_LABELS = { observation: "观察", reflection: "反思", strategy: "策略" };
const TOPIC_LABELS = { event: "事件", preference: "偏好", routine: "习惯", relationship: "关系" };
const REVIEW_LABELS = { pending: "待审查", confirmed: "已确认", revised: "已修改", deleted: "已删除" };
const USER_ICON = `
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle cx="12" cy="8" r="4"></circle>
    <path d="M4.5 21a7.5 7.5 0 0 1 15 0"></path>
  </svg>`;

function resolveApiBase() {
  if (window.yunqueDesktop?.apiBase) return window.yunqueDesktop.apiBase;
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
  state.backendOnline = Boolean(online);
  els.backendStatus.classList.toggle("is-online", online);
  els.backendStatus.lastChild.textContent = online ? "在线" : "离线";
}

let viewLoadTimer = 0;

function setView(view) {
  if (!Object.hasOwn(VIEW_TITLES, view)) return;
  const prevView = state.activeView;
  state.activeView = view;
  els.appShell.dataset.view = view;
  document.getElementById("homeView").classList.toggle("is-active", view === "home");
  document.getElementById("homeBackButton").hidden = view === "home";
  const map = {
    home: [els.sidebarHomeTab, els.homeView],
    chat: [els.sidebarChatTab, els.chatView],
    study: [els.sidebarStudyTab, els.studyView],
    profile: [els.sidebarProfileTab, els.profileView],
    growth: [els.sidebarGrowthTab, els.growthView],
    diary: [els.sidebarDiaryTab, els.diaryView],
    memory: [els.sidebarMemoryTab, els.memoryView],
    trajectory: [els.sidebarTrajectoryTab, els.trajectoryView],
    settings: [els.sidebarSettingsTab, els.settingsView],
  };
  Object.entries(map).forEach(([key, [tab, panel]]) => {
    if (tab) tab.classList.toggle("is-active", key === view);
    if (panel) panel.classList.toggle("is-active", key === view);
  });
  if (els.activeViewTitle) els.activeViewTitle.textContent = VIEW_TITLES[view];
  els.appShell.classList.remove("is-mobile-menu-open");
  syncExpandedCardState(view);
  window.dispatchEvent(new CustomEvent("yunque:view", { detail: view }));

  clearTimeout(viewLoadTimer);
  const stageMoved = prevView !== view && (prevView === "home" || view === "home" || prevView === "study" || view === "study");
  const runViewLoad = () => {
    if (state.activeView !== view) return;
    if (view === "chat") loadChatHistory();
    if (view === "study") loadStudySessions();
    if (view === "profile") { loadProfiles(); fetchAcademicScores(); }
    if (view === "growth") { fetchAcademicProfile(); fetchAcademicScores(); }
    if (view === "memory") fetchMemories();
    if (view === "diary") fetchAiDiary();
    if (view === "trajectory") fetchTrajectory();
  };
  if (stageMoved) {
    viewLoadTimer = setTimeout(runViewLoad, 410);
  } else {
    runViewLoad();
  }
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
  els.enterAppButton.disabled = false;
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
  if (typing) {
    bubble.className = "bubble";
    bubble.textContent = content;
  } else {
    bubble.className = "bubble md-bubble";
    bubble.innerHTML = renderMarkdown(content);
    hydrateHtmlWidgets(bubble);
  }
  wrap.append(label, bubble);
  message.append(wrap);
  els.chatList.append(message);
  els.chatList.scrollTop = els.chatList.scrollHeight;
  return message;
}

let lastRenderedChatSig = "";

function renderChatHistory(force = false) {
  const sig = `${activeProfile?.id || ""}:${state.history.length}:${state.history.map((i) => `${i.role}:${(i.content || "").length}`).join("|")}`;
  if (!force && sig === lastRenderedChatSig && els.chatList.children.length > 0) {
    return;
  }
  lastRenderedChatSig = sig;
  els.chatList.textContent = "";
  if (!state.history.length) {
    appendMessage("assistant", "你好，我是云雀。今天有什么想和我聊聊的吗？");
    return;
  }
  state.history.forEach((item) => appendMessage(item.role, item.content));
}

async function loadChatHistory() {
  try {
    const profileParam = activeProfile?.id ? `&profile_id=${encodeURIComponent(activeProfile.id)}` : "";
    const payload = await requestJson(`/api/chat/history?limit=30${profileParam}`);
    state.history = payload.items || [];
    renderChatHistory();
    rebuildSentMedia();
    setBackendOnline(true);
    await checkProfileGreeting();
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

async function consumeSseStream(url, payload, { signal, onMeta, onDelta, onDone, onError } = {}) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    let msg = `请求失败 (${response.status})`;
    try {
      const errJson = await response.json();
      if (errJson?.error) msg = errJson.error;
    } catch {}
    const err = new Error(msg);
    err.status = response.status;
    throw err;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let donePayload = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part
        .split("\n")
        .find((l) => l.startsWith("data:"));
      if (!line) continue;
      const raw = line.slice(5).trim();
      if (!raw) continue;
      let evt;
      try {
        evt = JSON.parse(raw);
      } catch {
        continue;
      }
      if (evt.type === "meta" && onMeta) onMeta(evt);
      else if (evt.type === "delta" && onDelta) onDelta(evt.delta || "");
      else if (evt.type === "done") {
        donePayload = evt;
        if (onDone) onDone(evt);
      } else if (evt.type === "error") {
        if (onError) onError(new Error(evt.error || "流式生成出错"));
        else throw new Error(evt.error || "流式生成出错");
      }
    }
  }
  return donePayload;
}

async function sendChat(message, { proactive = false } = {}) {
  if (state.chatPending) return;
  const abortController = new AbortController(); state.chatAbortController = abortController; setChatPending(true);
  let typing = null;
  if (!proactive && message) {
    appendMessage("user", message);
  }
  typing = appendMessage("assistant", "···", { typing: true });
  if (els.agentStatus) els.agentStatus.textContent = "云雀正在思考";
  let streamText = "";
  let streamBubble = null;
  let lastRenderAt = 0;

  try {
    const attachments = proactive ? [] : [...state.pendingFiles];
    const voiceAudio = proactive ? "" : state.pendingVoiceAudio;
    const reqBody = {
      message: proactive ? "" : message,
      proactive,
      proactive_reason: proactive ? "用户一段时间没有继续输入" : "",
      audio_data: voiceAudio,
      attachments,
      timestamp: chinaTimestamp(),
      profile_id: activeProfile?.id || "",
    };

    let donePayload = null;
    try {
      donePayload = await consumeSseStream("/api/chat/stream", reqBody, {
        signal: abortController.signal,
        onMeta: (meta) => {
          if (meta.scores) updateScores(meta.scores);
          if (els.agentStatus) {
            els.agentStatus.textContent = meta.modal_inputs?.audio_available ? "文本与音频陪伴模式" : "文本陪伴模式";
          }
        },
        onDelta: (delta) => {
          if (!delta) return;
          streamText += delta;
          if (!streamBubble) {
            typing.classList.remove("typing");
            streamBubble = typing.querySelector(".bubble");
            streamBubble.classList.add("md-bubble");
          }
          const now = Date.now();
          if (now - lastRenderAt > 120) {
            lastRenderAt = now;
            streamBubble.innerHTML = renderMarkdown(streamText, { streaming: true });
            els.chatList.scrollTop = els.chatList.scrollHeight;
          }
        },
      });
    } catch (streamErr) {
      if (streamErr?.status !== 404) throw streamErr;
      // 若后端尚未重启，自动降级到原有 /api/chat 接口
      const fallbackRes = await requestJson("/api/chat", {
        method: "POST",
        timeoutMs: voiceAudio ? 120000 : 30000,
        signal: abortController.signal,
        body: JSON.stringify(reqBody),
      });
      if (fallbackRes.scores) updateScores(fallbackRes.scores);
      donePayload = {
        ...fallbackRes,
        reply: fallbackRes.agent?.reply || "",
      };
    }

    const finalReply = donePayload?.reply || streamText;
    if (!finalReply) throw new Error("模型没有返回回复内容");
    if (!streamBubble) {
      typing.classList.remove("typing");
      streamBubble = typing.querySelector(".bubble");
      streamBubble.classList.add("md-bubble");
    }
    streamBubble.innerHTML = renderMarkdown(finalReply);
    hydrateHtmlWidgets(streamBubble);
    els.chatList.scrollTop = els.chatList.scrollHeight;

    if (donePayload?.study_intent && donePayload?.ask_study_confirmation) {
      const si = donePayload.study_intent;
      appendChatActionCard({
        title: "云雀伴学意图感知",
        desc: `检测到你想开始学习【${escapeHtml(si.subject || '自选学科')}】`,
        actions: [
          {
            text: "🚀 立即开始学习",
            action: "confirm-study",
            class: "primary",
            dataAttrs: `data-subject="${escapeHtml(si.subject || '')}" data-title="${escapeHtml(si.title || '')}" data-prompt="${escapeHtml(si.prompt_seed || '')}"`
          },
          {
            text: "继续在这里聊",
            action: "cancel-study",
            class: "secondary"
          }
        ]
      });
    }

    state.history = donePayload?.chat_history || state.history;
    state.pendingFiles = []; state.pendingVoiceAudio = ""; renderPendingFiles(); rebuildSentMedia();
    setBackendOnline(true);
    state.lastInteractionAt = Date.now();
    await Promise.allSettled([fetchMemories(), fetchAiDiary()]);
  } catch (error) {
    if (!streamText) typing?.remove();
    if (abortController.signal.aborted) { if (els.agentStatus) els.agentStatus.textContent = "已停止生成"; return; }
    window.alert(error.message); if (els.agentStatus) els.agentStatus.textContent = Number(error.status || 0) >= 500 ? "模型调用失败" : "连接失败";
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

const SUPPORTED_DOC_EXTENSIONS = new Set([
  ".pdf", ".docx", ".pptx", ".xlsx", ".csv", ".tsv", ".txt", ".md", ".markdown",
  ".json", ".jsonl", ".xml", ".yaml", ".yml", ".py", ".js", ".ts", ".tsx", ".jsx",
  ".html", ".htm", ".css", ".scss", ".java", ".c", ".cpp", ".h", ".hpp", ".go", ".rs", ".sql", ".sh", ".log"
]);

function isSupportedClientFile(file) {
  const type = String(file?.type || "").toLowerCase();
  if (type.startsWith("image/") || type.startsWith("audio/") || type.startsWith("text/") || type === "application/pdf" || type === "application/json") {
    return true;
  }
  const name = String(file?.name || "").toLowerCase();
  const dotIdx = name.lastIndexOf(".");
  return dotIdx >= 0 && SUPPORTED_DOC_EXTENSIONS.has(name.slice(dotIdx));
}

function inferClientMime(file) {
  if (file?.type) return file.type;
  const name = String(file?.name || "").toLowerCase();
  if (name.endsWith(".pdf")) return "application/pdf";
  if (name.endsWith(".docx")) return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (name.endsWith(".pptx")) return "application/vnd.openxmlformats-officedocument.presentationml.presentation";
  if (name.endsWith(".xlsx")) return "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  if (name.endsWith(".csv")) return "text/csv";
  if (name.endsWith(".json")) return "application/json";
  return "text/plain";
}

async function addFiles(fileList) {
  const files = [...fileList].filter(isSupportedClientFile);
  const available = 9 - state.pendingFiles.length;
  if (files.length > available) window.alert("每次最多选择 9 个文件。");
  const additions = [];
  for (const file of files.slice(0, available)) {
    if (file.size > 10 * 1024 * 1024) { window.alert(`${file.name} 超过 10 MB`); continue; }
    additions.push({ name: file.name, type: inferClientMime(file), size: file.size, data: await blobToDataUrl(file) });
  }
  state.pendingFiles.push(...additions); renderPendingFiles();
}

function rebuildSentMedia() {
  state.sentMedia = state.history.flatMap((item) => item.role === "user" ? (item.attachments || []) : []);
  els.sentMediaCount.textContent = String(state.sentMedia.length);
  const deckMediaCount = document.getElementById("deckMediaCount");
  if (deckMediaCount) deckMediaCount.textContent = String(state.sentMedia.length);
  els.sentMediaList.textContent = "";
  if (!state.sentMedia.length) { els.sentMediaList.innerHTML = '<span class="empty-note">还没有发送过媒体</span>'; return; }
  state.sentMedia.forEach((item) => { const node = document.createElement("article"); node.className = "sent-media-item"; node.textContent = `${item.name} · ${item.type} · ${Math.ceil(Number(item.size || 0) / 1024)} KB`; els.sentMediaList.append(node); });
}

async function analyzeVoiceInput(audioData) {
  if (state.chatPending) return;
  const controller = new AbortController(); state.chatAbortController = controller; setChatPending(true, "识别");
  if (els.agentStatus) els.agentStatus.textContent = "正在识别语音";
  try {
    const payload = await requestJson("/api/audio/input", { method: "POST", timeoutMs: 120000, signal: controller.signal, body: JSON.stringify({ audio_data: audioData, timestamp: chinaTimestamp() }) });
    const transcript = String(payload.transcript || "").trim(); if (!transcript) throw new Error("没有识别到语音文字");
    const existing = els.messageInput.value.trim(); els.messageInput.value = existing ? `${existing} ${transcript}` : transcript;
    state.pendingVoiceAudio = audioData; renderPendingFiles(); els.messageInput.focus(); if (els.agentStatus) els.agentStatus.textContent = "语音识别完成 · 录音等待发送"; setBackendOnline(true);
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
      if (els.agentStatus) els.agentStatus.textContent = "正在识别语音";
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
    if (els.agentStatus) els.agentStatus.textContent = "正在录音，点击麦克风结束识别";
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

[els.sidebarHomeTab, els.sidebarChatTab, els.sidebarStudyTab, els.sidebarProfileTab, els.sidebarDiaryTab, els.sidebarMemoryTab, els.sidebarTrajectoryTab, els.sidebarSettingsTab]
  .filter(Boolean)
  .forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
els.sidebarToggle.addEventListener("click", () => setSidebarCollapsed(!state.sidebarCollapsed));
els.mobileSidebarToggle.addEventListener("click", () => els.appShell.classList.add("is-mobile-menu-open"));
els.sidebarScrim.addEventListener("click", () => els.appShell.classList.remove("is-mobile-menu-open"));
els.emotionToggle.addEventListener("click", () => {
  showEmotionWidget(els.emotionWidget.hidden);
});

function syncExpandedCardState(view = state.activeView) {
  const isExpandable = view === "chat" || view === "study";
  const expanded = isExpandable && Boolean(state.expandedViews?.[view]);
  els.appShell.classList.toggle("is-card-expanded", expanded);

  const btnMap = [
    ["chat", document.getElementById("chatExpandToggle")],
    ["study", document.getElementById("studyExpandToggle")],
  ];
  btnMap.forEach(([key, btn]) => {
    if (!btn) return;
    const active = Boolean(state.expandedViews?.[key]);
    btn.classList.toggle("is-expanded", active);
    btn.setAttribute("aria-pressed", String(active));
    btn.title = active ? "收起还原" : "展开全屏";
    const span = btn.querySelector("span");
    if (span) span.textContent = active ? "收起" : "展开";
  });
}

["chat", "study"].forEach((viewKey) => {
  const btn = document.getElementById(viewKey === "chat" ? "chatExpandToggle" : "studyExpandToggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    state.expandedViews[viewKey] = !state.expandedViews[viewKey];
    syncExpandedCardState(state.activeView);
  });
});

function setActiveChatDeckCard(targetCard) {
  const deck = document.getElementById("chatDeck");
  const chatCard = document.getElementById("chatPrimaryCard") || document.querySelector("#chatView .chat-panel");
  const mediaCard = els.sentMediaPanel || document.getElementById("sentMediaPanel");
  if (!deck || !chatCard || !mediaCard) return;

  const isMediaFront = targetCard === "media";
  deck.dataset.activeCard = isMediaFront ? "media" : "chat";

  chatCard.classList.toggle("is-front-card", !isMediaFront);
  chatCard.classList.toggle("is-back-card", isMediaFront);

  mediaCard.classList.toggle("is-front-card", isMediaFront);
  mediaCard.classList.toggle("is-back-card", !isMediaFront);

  if (els.sentMediaToggle) {
    els.sentMediaToggle.setAttribute("aria-expanded", String(isMediaFront));
  }
  if (!isMediaFront) {
    requestAnimationFrame(() => clampEmotionWidgetPosition(true));
  }
}

els.sentMediaToggle.onclick = (e) => {
  e.stopPropagation();
  const deck = document.getElementById("chatDeck");
  const next = deck?.dataset.activeCard === "media" ? "chat" : "media";
  setActiveChatDeckCard(next);
};
els.sentMediaClose.onclick = (e) => {
  e.stopPropagation();
  setActiveChatDeckCard("chat");
};
document.getElementById("chatPrimaryCard")?.addEventListener("click", (e) => {
  const card = e.currentTarget;
  if (card.classList.contains("is-back-card")) {
    e.stopPropagation();
    setActiveChatDeckCard("chat");
  }
});
els.sentMediaPanel?.addEventListener("click", (e) => {
  const card = e.currentTarget;
  if (card.classList.contains("is-back-card")) {
    e.stopPropagation();
    setActiveChatDeckCard("media");
  }
});
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
  if (state.proactiveEnabled && state.authUser && state.backendOnline && !document.hidden && idleMs >= 2 * 60 * 1000 && !state.chatPending && state.activeView === "chat") {
    sendChat("", { proactive: true });
    state.lastInteractionAt = Date.now();
  }
}, 30_000);

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderInlineMarkdown(rawText) {
  const inlineCodes = [];
  let text = escapeHtml(rawText || "");
  text = text.replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = inlineCodes.length;
    inlineCodes.push(`<code>${code}</code>`);
    return `\u0000IC${idx}\u0000`;
  });
  text = text.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, label, url) => {
    const cleanUrl = url.replace(/&amp;/g, "&").trim();
    if (/^(https?:\/\/|\/|#)/i.test(cleanUrl)) {
      return `<a href="${escapeHtml(cleanUrl)}" target="_blank" rel="noopener noreferrer">${label}</a>`;
    }
    return `${label} (${url})`;
  });
  text = text.replace(/\*\*([\s\S]+?)\*\*/g, "<strong>$1</strong>");
  text = text.replace(/__([\s\S]+?)__/g, "<strong>$1</strong>");
  text = text.replace(/~~([\s\S]+?)~~/g, "<del>$1</del>");
  text = text.replace(/(^|[^\w\\])\*([^*\n]+?)\*(?!\w)/g, "$1<em>$2</em>");
  text = text.replace(/\u0000IC(\d+)\u0000/g, (_, idx) => inlineCodes[Number(idx)] || "");
  return text;
}

const htmlWidgetCodeStore = new Map();
let htmlWidgetSeq = 0;

function isRenderableHtmlBlock(lang, code) {
  const normalizedLang = String(lang || "").trim().toLowerCase();
  if (normalizedLang === "html-widget" || normalizedLang === "artifact-html") return true;
  if (normalizedLang === "html") {
    return /<\s*(?:!doctype|html|head|body|div|section|main|canvas|svg|script|style|form|table|button|input)\b/i.test(code);
  }
  return false;
}

function buildSandboxedWidgetDoc(rawHtml, widgetId) {
  const code = String(rawHtml || "").trim();
  const heightReporter = `<script>
(function(){
  var id = ${JSON.stringify(widgetId)};
  function postHeight(){
    try {
      var h = Math.max(
        document.documentElement ? document.documentElement.scrollHeight : 0,
        document.body ? document.body.scrollHeight : 0
      );
      window.parent.postMessage({ type: "lark-widget-height", id: id, height: h }, "*");
    } catch (e) {}
  }
  if (typeof ResizeObserver !== "undefined") {
    var ro = new ResizeObserver(postHeight);
    window.addEventListener("DOMContentLoaded", function(){
      if (document.body) ro.observe(document.body);
      postHeight();
    });
  }
  window.addEventListener("load", postHeight);
  setTimeout(postHeight, 120);
  setTimeout(postHeight, 450);
})();
<\/script>`;

  if (/<\s*(?:!doctype|html)\b/i.test(code)) {
    if (/<\/body>/i.test(code)) {
      return code.replace(/<\/body>/i, `${heightReporter}</body>`);
    }
    return `${code}\n${heightReporter}`;
  }

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<style>
  *, *::before, *::after { box-sizing: border-box; }
  html, body { margin: 0; padding: 12px; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color: #1e293b; background: #ffffff; }
</style>
</head>
<body>
${code}
${heightReporter}
</body>
</html>`;
}

function openWidgetFullscreenModal(widgetId) {
  const rawCode = htmlWidgetCodeStore.get(widgetId);
  if (!rawCode) return;
  const existing = document.getElementById("mdWidgetFullscreenBackdrop");
  if (existing) existing.remove();

  const backdrop = document.createElement("div");
  backdrop.id = "mdWidgetFullscreenBackdrop";
  backdrop.className = "md-widget-fullscreen-backdrop";
  backdrop.innerHTML = `
    <div class="md-widget-fullscreen-dialog" role="dialog" aria-modal="true" aria-label="交互组件全屏预览">
      <div class="md-widget-bar">
        <span class="md-widget-title">交互式组件 · 放大预览</span>
        <div class="md-widget-actions">
          <button type="button" class="md-widget-btn" data-action="close">关闭</button>
        </div>
      </div>
      <iframe class="md-widget-fullscreen-frame" sandbox="allow-scripts" referrerpolicy="no-referrer"></iframe>
    </div>
  `;
  const frame = backdrop.querySelector(".md-widget-fullscreen-frame");
  frame.srcdoc = buildSandboxedWidgetDoc(rawCode, `${widgetId}-full`);

  const closeModal = () => backdrop.remove();
  backdrop.querySelector('[data-action="close"]').addEventListener("click", closeModal);
  backdrop.addEventListener("click", (ev) => {
    if (ev.target === backdrop) closeModal();
  });
  document.body.appendChild(backdrop);
}

function hydrateHtmlWidgets(container) {
  if (!container) return;
  container.querySelectorAll(".md-html-widget[data-widget-id]").forEach((card) => {
    if (card.dataset.hydrated === "1") return;
    card.dataset.hydrated = "1";
    const widgetId = card.dataset.widgetId;
    const rawCode = htmlWidgetCodeStore.get(widgetId) || "";
    const iframe = card.querySelector(".md-widget-frame");
    const previewWrap = card.querySelector(".md-widget-preview");
    const codeWrap = card.querySelector(".md-widget-code");
    const tabBtns = card.querySelectorAll(".md-widget-tab");
    const copyBtn = card.querySelector('[data-action="copy"]');
    const expandBtn = card.querySelector('[data-action="fullscreen"]');

      const contentWrap = card.closest(".message-content");
      if (contentWrap) contentWrap.classList.add("has-html-widget");
      iframe.srcdoc = buildSandboxedWidgetDoc(rawCode, widgetId);

    tabBtns.forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.dataset.mode;
        tabBtns.forEach((b) => b.classList.toggle("is-active", b === btn));
        if (previewWrap) previewWrap.hidden = mode !== "preview";
        if (codeWrap) codeWrap.hidden = mode !== "code";
      });
    });

    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        try {
          await navigator.clipboard.writeText(rawCode);
          copyBtn.textContent = "已复制";
          setTimeout(() => { copyBtn.textContent = "复制"; }, 1500);
        } catch {
          copyBtn.textContent = "复制失败";
          setTimeout(() => { copyBtn.textContent = "复制"; }, 1500);
        }
      });
    }

    if (expandBtn) {
      expandBtn.addEventListener("click", () => openWidgetFullscreenModal(widgetId));
    }
  });
}

window.addEventListener("message", (event) => {
  const data = event.data;
  if (!data || data.type !== "lark-widget-height" || !data.id) return;
  const frame = document.querySelector(`.md-html-widget[data-widget-id="${CSS.escape(data.id)}"] .md-widget-frame`);
  if (!frame) return;
  const nextHeight = Math.max(220, Math.min(620, Number(data.height || 0) + 12));
  frame.style.height = `${nextHeight}px`;
});

function renderMarkdown(raw, { streaming = false } = {}) {
  if (!raw) return "";
  const normalized = String(raw).replace(/\r\n?/g, "\n");
  const codeBlocks = [];
  const withPlaceholders = normalized.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (_, lang, code) => {
    const idx = codeBlocks.length;
    const cleanCode = code.replace(/\n$/, "");
    if (!streaming && isRenderableHtmlBlock(lang, cleanCode)) {
      const widgetId = `lark-widget-${++htmlWidgetSeq}`;
      htmlWidgetCodeStore.set(widgetId, cleanCode);
      codeBlocks.push(
        `<div class="md-html-widget" data-widget-id="${widgetId}">
          <div class="md-widget-bar">
            <span class="md-widget-title">交互式组件</span>
            <div class="md-widget-actions">
              <button type="button" class="md-widget-btn md-widget-tab is-active" data-mode="preview">预览</button>
              <button type="button" class="md-widget-btn md-widget-tab" data-mode="code">源码</button>
              <button type="button" class="md-widget-btn" data-action="copy">复制</button>
              <button type="button" class="md-widget-btn" data-action="fullscreen">放大</button>
            </div>
          </div>
          <div class="md-widget-preview">
            <iframe class="md-widget-frame" sandbox="allow-scripts" referrerpolicy="no-referrer" title="交互式组件预览"></iframe>
          </div>
          <div class="md-widget-code" hidden>
            <pre><code>${escapeHtml(cleanCode)}</code></pre>
          </div>
        </div>`
      );
    } else {
      const langAttr = lang ? ` data-lang="${escapeHtml(lang)}"` : "";
      codeBlocks.push(`<pre${langAttr}><code>${escapeHtml(cleanCode)}</code></pre>`);
    }
    return `\n\u0000CB${idx}\u0000\n`;
  });

  const lines = withPlaceholders.split("\n");
  const out = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (!trimmed) {
      i++;
      continue;
    }

    const cbMatch = trimmed.match(/^\u0000CB(\d+)\u0000$/);
    if (cbMatch) {
      out.push(codeBlocks[Number(cbMatch[1])] || "");
      i++;
      continue;
    }

    if (/^(?:-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      out.push("<hr>");
      i++;
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      out.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      i++;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ""));
        i++;
      }
      out.push(`<blockquote>${quoteLines.map((l) => renderInlineMarkdown(l)).join("<br>")}</blockquote>`);
      continue;
    }

    // 表格：当前行含 | 且下一行为分隔行 | --- | --- |
    if (
      trimmed.includes("|") &&
      i + 1 < lines.length &&
      /^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$/.test(lines[i + 1])
    ) {
      const splitRow = (row) =>
        row
          .trim()
          .replace(/^\|/, "")
          .replace(/\|$/, "")
          .split("|")
          .map((cell) => cell.trim());
      const headers = splitRow(line);
      i += 2;
      const bodyRows = [];
      while (i < lines.length && lines[i].trim().includes("|") && lines[i].trim() !== "") {
        bodyRows.push(splitRow(lines[i]));
        i++;
      }
      const thead = `<thead><tr>${headers.map((h) => `<th>${renderInlineMarkdown(h)}</th>`).join("")}</tr></thead>`;
      const tbody = bodyRows.length
        ? `<tbody>${bodyRows
            .map((row) => `<tr>${headers.map((_, idx) => `<td>${renderInlineMarkdown(row[idx] || "")}</td>`).join("")}</tr>`)
            .join("")}</tbody>`
        : "";
      out.push(`<div class="md-table-wrap"><table>${thead}${tbody}</table></div>`);
      continue;
    }

    // 无序列表 / 有序列表
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(`<li>${renderInlineMarkdown(lines[i].replace(/^\s*[-*+]\s+/, ""))}</li>`);
        i++;
      }
      out.push(`<ul>${items.join("")}</ul>`);
      continue;
    }

    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(`<li>${renderInlineMarkdown(lines[i].replace(/^\s*\d+\.\s+/, ""))}</li>`);
        i++;
      }
      out.push(`<ol>${items.join("")}</ol>`);
      continue;
    }

    // 普通段落
    const paraLines = [];
    while (i < lines.length) {
      const cur = lines[i];
      const curTrim = cur.trim();
      if (
        !curTrim ||
        /^\u0000CB\d+\u0000$/.test(curTrim) ||
        /^(?:-{3,}|\*{3,}|_{3,})$/.test(curTrim) ||
        /^#{1,6}\s+/.test(curTrim) ||
        curTrim.startsWith(">") ||
        /^\s*[-*+]\s+/.test(cur) ||
        /^\s*\d+\.\s+/.test(cur)
      ) {
        break;
      }
      paraLines.push(renderInlineMarkdown(cur));
      i++;
    }
    if (paraLines.length) {
      out.push(`<p>${paraLines.join("<br>")}</p>`);
    }
  }

  return out.join("");
}

function showToastMessage(msg) {
  const el = document.getElementById("companionToast");
  if (el) {
    el.textContent = msg;
    el.hidden = false;
    setTimeout(() => { el.hidden = true; }, 3500);
  }
}

function formatMarkdownAdvice(text) {
  if (!text) return "";
  const lines = text.split("\n");
  const html = [];
  for (let line of lines) {
    const escaped = escapeHtml(line);
    if (escaped.startsWith("### ")) {
      html.push(`<h4 style="margin:12px 0 6px;color:#2b4564;font-size:0.95rem;">${escaped.slice(4)}</h4>`);
    } else if (escaped.startsWith("## ")) {
      html.push(`<h3 style="margin:16px 0 8px;color:#243950;font-size:1.02rem;">${escaped.slice(3)}</h3>`);
    } else if (escaped.startsWith("# ")) {
      html.push(`<h2 style="margin:18px 0 10px;color:#1c2d40;font-size:1.1rem;">${escaped.slice(2)}</h2>`);
    } else if (escaped.startsWith("- ") || escaped.startsWith("* ")) {
      const bolded = escaped.slice(2).replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      html.push(`<li style="margin-left:18px;margin-bottom:4px;">${bolded}</li>`);
    } else if (escaped.trim().length > 0) {
      const bolded = escaped.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
      html.push(`<p style="margin:6px 0;line-height:1.65;">${bolded}</p>`);
    } else {
      html.push(`<div style="height:6px;"></div>`);
    }
  }
  return html.join("");
}

let currentAcademicStage = "high_school";

function setAcademicStage(stage) {
  currentAcademicStage = stage;
  const picker = document.getElementById("academicStagePicker");
  if (picker) {
    picker.querySelectorAll("button").forEach(btn => {
      const active = btn.dataset.stage === stage;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }
  const hs = document.getElementById("highSchoolForm");
  const ug = document.getElementById("undergraduateForm");
  const gen = document.getElementById("generalForm");
  if (hs) hs.hidden = stage !== "high_school";
  if (ug) ug.hidden = stage !== "undergraduate";
  if (gen) gen.hidden = stage !== "general";
}

function getAcademicFormData() {
  const data = {
    stage: currentAcademicStage,
    grade: "",
    sub_category: "",
    province: "",
    current_school: "",
    target_school: "",
    target_goal: "",
    current_score_or_gpa: "",
    rank_info: "",
    extra_profile: {},
  };

  if (currentAcademicStage === "high_school") {
    data.grade = document.getElementById("hsGrade")?.value || "高三";
    data.province = document.getElementById("hsProvince")?.value.trim() || "";
    data.sub_category = document.getElementById("hsSubCategory")?.value.trim() || "";
    data.target_school = document.getElementById("hsTargetSchool")?.value.trim() || "";
    data.target_goal = document.getElementById("hsTargetGoal")?.value.trim() || "";
    data.current_score_or_gpa = document.getElementById("hsCurrentScore")?.value.trim() || "";
    data.rank_info = document.getElementById("hsRankInfo")?.value.trim() || "";
    data.extra_profile = {
      weak_subjects: document.getElementById("hsWeakSubjects")?.value.trim() || "",
    };
  } else if (currentAcademicStage === "undergraduate") {
    data.grade = document.getElementById("ugGrade")?.value || "大三";
    data.current_school = document.getElementById("ugCurrentSchool")?.value.trim() || "";
    data.sub_category = document.getElementById("ugSubCategory")?.value.trim() || "";
    data.target_goal = document.getElementById("ugTargetGoal")?.value.trim() || "";
    data.target_school = document.getElementById("ugTargetSchool")?.value.trim() || "";
    data.current_score_or_gpa = document.getElementById("ugCurrentGpa")?.value.trim() || "";
    data.rank_info = document.getElementById("ugRankInfo")?.value.trim() || "";
    data.extra_profile = {
      english: document.getElementById("ugEnglish")?.value.trim() || "",
      research: document.getElementById("ugResearch")?.value.trim() || "",
      competitions: document.getElementById("ugCompetitions")?.value.trim() || "",
    };
  } else {
    data.sub_category = document.getElementById("genSubCategory")?.value.trim() || "";
    data.current_score_or_gpa = document.getElementById("genCurrentScore")?.value.trim() || "";
    data.target_goal = document.getElementById("genTargetGoal")?.value.trim() || "";
  }
  return data;
}

function fillAcademicForm(profile) {
  if (!profile) return;
  const stage = profile.stage || "high_school";
  setAcademicStage(stage);
  const extra = profile.extra_profile || {};

  if (stage === "high_school") {
    if (document.getElementById("hsGrade")) document.getElementById("hsGrade").value = profile.grade || "高三";
    if (document.getElementById("hsProvince")) document.getElementById("hsProvince").value = profile.province || "";
    if (document.getElementById("hsSubCategory")) document.getElementById("hsSubCategory").value = profile.sub_category || "";
    if (document.getElementById("hsTargetSchool")) document.getElementById("hsTargetSchool").value = profile.target_school || "";
    if (document.getElementById("hsTargetGoal")) document.getElementById("hsTargetGoal").value = profile.target_goal || "";
    if (document.getElementById("hsCurrentScore")) document.getElementById("hsCurrentScore").value = profile.current_score_or_gpa || "";
    if (document.getElementById("hsRankInfo")) document.getElementById("hsRankInfo").value = profile.rank_info || "";
    if (document.getElementById("hsWeakSubjects")) document.getElementById("hsWeakSubjects").value = extra.weak_subjects || "";
  } else if (stage === "undergraduate") {
    if (document.getElementById("ugGrade")) document.getElementById("ugGrade").value = profile.grade || "大三";
    if (document.getElementById("ugCurrentSchool")) document.getElementById("ugCurrentSchool").value = profile.current_school || "";
    if (document.getElementById("ugSubCategory")) document.getElementById("ugSubCategory").value = profile.sub_category || "";
    if (document.getElementById("ugTargetGoal")) document.getElementById("ugTargetGoal").value = profile.target_goal || "";
    if (document.getElementById("ugTargetSchool")) document.getElementById("ugTargetSchool").value = profile.target_school || "";
    if (document.getElementById("ugCurrentGpa")) document.getElementById("ugCurrentGpa").value = profile.current_score_or_gpa || "";
    if (document.getElementById("ugRankInfo")) document.getElementById("ugRankInfo").value = profile.rank_info || "";
    if (document.getElementById("ugEnglish")) document.getElementById("ugEnglish").value = extra.english || "";
    if (document.getElementById("ugResearch")) document.getElementById("ugResearch").value = extra.research || "";
    if (document.getElementById("ugCompetitions")) document.getElementById("ugCompetitions").value = extra.competitions || "";
  } else {
    if (document.getElementById("genSubCategory")) document.getElementById("genSubCategory").value = profile.sub_category || "";
    if (document.getElementById("genCurrentScore")) document.getElementById("genCurrentScore").value = profile.current_score_or_gpa || "";
    if (document.getElementById("genTargetGoal")) document.getElementById("genTargetGoal").value = profile.target_goal || "";
  }

  // 同步更新独立学业成长模块概览卡片
  const badge = document.getElementById("growthStageBadge");
  const title = document.getElementById("growthTargetTitle");
  const subInfo = document.getElementById("growthSubInfo");
  const scoreDisplay = document.getElementById("growthCurrentScoreDisplay");
  const rankDisplay = document.getElementById("growthRankDisplay");

  if (badge) {
    badge.textContent = stage === "high_school" ? `高中 · ${profile.grade || "高三"}` : (stage === "undergraduate" ? `大学 · ${profile.grade || "大三"}` : "成长进阶");
  }
  if (title) {
    title.textContent = profile.target_school ? `目标：${profile.target_school}` : "目标院校：尚未设定";
  }
  if (subInfo) {
    const parts = [];
    if (profile.sub_category) parts.push(`方向/选科：${profile.sub_category}`);
    if (profile.target_goal) parts.push(`追求：${profile.target_goal}`);
    subInfo.textContent = parts.join(" ｜ ") || "尚未完善详细目标";
  }
  if (scoreDisplay) {
    scoreDisplay.textContent = profile.current_score_or_gpa || "-";
  }
  if (rankDisplay) {
    rankDisplay.textContent = profile.rank_info || "-";
  }

  renderAcademicAdviceCard(profile.latest_advice, profile.advice_updated_at);
}

function renderAcademicAdviceCard(adviceText, updatedAt) {
  const card = document.getElementById("academicAdviceCard");
  const content = document.getElementById("academicAdviceContent");
  const time = document.getElementById("adviceUpdateTime");
  if (!card || !content) return;
  if (!adviceText || !adviceText.trim()) {
    content.innerHTML = '<p class="score-empty-tip">点击右上角“生成 / 刷新规划建议”，云雀将结合你的目标与真实成绩为你生成专属规划报告。</p>';
    if (time) time.textContent = "";
    return;
  }
  content.innerHTML = formatMarkdownAdvice(adviceText);
  if (time && updatedAt) {
    time.textContent = `更新于 ${updatedAt.slice(0, 16)}`;
  }
}

async function fetchAcademicProfile() {
  try {
    const res = await requestJson("/api/academic/profile");
    if (res && res.profile) {
      fillAcademicForm(res.profile);
    }
  } catch (err) {
    console.error("fetchAcademicProfile failed:", err);
  }
  fetchAcademicScores();
}

async function saveAcademicProfile(showToast = true) {
  const statusEl = document.getElementById("academicProfileStatus");
  const btn = document.getElementById("saveAcademicProfileButton");
  if (statusEl) {
    statusEl.textContent = "正在保存...";
    statusEl.className = "profile-save-status";
  }
  if (btn) btn.disabled = true;

  try {
    const payload = getAcademicFormData();
    const res = await requestJson("/api/academic/profile", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (res && res.profile) {
      fillAcademicForm(res.profile);
      if (statusEl) {
        statusEl.textContent = "基本信息已保存";
        statusEl.className = "profile-save-status is-success";
        setTimeout(() => { statusEl.textContent = ""; }, 3000);
      }
      if (showToast) {
        showToastMessage("个人基本信息已保存");
      }
      return res.profile;
    }
  } catch (err) {
    if (statusEl) {
      statusEl.textContent = "保存失败";
      statusEl.className = "profile-save-status is-error";
    }
  } finally {
    if (btn) btn.disabled = false;
  }
  return null;
}

async function generateAcademicAdviceAction() {
  const btn = document.getElementById("growthGenerateAdviceBtn");
  const origText = btn ? btn.textContent : "";
  if (btn) {
    btn.disabled = true;
    btn.textContent = "云雀正在推演规划建议...";
  }
  try {
    const payload = getAcademicFormData();
    await saveAcademicProfile(false);
    const res = await requestJson("/api/academic/advice", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (res && res.advice) {
      renderAcademicAdviceCard(res.advice, res.profile?.advice_updated_at || chinaDateKey());
      showToastMessage("云雀已为你生成专属学业成长规划建议！");
    } else {
      showToastMessage(res?.error || "生成建议遇到问题，请稍后重试");
    }
  } catch (err) {
    showToastMessage("生成失败: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = origText;
    }
  }
}

async function fetchAcademicScores() {
  const listEl = document.getElementById("scoreRecordsList");
  if (!listEl) return;
  try {
    const res = await requestJson("/api/academic/scores");
    const scores = res?.scores || [];
    if (!scores.length) {
      listEl.innerHTML = '<div class="score-empty-tip">暂无历史成绩记录，点击上方添加记录。</div>';
      return;
    }
    listEl.innerHTML = scores.map(item => {
      const rankText = item.rank_num ? `排名 ${item.rank_num}${item.rank_total ? ` / ${item.rank_total}` : ""}` : "";
      return `
        <div class="score-item">
          <div class="score-item-left">
            <div>
              <strong>${escapeHtml(item.title)}</strong>
              <span class="score-item-tag">${escapeHtml(item.exam_date || "")}</span>
            </div>
            ${item.notes ? `<div class="score-item-notes">${escapeHtml(item.notes)}</div>` : ""}
          </div>
          <div class="score-item-right">
            <div class="score-val">${item.total_score}</div>
            ${rankText ? `<div class="score-rank">${rankText}</div>` : ""}
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    console.error("fetchAcademicScores error:", err);
  }
}

async function saveAcademicScoreAction(event) {
  event.preventDefault();
  const title = document.getElementById("scoreExamTitle")?.value.trim();
  const examDate = document.getElementById("scoreExamDate")?.value;
  const totalVal = parseFloat(document.getElementById("scoreTotalVal")?.value || "0");
  const rankNum = parseInt(document.getElementById("scoreRankNum")?.value || "0", 10) || 0;
  const rankTotal = parseInt(document.getElementById("scoreRankTotal")?.value || "0", 10) || 0;
  const notes = document.getElementById("scoreNotes")?.value.trim() || "";

  if (!title || !examDate) return;

  try {
    await requestJson("/api/academic/scores", {
      method: "POST",
      body: JSON.stringify({
        title,
        exam_date: examDate,
        stage: currentAcademicStage,
        total_score: totalVal,
        rank_num: rankNum,
        rank_total: rankTotal,
        notes,
      }),
    });
    showToastMessage("成绩记录已添加");
    document.getElementById("scoreQuickForm")?.reset();
    document.getElementById("scoreQuickForm").hidden = true;
    fetchAcademicScores();
  } catch (err) {
    showToastMessage("添加失败: " + err.message);
  }
}

// --- 交互联动卡片 (Action Cards) ---
function appendChatActionCard({ title, desc, actions = [], link = null, type = "" }) {
  const card = document.createElement("div");
  card.className = "chat-action-card";
  if (type) card.dataset.cardType = type;
  let html = `<div><strong>${title}</strong>：${desc}</div>`;
  if (link) {
    html += `<div><a class="study-jump-link" href="javascript:void(0)" onclick="${link.onclick}">${link.text}</a></div>`;
  }
  if (actions && actions.length) {
    html += `<div class="chat-action-buttons">` +
      actions.map(act => `<button type="button" class="chat-action-btn ${act.class || ''}" data-act="${act.action}" ${act.dataAttrs || ''}>${act.text}</button>`).join("") +
      `</div>`;
  }
  card.innerHTML = html;
  els.chatList.appendChild(card);
  els.chatList.scrollTop = els.chatList.scrollHeight;
}

els.chatList.addEventListener("click", async (e) => {
  const btn = e.target.closest(".chat-action-btn");
  if (!btn) return;
  const act = btn.dataset.act;
  if (act === "confirm-study") {
    const subject = btn.dataset.subject || "通用学科";
    const title = btn.dataset.title || `${subject}专项学习`;
    const promptSeed = btn.dataset.prompt || "";
    try {
      btn.disabled = true;
      btn.textContent = "正在开启自习室...";
      const res = await requestJson("/api/study/sessions", {
        method: "POST",
        body: JSON.stringify({ subject, title, prompt_seed: promptSeed }),
      });
      if (res.ok && res.session) {
        appendChatActionCard({
          title: "学习自习室已就绪",
          desc: `已成功为你开启【${title}】！`,
          link: {
            text: "👉 点击立即前往「开始学习！」页面",
            onclick: `window.openStudySession('${res.session.id}')`
          }
        });
        window.openStudySession(res.session.id);
      }
    } catch (err) {
      alert("创建学习会话失败: " + err.message);
      btn.disabled = false;
      btn.textContent = "重试开启学习";
    }
  } else if (act === "cancel-study") {
    const card = btn.closest(".chat-action-card");
    if (card) {
      card.innerHTML = `<span style="color:var(--muted);font-size:12px;">已取消本次自习室跳转，继续在这里聊天。</span>`;
    }
  } else if (act === "generate-plan") {
    const card = btn.closest(".chat-action-card");
    if (card) card.remove();
    sendChat("请结合我的学业档案与目标，为我生成一份详细的专属学业成长规划。");
  } else if (act === "dismiss-action") {
    const card = btn.closest(".chat-action-card");
    if (card) card.remove();
  }
});

// 检查画像首次问询 (Profile Switch Greeting)
async function checkProfileGreeting() {
  try {
    const payload = activeProfile?.id ? { profile_id: activeProfile.id } : {};
    const res = await requestJson("/api/profiles/greeting", { method: "POST", body: JSON.stringify(payload) });
    if (res.ok && res.greeting && !res.already_chatted) {
      const alreadyHasGreeting = state.history.some(m => m.content === res.greeting) ||
                                 Array.from(els.chatList.querySelectorAll(".bubble")).some(b => b.textContent.includes("还没有为这个画像制定过专属的成长与学业规划"));
      if (!alreadyHasGreeting) {
        appendMessage("assistant", res.greeting);
      }
      if (!els.chatList.querySelector(".chat-action-card[data-card-type='plan-wizard']")) {
        appendChatActionCard({
          type: "plan-wizard",
          title: "学业与成长规划向导",
          desc: "检测到新画像尚未制定专属规划，是否由云雀现在为你生成一份深度规划报告？",
          actions: [
            { text: "✨ 立即生成学业规划", action: "generate-plan", class: "primary" },
            { text: "稍后再说", action: "dismiss-action", class: "secondary" }
          ]
        });
      }
    }
  } catch (err) {
    console.warn("checkProfileGreeting error:", err);
  }
}

// --- 多画像 (Profile) 管理 ---
let userProfiles = [];
let activeProfile = null;

const STAGE_CONFIGS = {
  high_school: {
    badgeText: "高中阶段专属",
    showProvince: true,
    gradeLabel: "当前年级",
    gradePlaceholder: "例如：高一 / 高二 / 高三",
    subCategoryLabel: "选科组合",
    subCategoryPlaceholder: "例如：物化生 / 物化地 / 史政地",
    provinceLabel: "高考省份 / 考区",
    provincePlaceholder: "例如：江苏 / 浙江 / 山东 / 广东",
    currentSchoolLabel: "当前就读高中",
    currentSchoolPlaceholder: "例如：某省重点高中 / 某实验高中",
    targetSchoolLabel: "目标高校 / 平台",
    targetSchoolPlaceholder: "例如：清华大学 / 浙江大学 / 985高校",
    targetGoalLabel: "目标追求 / 愿景",
    targetGoalPlaceholder: "例如：高考冲刺650分 / 稳上一本线",
    scoreLabel: "近期模考成绩 (总分)",
    scorePlaceholder: "例如：模考615分 / 上期统考580分",
    rankLabel: "全校 / 考区排名",
    rankPlaceholder: "例如：年级前50名 / 全省前3000名",
    extraLabel: "薄弱科目与攻坚重点",
    extraPlaceholder: "例如：数学导数与物理电磁弱；立体几何失分较多，需要针对性攻坚。"
  },
  undergraduate: {
    badgeText: "大学本科专属",
    showProvince: false,
    gradeLabel: "当前年级",
    gradePlaceholder: "例如：大一 / 大二 / 大三 / 大四",
    subCategoryLabel: "就读专业",
    subCategoryPlaceholder: "例如：计算机科学与技术 / 临床医学 / 金融学",
    provinceLabel: "",
    provincePlaceholder: "",
    currentSchoolLabel: "本科就读院校",
    currentSchoolPlaceholder: "例如：某211高校 / 某985大学",
    targetSchoolLabel: "目标高校 / 发展方向",
    targetSchoolPlaceholder: "例如：本校保研 / 浙大考研 / 境外名校",
    targetGoalLabel: "目标追求 / 愿景",
    targetGoalPlaceholder: "例如：稳保前5%推免 / 冲刺408考研385分",
    scoreLabel: "当前学分绩点 / GPA (均分)",
    scorePlaceholder: "例如：GPA 3.86 (89.5分) / 满绩4.0",
    rankLabel: "专业排名 / 推免位次",
    rankPlaceholder: "例如：3/120 (Top 2.5%) / 综测年级第二",
    extraLabel: "科研竞赛与综合经历",
    extraPlaceholder: "例如：有CCF-A论文在投、国家级大创一项、英语六级585分。"
  },
  growth: {
    badgeText: "职场与自主进修专属",
    showProvince: false,
    gradeLabel: "当前职级 / 年资",
    gradePlaceholder: "例如：在职2年 / 资深工程师 / 跨考转型中",
    subCategoryLabel: "专业方向 / 业务领域",
    subCategoryPlaceholder: "例如：全栈开发 / 注册会计师CPA / PMP项目管理",
    provinceLabel: "",
    provincePlaceholder: "",
    currentSchoolLabel: "所在单位 / 行业机构",
    currentSchoolPlaceholder: "例如：某互联网科技公司 / 金融证券 / 自由职业",
    targetSchoolLabel: "进修目标 / 证书方向",
    targetSchoolPlaceholder: "例如：考取CPA专业阶段 / 冲刺架构师认证 / 在职MPA",
    targetGoalLabel: "进修目标 / 愿景",
    targetGoalPlaceholder: "例如：半年内掌握分布式高并发 / 拿下一级建造师",
    scoreLabel: "当前水平 / 测验成绩",
    scorePlaceholder: "例如：模拟测试82分 / 雅思7.0 / 已通过2门科目",
    rankLabel: "学习进度 / 指标",
    rankPlaceholder: "例如：课程进度80% / 刷题200道",
    extraLabel: "进修规划与工学痛点",
    extraPlaceholder: "例如：工作较忙需夜间固定1小时专注自习；算法基础薄弱需循序渐进。"
  }
};

function applyStageToProfileForm(prefix, stage) {
  const safeStage = STAGE_CONFIGS[stage] ? stage : "high_school";
  const cfg = STAGE_CONFIGS[safeStage];

  // 1. 同步隐藏的 select
  const selectEl = document.getElementById(`${prefix}ProfileStage`);
  if (selectEl) selectEl.value = safeStage;

  // 2. 更新分段选择按钮的高亮与无障碍属性
  const container = document.getElementById(`${prefix}StageSegmented`);
  if (container) {
    container.querySelectorAll(".stage-segment-btn").forEach((btn) => {
      const active = btn.dataset.stage === safeStage;
      btn.classList.toggle("is-active", active);
      btn.setAttribute("aria-pressed", active ? "true" : "false");
    });
  }

  // 3. 更新专属阶段徽标
  const badgeEl = document.getElementById(`${prefix}StageBadge`);
  if (badgeEl) badgeEl.textContent = cfg.badgeText;

  // 4. 显示 / 隐藏高考省份（高中阶段显示，大学及职场隐藏）
  const provItem = document.getElementById(`${prefix}ItemProvince`);
  if (provItem) {
    provItem.style.display = cfg.showProvince ? "" : "none";
  }

  // 5. 动态更新各表单项标签与占位符
  const updateField = (idSuffix, labelText, placeholderText) => {
    const lbl = document.getElementById(`${prefix}Label${idSuffix}`);
    const inp = document.getElementById(`${prefix}Profile${idSuffix}`);
    if (lbl && labelText !== undefined) lbl.textContent = labelText;
    if (inp && placeholderText !== undefined) inp.placeholder = placeholderText;
  };

  updateField("Grade", cfg.gradeLabel, cfg.gradePlaceholder);
  updateField("SubCategory", cfg.subCategoryLabel, cfg.subCategoryPlaceholder);
  updateField("Province", cfg.provinceLabel, cfg.provincePlaceholder);
  updateField("CurrentSchool", cfg.currentSchoolLabel, cfg.currentSchoolPlaceholder);
  updateField("TargetSchool", cfg.targetSchoolLabel, cfg.targetSchoolPlaceholder);
  updateField("TargetGoal", cfg.targetGoalLabel, cfg.targetGoalPlaceholder);
  updateField("Score", cfg.scoreLabel, cfg.scorePlaceholder);
  updateField("Rank", cfg.rankLabel, cfg.rankPlaceholder);
  updateField("Extra", cfg.extraLabel, cfg.extraPlaceholder);
}

function initStageSegmentedBars() {
  const setupBar = (prefix) => {
    const container = document.getElementById(`${prefix}StageSegmented`);
    if (!container) return;
    container.querySelectorAll(".stage-segment-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const stage = btn.dataset.stage;
        if (stage) {
          applyStageToProfileForm(prefix, stage);
        }
      });
    });
  };
  setupBar("edit");
  setupBar("new");
  applyStageToProfileForm("edit", activeProfile?.stage || "high_school");
  applyStageToProfileForm("new", "high_school");
}

async function loadProfiles() {
  try {
    const res = await requestJson("/api/profiles");
    if (!res.ok) return;
    userProfiles = res.profiles || [];
    activeProfile = res.active_profile || userProfiles[0] || null;
    renderProfileCards();
    fillActiveProfileForm();
  } catch (err) {
    console.error("loadProfiles error:", err);
  }
}

function renderProfileCards() {
  if (!els.profileCardsGrid) return;
  els.profileCardsGrid.innerHTML = "";
  if (!userProfiles.length) {
    els.profileCardsGrid.innerHTML = '<div style="color:var(--muted);">暂无画像，点击右上角新建画像</div>';
    return;
  }
  const stageMap = { high_school: "高中", undergraduate: "大学本科", growth: "职场进修" };
  userProfiles.forEach(p => {
    const isActive = activeProfile && activeProfile.id === p.id;
    const card = document.createElement("div");
    card.className = `profile-card-item ${isActive ? "is-active" : ""}`;
    const scoreTitle = p.stage === 'high_school' ? '模考成绩' : (p.stage === 'undergraduate' ? '当前GPA' : '当前水平');
    card.innerHTML = `
      <div class="profile-card-header">
        <strong class="profile-card-title">${escapeHtml(p.profile_name || '未命名画像')}</strong>
        ${isActive ? '<span class="active-tag">当前生效</span>' : `<button class="button button-sm" type="button" data-switch-id="${p.id}">设为生效</button>`}
      </div>
      <div class="profile-card-meta">
        <div>学业阶段：<b>${stageMap[p.stage] || p.stage || '未指定'}</b> ${p.grade ? `(${escapeHtml(p.grade)})` : ''}</div>
        <div>目标追求：${escapeHtml(p.target_goal || p.target_school || '未设定')}</div>
        <div>${scoreTitle}：${escapeHtml(p.current_score_or_gpa || '-')}</div>
      </div>
    `;
    card.onclick = (e) => {
      if (e.target.closest("[data-switch-id]")) {
        switchActiveProfile(p.id);
      } else if (!isActive) {
        switchActiveProfile(p.id);
      }
    };
    els.profileCardsGrid.appendChild(card);
  });
}

function fillActiveProfileForm() {
  if (!activeProfile) return;
  if (els.currentActiveProfileBadge) {
    els.currentActiveProfileBadge.textContent = `${activeProfile.profile_name || '当前画像'} (生效中)`;
  }
  const stage = activeProfile.stage || "high_school";
  if (els.editProfileStage) els.editProfileStage.value = stage;
  applyStageToProfileForm("edit", stage);

  if (els.editProfileName) els.editProfileName.value = activeProfile.profile_name || "";
  if (els.editProfileGrade) els.editProfileGrade.value = activeProfile.grade || "";
  if (els.editProfileSubCategory) els.editProfileSubCategory.value = activeProfile.sub_category || "";
  if (els.editProfileProvince) els.editProfileProvince.value = activeProfile.province || "";
  if (els.editProfileCurrentSchool) els.editProfileCurrentSchool.value = activeProfile.current_school || "";
  if (els.editProfileTargetSchool) els.editProfileTargetSchool.value = activeProfile.target_school || "";
  if (els.editProfileTargetGoal) els.editProfileTargetGoal.value = activeProfile.target_goal || "";
  if (els.editProfileScore) els.editProfileScore.value = activeProfile.current_score_or_gpa || "";
  if (els.editProfileRank) els.editProfileRank.value = activeProfile.rank_info || "";
  if (els.editProfileExtra) {
    const extra = activeProfile.extra_profile || {};
    els.editProfileExtra.value = extra.notes || extra.weak_subjects || extra.research || "";
  }
}

async function switchActiveProfile(profileId) {
  try {
    const res = await requestJson("/api/profiles/switch", {
      method: "POST",
      body: JSON.stringify({ profile_id: profileId }),
    });
    if (res.ok) {
      activeProfile = res.active_profile;
      userProfiles = res.profiles || userProfiles;
      renderProfileCards();
      fillActiveProfileForm();
      showToastMessage(`已切换为【${activeProfile.profile_name}】画像`);
      await loadChatHistory();
    }
  } catch (err) {
    alert("切换画像失败: " + err.message);
  }
}

async function saveActiveProfile() {
  const stage = (els.editProfileStage?.value || "").trim() || "high_school";
  const name = (els.editProfileName?.value || "").trim() || "默认画像";

  if (!activeProfile) {
    const payload = {
      stage,
      profile_name: name,
      grade: (els.editProfileGrade?.value || "").trim(),
      sub_category: (els.editProfileSubCategory?.value || "").trim(),
      province: stage === "high_school" ? (els.editProfileProvince?.value || "").trim() : "",
      current_school: (els.editProfileCurrentSchool?.value || "").trim(),
      target_school: (els.editProfileTargetSchool?.value || "").trim(),
      target_goal: (els.editProfileTargetGoal?.value || "").trim(),
      current_score_or_gpa: (els.editProfileScore?.value || "").trim(),
      rank_info: (els.editProfileRank?.value || "").trim(),
      extra_profile: { notes: (els.editProfileExtra?.value || "").trim() },
    };
    try {
      if (els.profileSaveStatus) els.profileSaveStatus.textContent = "保存中...";
      const res = await requestJson("/api/profiles", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        activeProfile = res.profile || res.active_profile;
        userProfiles = res.profiles || [activeProfile];
        renderProfileCards();
        fillActiveProfileForm();
        if (els.profileSaveStatus) els.profileSaveStatus.textContent = "✓ 已成功保存画像";
        setTimeout(() => { if (els.profileSaveStatus) els.profileSaveStatus.textContent = ""; }, 2500);
        showToastMessage("画像已成功保存");
      }
    } catch (err) {
      if (els.profileSaveStatus) els.profileSaveStatus.textContent = "保存失败: " + err.message;
      alert("保存失败: " + err.message);
    }
    return;
  }

  const payload = {
    profile_id: activeProfile.id,
    profile_name: name,
    stage,
    grade: (els.editProfileGrade?.value || "").trim(),
    sub_category: (els.editProfileSubCategory?.value || "").trim(),
    province: stage === "high_school" ? (els.editProfileProvince?.value || "").trim() : "",
    current_school: (els.editProfileCurrentSchool?.value || "").trim(),
    target_school: (els.editProfileTargetSchool?.value || "").trim(),
    target_goal: (els.editProfileTargetGoal?.value || "").trim(),
    current_score_or_gpa: (els.editProfileScore?.value || "").trim(),
    rank_info: (els.editProfileRank?.value || "").trim(),
    extra_profile: { notes: (els.editProfileExtra?.value || "").trim() },
  };
  try {
    if (els.profileSaveStatus) els.profileSaveStatus.textContent = "保存中...";
    const res = await requestJson("/api/profiles/update", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      activeProfile = res.active_profile;
      userProfiles = res.profiles || userProfiles;
      renderProfileCards();
      fillActiveProfileForm();
      if (els.profileSaveStatus) els.profileSaveStatus.textContent = "✓ 已成功保存";
      setTimeout(() => { if (els.profileSaveStatus) els.profileSaveStatus.textContent = ""; }, 2500);
      showToastMessage("画像修改已保存");
    }
  } catch (err) {
    if (els.profileSaveStatus) els.profileSaveStatus.textContent = "保存失败: " + err.message;
    alert("保存画像失败: " + err.message);
  }
}

async function deleteActiveProfile() {
  if (!activeProfile) return;
  if (userProfiles.length <= 1) {
    alert("至少保留一个画像，无法删除唯一的画像。");
    return;
  }
  if (!confirm(`确定要删除画像【${activeProfile.profile_name}】吗？`)) return;
  try {
    const res = await requestJson("/api/profiles/delete", {
      method: "POST",
      body: JSON.stringify({ profile_id: activeProfile.id }),
    });
    if (res.ok) {
      userProfiles = res.profiles || [];
      activeProfile = res.active_profile;
      renderProfileCards();
      fillActiveProfileForm();
      showToastMessage("画像已删除");
      await loadChatHistory();
    }
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

async function handleCreateProfileSubmit(e) {
  if (e) e.preventDefault();
  const stage = (els.newProfileStage?.value || "").trim() || "high_school";
  const name = (els.newProfileName?.value || "").trim();
  if (!name) {
    alert("请输入画像名称！");
    els.newProfileName?.focus();
    return;
  }
  const payload = {
    stage,
    profile_name: name,
    grade: (els.newProfileGrade?.value || "").trim(),
    sub_category: (els.newProfileSubCategory?.value || "").trim(),
    province: stage === "high_school" ? (els.newProfileProvince?.value || "").trim() : "",
    current_school: (els.newProfileCurrentSchool?.value || "").trim(),
    target_school: (els.newProfileTargetSchool?.value || "").trim(),
    target_goal: (els.newProfileTargetGoal?.value || "").trim(),
    current_score_or_gpa: (els.newProfileScore?.value || "").trim(),
    rank_info: (els.newProfileRank?.value || "").trim(),
  };
  try {
    const res = await requestJson("/api/profiles", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    if (res.ok) {
      if (els.newProfileModal) {
        els.newProfileModal.hidden = true;
        els.newProfileModal.setAttribute("hidden", "");
      }
      if (els.newProfileForm) els.newProfileForm.reset();
      userProfiles = res.profiles || userProfiles;
      activeProfile = res.profile || res.active_profile;
      renderProfileCards();
      fillActiveProfileForm();
      showToastMessage(`已成功创建画像【${name}】！`);
      await loadChatHistory();
    }
  } catch (err) {
    alert("创建画像失败: " + err.message);
  }
}

// --- 独立学习自习室 (Study View) ---
let currentStudySessionId = null;
let studySessionsList = [];
let studyWheelLocked = false;

function renderStudySessionWheel() {
  const wheelEl = document.getElementById("studySessionWheel");
  if (!wheelEl) return;
  wheelEl.innerHTML = "";
  if (!studySessionsList.length) return;

  let activeIdx = studySessionsList.findIndex((s) => s.id === currentStudySessionId);
  if (activeIdx < 0) activeIdx = 0;

  studySessionsList.forEach((sess, idx) => {
    const offset = idx - activeIdx;
    const absOffset = Math.abs(offset);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `study-wheel-item${offset === 0 ? " is-active" : ""}`;
    btn.setAttribute("role", "option");
    btn.setAttribute("aria-selected", offset === 0 ? "true" : "false");
    btn.dataset.sessionId = sess.id;

    // 轮盘弧线与纵深缩放变换（使用纯2D层级变换，避免3D rotateX导致Z<0半区无法响应鼠标点击）
    const translateY = offset * 76;
    const translateX = absOffset * -10;
    const scale = Math.max(0.72, 1 - absOffset * 0.1);
    const opacity = absOffset > 3 ? 0 : Math.max(0.22, 1 - absOffset * 0.25);

    btn.style.transform = `translateY(calc(-50% + ${translateY}px)) translateX(${translateX}px) scale(${scale})`;
    btn.style.opacity = String(opacity);
    btn.style.zIndex = String(10 - absOffset);
    btn.style.pointerEvents = absOffset > 3 ? "none" : "auto";

    btn.innerHTML = `
      <span class="wheel-item-subject">${escapeHtml(sess.subject || "自习")}</span>
      <span class="wheel-item-title">${escapeHtml(sess.title || "专注自习室")}</span>
    `;

    btn.addEventListener("click", () => {
      if (sess.id !== currentStudySessionId) {
        selectStudySession(sess.id, sess);
      }
    });

    wheelEl.appendChild(btn);
  });
}

async function loadStudySessions(targetSessionId = null) {
  try {
    const res = await requestJson("/api/study/sessions");
    if (!res.ok) return;
    const sessions = res.sessions || [];
    if (els.studySessionSelect) els.studySessionSelect.innerHTML = "";

    if (!sessions.length) {
      const created = await requestJson("/api/study/sessions", {
        method: "POST",
        body: JSON.stringify({ title: "自主自习探索", subject: "综合学科" }),
      });
      if (created.ok && created.session) {
        sessions.push(created.session);
      }
    }

    studySessionsList = sessions;

    sessions.forEach(sess => {
      const opt = document.createElement("option");
      opt.value = sess.id;
      opt.textContent = `【${sess.subject || '自习'}】${sess.title}`;
      if (els.studySessionSelect) els.studySessionSelect.appendChild(opt);
    });

    const activeId = targetSessionId || (sessions.some(s => s.id === currentStudySessionId) ? currentStudySessionId : (sessions[0] ? sessions[0].id : null));
    if (activeId) {
      if (els.studySessionSelect) els.studySessionSelect.value = activeId;
      selectStudySession(activeId, sessions.find(s => s.id === activeId));
    } else {
      renderStudySessionWheel();
    }
  } catch (err) {
    console.error("loadStudySessions error:", err);
  }
}

async function selectStudySession(sessionId, sessionObj = null) {
  currentStudySessionId = sessionId;
  const found = sessionObj || studySessionsList.find(s => s.id === sessionId);
  if (found) {
    if (els.currentStudySessionTitle) els.currentStudySessionTitle.textContent = found.title || "自习室";
    if (els.currentStudySubject) els.currentStudySubject.textContent = found.subject || "学科辅导";
  }
  if (els.studySessionSelect) els.studySessionSelect.value = sessionId;
  renderStudySessionWheel();
  await Promise.all([loadStudyMessages(sessionId), loadStudyFiles(sessionId)]);
}

let studyLibraryFiles = [];
let studyFilterLinkedOnly = false;

function formatFileTypeLabel(fileType, fileName = "") {
  const ft = String(fileType || "").toLowerCase();
  if (ft) return ft.toUpperCase();
  const ext = (String(fileName).split(".").pop() || "").toLowerCase();
  return ext ? ext.toUpperCase() : "FILE";
}

function renderTopicChipsHtml(topics = [], maxItems = 5) {
  const list = (Array.isArray(topics) ? topics : []).filter(Boolean).slice(0, maxItems);
  if (!list.length) return "";
  return `<div class="rag-topic-row">${list.map((t) => `<span class="rag-topic-chip"># ${escapeHtml(t)}</span>`).join("")}</div>`;
}

function renderStudyFilesList(files = studyLibraryFiles) {
  studyLibraryFiles = Array.isArray(files) ? files : [];
  const linkedFiles = studyLibraryFiles.filter((f) => f.linked);
  const countEl = document.getElementById("studyFilesCount");
  if (countEl) countEl.textContent = `${linkedFiles.length}/${studyLibraryFiles.length}`;
  const summaryEl = document.getElementById("studyFilesSummary");
  if (summaryEl) {
    summaryEl.textContent = linkedFiles.length
      ? `本自习室已关联 ${linkedFiles.length} 份资料（仅检索已关联资料，共 ${studyLibraryFiles.length} 份入库）`
      : `当前自习室未关联资料（勾选下方资料即可开启严格溯源问答与继续学习推荐）`;
  }

  const listEl = document.getElementById("studyFilesList");
  if (!listEl) return;
  listEl.innerHTML = "";
  const visible = studyFilterLinkedOnly ? linkedFiles : studyLibraryFiles;
  if (!visible.length) {
    listEl.innerHTML = studyFilterLinkedOnly
      ? '<span class="study-files-empty">本自习室还没有关联任何资料，取消“仅看已关联”可从资料库勾选，或点击右上角上传。</span>'
      : '<span class="study-files-empty">学习资料库暂无资料，上传 PDF / PPTX / Word / Markdown / 代码后将自动按类型切片并提取主题词。</span>';
    return;
  }

  visible.forEach((file) => {
    const row = document.createElement("div");
    row.className = `study-library-item${file.linked ? " is-linked" : ""}`;
    const kb = Math.max(1, Math.ceil(Number(file.file_size || 0) / 1024));
    const chunkInfo = file.chunk_count ? `${file.chunk_count} 切片` : (file.file_category === "image" ? "图片" : "媒体");
    const typeLabel = formatFileTypeLabel(file.file_type, file.file_name);
    row.innerHTML = `
      <label class="study-lib-check" title="勾选后，本自习室将读取该资料">
        <input type="checkbox" ${file.linked ? "checked" : ""} />
        <span class="study-lib-check-box">${file.linked ? "已关联" : "关联"}</span>
      </label>
      <div class="study-lib-main">
        <div class="study-lib-title-row">
          <span class="study-type-badge">${escapeHtml(typeLabel)}</span>
          <strong class="study-lib-name" title="${escapeHtml(file.file_name)}">${escapeHtml(file.file_name)}</strong>
          <small class="study-lib-meta">${kb} KB · ${chunkInfo}</small>
        </div>
        ${renderTopicChipsHtml(file.topics, 5)}
      </div>
      <div class="study-lib-actions">
        <button type="button" class="study-lib-btn btn-inspect-chunks" title="查看切片与主题词">切片</button>
        <button type="button" class="study-lib-btn is-danger btn-delete-lib" title="从学习资料库永久删除" aria-label="删除 ${escapeHtml(file.file_name)}">删除</button>
      </div>
    `;
    const checkbox = row.querySelector('input[type="checkbox"]');
    checkbox.addEventListener("change", () => toggleStudyFileLink(file.id, checkbox.checked));
    row.querySelector(".btn-inspect-chunks").addEventListener("click", () => openFileChunksModal(file));
    row.querySelector(".btn-delete-lib").addEventListener("click", () => deleteStudyLibraryFile(file.id, file.file_name));
    listEl.appendChild(row);
  });
}

async function loadStudyFiles(sessionId = currentStudySessionId) {
  if (!sessionId) return;
  try {
    const res = await requestJson(`/api/study/library?session_id=${encodeURIComponent(sessionId)}`);
    if (res.ok) renderStudyFilesList(res.files || []);
  } catch (err) {
    console.error("loadStudyFiles error:", err);
  }
}

async function toggleStudyFileLink(fileId, linked) {
  if (!currentStudySessionId || !fileId) return;
  try {
    const res = await requestJson("/api/study/session/links", {
      method: "POST",
      body: JSON.stringify({ session_id: currentStudySessionId, file_id: fileId, linked }),
    });
    if (res.ok) {
      renderStudyFilesList(res.files || []);
      showToastMessage(linked ? "已关联到当前自习室" : "已取消当前自习室关联");
    }
  } catch (err) {
    alert("更新资料关联失败: " + err.message);
    await loadStudyFiles(currentStudySessionId);
  }
}

async function uploadFilesToStudyLibrary(fileList) {
  const files = [...fileList].filter(isSupportedClientFile);
  if (!files.length) return;
  const payloadFiles = [];
  for (const file of files.slice(0, 9)) {
    if (file.size > 10 * 1024 * 1024) {
      window.alert(`${file.name} 超过 10 MB`);
      continue;
    }
    payloadFiles.push({
      name: file.name,
      type: inferClientMime(file),
      size: file.size,
      data: await blobToDataUrl(file),
    });
  }
  if (!payloadFiles.length) return;
  try {
    const res = await requestJson("/api/study/library", {
      method: "POST",
      body: JSON.stringify({ session_id: currentStudySessionId || "", attachments: payloadFiles }),
    });
    if (res.ok) {
      renderStudyFilesList(res.files || []);
      showToastMessage(`已入库并切片 ${payloadFiles.length} 份资料${currentStudySessionId ? "（已自动关联本自习室）" : ""}`);
    }
  } catch (err) {
    alert("上传资料失败: " + err.message);
  }
}

async function deleteStudyLibraryFile(fileId, fileName = "") {
  if (!fileId) return;
  if (!window.confirm(`确定从学习资料库永久删除「${fileName || "该资料"}」吗？所有自习室都将解除关联。`)) return;
  try {
    const res = await requestJson("/api/study/library/delete", {
      method: "POST",
      body: JSON.stringify({ session_id: currentStudySessionId || "", file_id: fileId }),
    });
    if (res.ok) {
      renderStudyFilesList(res.files || []);
      showToastMessage("已从学习资料库删除");
    }
  } catch (err) {
    alert("删除资料失败: " + err.message);
  }
}

const studyChunkModal = document.getElementById("studyChunkModal");
const studyChunkModalClose = document.getElementById("studyChunkModalClose");
if (studyChunkModalClose && studyChunkModal) {
  studyChunkModalClose.addEventListener("click", () => studyChunkModal.close());
  studyChunkModal.addEventListener("click", (ev) => {
    if (ev.target === studyChunkModal) studyChunkModal.close();
  });
}

function openChunkPreviewModal(chunk) {
  if (!studyChunkModal || !chunk) return;
  const titleEl = document.getElementById("studyChunkModalTitle");
  const subEl = document.getElementById("studyChunkModalSub");
  const bodyEl = document.getElementById("studyChunkModalBody");
  const docName = chunk.doc_name || chunk.file_name || "学习资料";
  const loc = chunk.location || `片段 ${(chunk.chunk_index || 0) + 1}`;
  if (titleEl) titleEl.textContent = `${docName} · ${loc}`;
  if (subEl) subEl.textContent = chunk.section_title || "";
  if (bodyEl) {
    bodyEl.innerHTML = `
      ${renderTopicChipsHtml(chunk.topics, 8)}
      <pre class="study-chunk-fulltext">${escapeHtml(chunk.content || chunk.snippet || "")}</pre>
      <div class="study-chunk-modal-actions">
        <button type="button" class="button button-primary" id="studyChunkAskBtn">学习 / 追问此切片</button>
      </div>
    `;
    const askBtn = bodyEl.querySelector("#studyChunkAskBtn");
    if (askBtn) {
      askBtn.addEventListener("click", () => {
        studyChunkModal.close();
        askAboutStudyChunk(chunk);
      });
    }
  }
  studyChunkModal.showModal();
}

async function openFileChunksModal(file) {
  if (!studyChunkModal || !file) return;
  const titleEl = document.getElementById("studyChunkModalTitle");
  const subEl = document.getElementById("studyChunkModalSub");
  const bodyEl = document.getElementById("studyChunkModalBody");
  if (titleEl) titleEl.textContent = `${file.file_name} · 切片一览`;
  if (subEl) subEl.textContent = `${formatFileTypeLabel(file.file_type, file.file_name)} · 共 ${file.chunk_count || 0} 个切片`;
  if (bodyEl) bodyEl.innerHTML = '<div style="padding:20px;color:var(--muted);text-align:center;">正在加载切片与主题词...</div>';
  studyChunkModal.showModal();
  try {
    const res = await requestJson(`/api/study/library/chunks?file_id=${encodeURIComponent(file.id)}`);
    if (!res.ok || !bodyEl) return;
    const chunks = res.chunks || [];
    if (!chunks.length) {
      bodyEl.innerHTML = '<div style="padding:20px;color:var(--muted);text-align:center;">该资料暂无文本切片。</div>';
      return;
    }
    bodyEl.innerHTML = "";
    chunks.forEach((ch) => {
      const card = document.createElement("div");
      card.className = "study-chunk-list-card";
      card.innerHTML = `
        <div class="study-chunk-list-head">
          <strong>${escapeHtml(ch.location || `片段 ${ch.chunk_index + 1}`)}${ch.section_title ? ` · ${escapeHtml(ch.section_title)}` : ""}</strong>
          ${file.linked ? '<button type="button" class="study-lib-btn btn-ask-this">学习此切片</button>' : ""}
        </div>
        ${renderTopicChipsHtml(ch.topics, 6)}
        <div class="study-chunk-list-text">${escapeHtml((ch.content || "").slice(0, 320))}${(ch.content || "").length > 320 ? "..." : ""}</div>
      `;
      const askBtn = card.querySelector(".btn-ask-this");
      if (askBtn) {
        askBtn.addEventListener("click", () => {
          studyChunkModal.close();
          askAboutStudyChunk({ ...ch, chunk_id: ch.id, doc_name: file.file_name });
        });
      }
      bodyEl.appendChild(card);
    });
  } catch (err) {
    if (bodyEl) bodyEl.innerHTML = `<div style="padding:20px;color:#e05252;">加载失败：${escapeHtml(err.message)}</div>`;
  }
}

const studyFilesToggleBtn = document.getElementById("studyFilesToggle");
const studyFilesDrawer = document.getElementById("studyFilesDrawer");
if (studyFilesToggleBtn && studyFilesDrawer) {
  studyFilesToggleBtn.addEventListener("click", () => {
    const nextHidden = !studyFilesDrawer.hidden;
    studyFilesDrawer.hidden = nextHidden;
    studyFilesToggleBtn.setAttribute("aria-expanded", String(!nextHidden));
  });
}
const studyFilesFilterLinkedBtn = document.getElementById("studyFilesFilterLinkedBtn");
if (studyFilesFilterLinkedBtn) {
  studyFilesFilterLinkedBtn.addEventListener("click", () => {
    studyFilterLinkedOnly = !studyFilterLinkedOnly;
    studyFilesFilterLinkedBtn.setAttribute("aria-pressed", String(studyFilterLinkedOnly));
    studyFilesFilterLinkedBtn.classList.toggle("is-active", studyFilterLinkedOnly);
    renderStudyFilesList();
  });
}
const studyLibraryUploadBtn = document.getElementById("studyLibraryUploadBtn");
const studyLibraryUploadInput = document.getElementById("studyLibraryUploadInput");
if (studyLibraryUploadBtn && studyLibraryUploadInput) {
  studyLibraryUploadBtn.addEventListener("click", () => studyLibraryUploadInput.click());
  studyLibraryUploadInput.addEventListener("change", async () => {
    await uploadFilesToStudyLibrary(studyLibraryUploadInput.files || []);
    studyLibraryUploadInput.value = "";
  });
}

function hydrateStudyCitationsAndPanels(messageItem, ragMeta) {
  if (!messageItem || !ragMeta || !ragMeta.grounded) return;
  const contentWrap = messageItem.querySelector(".message-content");
  const bubble = messageItem.querySelector(".md-bubble");
  if (!contentWrap || !bubble) return;

  const sources = Array.isArray(ragMeta.sources) ? ragMeta.sources : [];
  const citeMap = {};
  sources.forEach((s) => {
    if (s.cite_id) citeMap[s.cite_id] = s;
  });

  const walker = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT);
  const textNodes = [];
  let node;
  while ((node = walker.nextNode())) {
    if (!node.parentElement) continue;
    if (node.parentElement.closest("code, pre, script, style, .cite-pill")) continue;
    if (/\[S\d+\]/.test(node.nodeValue || "")) textNodes.push(node);
  }
  textNodes.forEach((tn) => {
    const parts = (tn.nodeValue || "").split(/(\[S\d+\])/g);
    const frag = document.createDocumentFragment();
    parts.forEach((part) => {
      const m = part.match(/^\[(S\d+)\]$/);
      if (m && citeMap[m[1]]) {
        const src = citeMap[m[1]];
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "cite-pill";
        btn.textContent = `[${m[1]}]`;
        btn.title = `点击查看来源：${src.doc_name} · ${src.location}`;
        btn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          openChunkPreviewModal(src);
        });
        frag.appendChild(btn);
      } else {
        frag.appendChild(document.createTextNode(part));
      }
    });
    tn.parentNode.replaceChild(frag, tn);
  });

  if (ragMeta.abstained) {
    bubble.classList.add("is-abstained");
  }

  contentWrap.querySelectorAll(".study-rag-panel").forEach((el) => el.remove());

  const panel = document.createElement("div");
  panel.className = "study-rag-panel";

  const statusStrip = document.createElement("div");
  statusStrip.className = `rag-status-strip${ragMeta.abstained ? " is-abstained" : ""}`;
  const scoreStr = Number(ragMeta.max_score || 0).toFixed(3);
  const thStr = Number(ragMeta.threshold || 0.22).toFixed(2);
  statusStrip.innerHTML = `
    <span class="rag-status-badge">${ragMeta.abstained ? "诚实拒答 · 相关度不足" : "已溯源作答"}</span>
    <span>最高相关度 <code>${scoreStr}</code>（阈值 <code>${thStr}</code>）</span>
    ${ragMeta.citation_warning ? `<span class="rag-warning">${escapeHtml(ragMeta.citation_warning)}</span>` : ""}
  `;
  panel.appendChild(statusStrip);

  if (sources.length > 0) {
    const srcDet = document.createElement("details");
    srcDet.className = "rag-section";
    srcDet.open = true;
    srcDet.innerHTML = `<summary>${
      ragMeta.abstained
        ? `最相关的候选切片（共 ${sources.length} 处 · 相关度低于阈值，仅供参考）`
        : `引用来源（共 ${sources.length} 处 · 点击查看切片原文）`
    }</summary>`;
    const list = document.createElement("div");
    list.className = "rag-card-list";
    sources.forEach((src) => {
      const card = document.createElement("div");
      card.className = "rag-card";
      card.innerHTML = `
        <div class="rag-card-top">
          <span class="rag-card-title">[${escapeHtml(src.cite_id || "S")}] ${escapeHtml(src.doc_name)} · ${escapeHtml(src.location)}</span>
          <span class="rag-card-score">相关度 ${Number(src.score || 0).toFixed(3)}</span>
        </div>
        ${src.section_title ? `<div class="rag-card-sub">${escapeHtml(src.section_title)}</div>` : ""}
        ${renderTopicChipsHtml(src.topics, 5)}
        ${src.snippet ? `<div class="rag-card-snippet">${escapeHtml(src.snippet)}</div>` : ""}
      `;
      card.addEventListener("click", () => openChunkPreviewModal(src));
      list.appendChild(card);
    });
    srcDet.appendChild(list);
    panel.appendChild(srcDet);
  }

  const recs = Array.isArray(ragMeta.recommendations) ? ragMeta.recommendations : [];
  if (recs.length > 0 && !ragMeta.abstained) {
    const recDet = document.createElement("details");
    recDet.className = "rag-section";
    recDet.open = true;
    recDet.innerHTML = `<summary>继续学习 · 按主题词选择下一个学习切片</summary>`;
    const list = document.createElement("div");
    list.className = "rag-card-list";
    recs.forEach((rec) => {
      const card = document.createElement("div");
      card.className = "rag-card rag-rec-card";
      card.innerHTML = `
        <div class="rag-card-top">
          <span class="rag-card-title">${escapeHtml(rec.doc_name)} · ${escapeHtml(rec.location)}</span>
          <span class="rag-reason-badge">${escapeHtml(rec.reason || "推荐学习")}</span>
        </div>
        ${rec.section_title ? `<div class="rag-card-sub"><strong>本切片主题：</strong>${escapeHtml(rec.section_title)}</div>` : ""}
        ${renderTopicChipsHtml(rec.topics, 6)}
        ${rec.snippet ? `<div class="rag-card-snippet">${escapeHtml(rec.snippet)}</div>` : ""}
        <div class="rag-card-actions">
          <button type="button" class="rag-mini-btn is-primary btn-learn-next">学习此主题</button>
          <button type="button" class="rag-mini-btn btn-view-slice">查看切片</button>
        </div>
      `;
      card.querySelector(".btn-learn-next").addEventListener("click", (ev) => {
        ev.stopPropagation();
        askAboutStudyChunk(rec);
      });
      card.querySelector(".btn-view-slice").addEventListener("click", (ev) => {
        ev.stopPropagation();
        openChunkPreviewModal(rec);
      });
      card.addEventListener("click", () => openChunkPreviewModal(rec));
      list.appendChild(card);
    });
    recDet.appendChild(list);
    panel.appendChild(recDet);
  }

  contentWrap.appendChild(panel);
}

function askAboutStudyChunk(chunk) {
  if (!currentStudySessionId || !chunk) return;
  const docName = chunk.doc_name || chunk.file_name || "学习资料";
  const loc = chunk.location || "";
  const title = chunk.section_title || "";
  const topicsStr = Array.isArray(chunk.topics) && chunk.topics.length ? `（主题词：${chunk.topics.slice(0, 4).join("、")}）` : "";
  const prompt = `请结合《${docName}》${loc}${title ? `「${title}」` : ""}${topicsStr}，详细讲解这一部分的核心知识点。`;
  sendStudyQuestion(prompt, { pinnedChunkId: chunk.chunk_id || chunk.id || "" });
}

let lastRenderedStudySig = "";

async function loadStudyMessages(sessionId) {
  if (!els.studyChatList) return;
  if (!els.studyChatList.children.length) {
    els.studyChatList.innerHTML = '<div style="text-align:center;color:var(--muted);padding:24px;">进入自习室中...</div>';
  }
  try {
    const res = await requestJson(`/api/study/messages?session_id=${encodeURIComponent(sessionId)}`);
    if (!res.ok) return;
    renderStudyMessages(res.messages || [], sessionId);
  } catch (err) {
    els.studyChatList.innerHTML = `<div style="text-align:center;color:#e05252;padding:24px;">加载失败: ${err.message}</div>`;
  }
}

function renderStudyMessages(messages, sessionId = currentStudySessionId) {
  if (!els.studyChatList) return;
  const sig = `${sessionId}:${(messages || []).length}:${(messages || []).map((m) => `${m.role}:${(m.content || "").length}:${m.meta?.abstained ? 1 : 0}:${(m.meta?.recommendations || []).length}`).join("|")}`;
  if (sig === lastRenderedStudySig && els.studyChatList.children.length > 0) {
    return;
  }
  lastRenderedStudySig = sig;
  els.studyChatList.innerHTML = "";
  if (!messages || !messages.length) {
    els.studyChatList.innerHTML = '<div style="text-align:center;color:var(--muted);padding:40px;">自习室已开启！你可以先在右上角「资料库」上传并勾选本自习室要关联的学习资料，然后向云雀提问。</div>';
    return;
  }
  messages.forEach(msg => {
    const isUser = msg.role === "user";
    const item = document.createElement("article");
    item.className = `message ${isUser ? "is-user" : "is-agent"}`;
    item.innerHTML = `
      <div class="message-content">
        <div class="bubble md-bubble">${renderMarkdown(msg.content)}</div>
      </div>
    `;
    els.studyChatList.appendChild(item);
    hydrateHtmlWidgets(item);
    if (!isUser && msg.meta && msg.meta.grounded) {
      hydrateStudyCitationsAndPanels(item, msg.meta);
    }
  });
  els.studyChatList.scrollTop = els.studyChatList.scrollHeight;
}

let studyPendingFiles = [];

function renderStudyPendingFiles() {
  const box = document.getElementById("studyPendingAttachments");
  if (!box) return;
  box.textContent = "";
  box.hidden = !studyPendingFiles.length;
  studyPendingFiles.forEach((item) => {
    const chip = document.createElement("span");
    chip.className = "pending-file";
    const name = document.createElement("span");
    name.textContent = item.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `移除 ${item.name}`);
    remove.onclick = () => {
      studyPendingFiles = studyPendingFiles.filter((entry) => entry !== item);
      renderStudyPendingFiles();
    };
    chip.append(name, remove);
    box.append(chip);
  });
}

async function addStudyFiles(fileList) {
  const files = [...fileList].filter(isSupportedClientFile);
  const available = 9 - studyPendingFiles.length;
  if (files.length > available) window.alert("每次最多选择 9 个文件。");
  const additions = [];
  for (const file of files.slice(0, available)) {
    if (file.size > 10 * 1024 * 1024) {
      window.alert(`${file.name} 超过 10 MB`);
      continue;
    }
    additions.push({ name: file.name, type: inferClientMime(file), size: file.size, data: await blobToDataUrl(file) });
  }
  studyPendingFiles.push(...additions);
  renderStudyPendingFiles();
}

const studyAttachmentBtn = document.getElementById("studyAttachmentButton");
const studyAttachmentInput = document.getElementById("studyAttachmentInput");
if (studyAttachmentBtn && studyAttachmentInput) {
  studyAttachmentBtn.addEventListener("click", () => studyAttachmentInput.click());
  studyAttachmentInput.addEventListener("change", async () => {
    await addStudyFiles(studyAttachmentInput.files || []);
    studyAttachmentInput.value = "";
  });
}

async function sendStudyQuestion(rawText, options = {}) {
  const attachmentsToSend = Array.isArray(options.attachments) ? options.attachments : [];
  const pinnedChunkId = String(options.pinnedChunkId || "").trim();
  if ((!rawText && !attachmentsToSend.length) || !currentStudySessionId) return;

  const displayText = rawText || "请帮我解析上传的文件或图片内容，并结合当前学习主题辅导我。";
  const displayWithBadges = attachmentsToSend.length
    ? `${displayText}\n\n${attachmentsToSend.map((f) => `[附件: ${f.name}]`).join(" ")}`
    : displayText;

  lastRenderedStudySig = "";
  const userItem = document.createElement("article");
  userItem.className = "message is-user";
  userItem.innerHTML = `<div class="message-content"><div class="bubble md-bubble">${renderMarkdown(displayWithBadges)}</div></div>`;
  els.studyChatList.appendChild(userItem);

  const typingItem = document.createElement("article");
  typingItem.className = "message is-agent";
  typingItem.innerHTML = `<div class="message-content"><div class="bubble" style="color:var(--muted);">云雀正在检索关联资料并整理溯源解答……</div></div>`;
  els.studyChatList.appendChild(typingItem);
  els.studyChatList.scrollTop = els.studyChatList.scrollHeight;

  let streamText = "";
  let lastRenderAt = 0;
  const replyBubble = typingItem.querySelector(".bubble");

  try {
    const studyReqBody = {
      session_id: currentStudySessionId,
      content: rawText,
      attachments: attachmentsToSend,
      pinned_chunk_id: pinnedChunkId,
    };
    let donePayload = null;
    try {
      donePayload = await consumeSseStream("/api/study/chat/stream", studyReqBody, {
        onMeta: (meta) => {
          if (Array.isArray(meta.library_files)) renderStudyFilesList(meta.library_files);
        },
        onDelta: (delta) => {
          if (!delta) return;
          streamText += delta;
          replyBubble.style.color = "";
          replyBubble.classList.add("md-bubble");
          const now = Date.now();
          if (now - lastRenderAt > 120) {
            lastRenderAt = now;
            replyBubble.innerHTML = renderMarkdown(streamText, { streaming: true });
            els.studyChatList.scrollTop = els.studyChatList.scrollHeight;
          }
        },
      });
    } catch (streamErr) {
      if (streamErr?.status !== 404) throw streamErr;
      donePayload = await requestJson("/api/study/chat", {
        method: "POST",
        body: JSON.stringify(studyReqBody),
      });
    }
    const finalReply = donePayload?.reply || streamText;
    if (finalReply) {
      replyBubble.style.color = "";
      replyBubble.classList.add("md-bubble");
      replyBubble.innerHTML = renderMarkdown(finalReply);
      hydrateHtmlWidgets(replyBubble);
      if (donePayload?.rag_meta && donePayload.rag_meta.grounded) {
        hydrateStudyCitationsAndPanels(typingItem, donePayload.rag_meta);
      }
      if (Array.isArray(donePayload?.library_files)) renderStudyFilesList(donePayload.library_files);
    } else {
      replyBubble.textContent = "解答遇到一点问题，请重试~";
    }
  } catch (err) {
    replyBubble.textContent = `回答失败: ${err.message}`;
  }
  els.studyChatList.scrollTop = els.studyChatList.scrollHeight;
}

async function handleStudySubmit(e) {
  e.preventDefault();
  const rawText = (els.studyMessageInput?.value || "").trim();
  const attachmentsToSend = [...studyPendingFiles];
  if ((!rawText && !attachmentsToSend.length) || !currentStudySessionId) return;

  els.studyMessageInput.value = "";
  studyPendingFiles = [];
  renderStudyPendingFiles();
  await sendStudyQuestion(rawText, { attachments: attachmentsToSend });
}

async function handleCreateStudySession(e) {
  e.preventDefault();
  const subject = (els.newStudySubjectInput?.value || "").trim();
  if (!subject) {
    alert("请输入自习学科科目！");
    els.newStudySubjectInput?.focus();
    return;
  }
  const topic = (els.newStudyTopicInput?.value || "").trim() || `${subject}重点自习`;
  const seed = (els.newStudySeedInput?.value || "").trim();

  try {
    const res = await requestJson("/api/study/sessions", {
      method: "POST",
      body: JSON.stringify({ subject, title: topic, prompt_seed: seed }),
    });
    if (res.ok && res.session) {
      if (els.newStudySessionModal) els.newStudySessionModal.hidden = true;
      if (els.newStudySessionForm) els.newStudySessionForm.reset();
      showToastMessage(`已开启自习室【${topic}】`);
      await loadStudySessions(res.session.id);
    }
  } catch (err) {
    alert("创建自习室失败: " + err.message);
  }
}

window.openStudySession = function(sessionId) {
  setView("study");
  loadStudySessions(sessionId);
};

const SHORTCUT_STORAGE_KEY = "yunque.companion.shortcuts.v1";

function getEnabledShortcuts() {
  try {
    const raw = localStorage.getItem(SHORTCUT_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function saveEnabledShortcuts(list) {
  try {
    localStorage.setItem(SHORTCUT_STORAGE_KEY, JSON.stringify(list));
  } catch {
    // ignore storage errors
  }
}

function renderOrbitShortcuts() {
  const enabled = new Set(getEnabledShortcuts());
  const grid = document.getElementById("orbitShortcutsGrid");
  if (grid) {
    grid.querySelectorAll("input[data-shortcut-toggle]").forEach((chk) => {
      chk.checked = enabled.has(chk.dataset.shortcutToggle);
    });
  }

  const nav = document.getElementById("orbitNav") || document.querySelector(".orbit-nav");
  if (!nav) return;
  const allBubbles = [...nav.querySelectorAll(".orbit-bubble[data-shortcut-id]")];
  const visibleBubbles = [];

  allBubbles.forEach((btn) => {
    const id = btn.dataset.shortcutId;
    const isShown = enabled.has(id);
    btn.hidden = !isShown;
    btn.style.display = isShown ? "" : "none";
    if (isShown) visibleBubbles.push(btn);
  });

  // 根据勾选的气泡数量，动态在云雀左右两侧排布优美对称弧线
  const leftSide = [];
  const rightSide = [];
  visibleBubbles.forEach((btn, idx) => {
    if (idx % 2 === 0) leftSide.push(btn);
    else rightSide.push(btn);
  });

  const getArcSlots = (count) => {
    if (count === 1) return [{ top: "50%", dist: "215px" }];
    if (count === 2) return [{ top: "38%", dist: "215px" }, { top: "62%", dist: "215px" }];
    if (count === 3) return [{ top: "27%", dist: "195px" }, { top: "50%", dist: "235px" }, { top: "73%", dist: "195px" }];
    return [
      { top: "22%", dist: "185px" },
      { top: "41%", dist: "240px" },
      { top: "61%", dist: "240px" },
      { top: "80%", dist: "185px" },
    ];
  };

  const leftSlots = getArcSlots(leftSide.length);
  leftSide.forEach((btn, i) => {
    const slot = leftSlots[i] || leftSlots[leftSlots.length - 1];
    btn.style.top = slot.top;
    btn.style.right = `calc(50% + ${slot.dist})`;
    btn.style.left = "auto";
  });

  const rightSlots = getArcSlots(rightSide.length);
  rightSide.forEach((btn, i) => {
    const slot = rightSlots[i] || rightSlots[rightSlots.length - 1];
    btn.style.top = slot.top;
    btn.style.left = `calc(50% + ${slot.dist})`;
    btn.style.right = "auto";
  });
}

function setupOrbitShortcuts() {
  const grid = document.getElementById("orbitShortcutsGrid");
  if (grid) {
    grid.querySelectorAll("input[data-shortcut-toggle]").forEach((chk) => {
      chk.addEventListener("change", () => {
        const selected = [...grid.querySelectorAll("input[data-shortcut-toggle]:checked")]
          .map((el) => el.dataset.shortcutToggle);
        saveEnabledShortcuts(selected);
        renderOrbitShortcuts();
      });
    });
  }
  renderOrbitShortcuts();
}

function setupSettingsSubNav() {
  const nav = document.getElementById("settingsNavBar");
  if (!nav) return;
  nav.querySelectorAll(".settings-nav-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const target = btn.dataset.settingsTab;
      nav.querySelectorAll(".settings-nav-btn").forEach(b => {
        b.classList.toggle("is-active", b === btn);
      });
      const compPanel = document.getElementById("settingsPanelCompanion");
      const sysPanel = document.getElementById("settingsPanelSystem");
      if (compPanel) compPanel.hidden = target !== "companion";
      if (sysPanel) sysPanel.hidden = target !== "system";
    });
  });
}

function setupAcademicProfileEvents() {
  // Study events
  if (els.studyForm) els.studyForm.onsubmit = handleStudySubmit;
  if (els.studySessionSelect) {
    els.studySessionSelect.onchange = (e) => {
      selectStudySession(e.target.value);
    };
  }
  const wheelStage = document.getElementById("studyWheelStage");
  if (wheelStage) {
    wheelStage.addEventListener("wheel", (e) => {
      if (!studySessionsList || studySessionsList.length <= 1) return;
      e.preventDefault();
      if (studyWheelLocked) return;
      const curIdx = studySessionsList.findIndex((s) => s.id === currentStudySessionId);
      const nextIdx = e.deltaY > 0
        ? Math.min(studySessionsList.length - 1, (curIdx < 0 ? 0 : curIdx) + 1)
        : Math.max(0, (curIdx < 0 ? 0 : curIdx) - 1);
      if (nextIdx !== curIdx && studySessionsList[nextIdx]) {
        studyWheelLocked = true;
        selectStudySession(studySessionsList[nextIdx].id, studySessionsList[nextIdx]);
        setTimeout(() => { studyWheelLocked = false; }, 160);
      }
    }, { passive: false });
  }
  if (els.newStudySessionBtn) {
    els.newStudySessionBtn.onclick = () => {
      if (els.newStudySessionModal) els.newStudySessionModal.hidden = false;
    };
  }
  if (els.newStudyCancelBtn) {
    els.newStudyCancelBtn.onclick = () => {
      if (els.newStudySessionModal) els.newStudySessionModal.hidden = true;
    };
  }
  if (els.newStudySessionForm) els.newStudySessionForm.onsubmit = handleCreateStudySession;

  // Profile events
  initStageSegmentedBars();
  if (els.openNewProfileModalBtn) {
    els.openNewProfileModalBtn.onclick = () => {
      if (els.newProfileModal) {
        els.newProfileModal.hidden = false;
        els.newProfileModal.removeAttribute("hidden");
        applyStageToProfileForm("new", "high_school");
      }
    };
  }
  if (els.newProfileCancelBtn) {
    els.newProfileCancelBtn.onclick = () => {
      if (els.newProfileModal) {
        els.newProfileModal.hidden = true;
        els.newProfileModal.setAttribute("hidden", "");
      }
    };
  }
  if (els.newProfileForm) els.newProfileForm.onsubmit = handleCreateProfileSubmit;
  if (els.newProfileSubmitBtn) {
    els.newProfileSubmitBtn.onclick = (e) => {
      if (els.newProfileForm && !els.newProfileForm.checkValidity()) {
        els.newProfileForm.reportValidity();
        return;
      }
      handleCreateProfileSubmit(e);
    };
  }
  if (els.saveActiveProfileBtn) els.saveActiveProfileBtn.onclick = saveActiveProfile;
  if (els.deleteActiveProfileBtn) els.deleteActiveProfileBtn.onclick = deleteActiveProfile;

  // Scores
  const toggleScoreBtn = document.getElementById("toggleScoreFormButton");
  const scoreForm = document.getElementById("scoreQuickForm");
  const cancelScoreBtn = document.getElementById("cancelScoreFormButton");

  toggleScoreBtn?.addEventListener("click", () => {
    if (scoreForm) {
      scoreForm.hidden = !scoreForm.hidden;
      if (!scoreForm.hidden && document.getElementById("scoreExamDate")) {
        document.getElementById("scoreExamDate").value = chinaDateKey();
      }
    }
  });

  cancelScoreBtn?.addEventListener("click", () => {
    if (scoreForm) scoreForm.hidden = true;
  });

  scoreForm?.addEventListener("submit", saveAcademicScoreAction);

  setupSettingsSubNav();
  setupOrbitShortcuts();
}

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
const LARK_TIME_GREETINGS = {
  morning: [
    "早上好，准备开始一天的学习了吗？",
    "早安呀，新的一天我们慢慢来，先定一个小目标吧。",
    "早上好！精神不错的话，要不要先去自习室热热身？",
  ],
  noon: [
    "中午好，记得好好吃午饭、休息一会儿再继续哦。",
    "午间时间到啦，劳逸结合效率才会更高。",
    "中午好呀，上午的进度怎么样？可以和我聊聊。",
  ],
  afternoon: [
    "下午好，要一起推进今天的学习任务吗？",
    "午后容易犯困，喝口水，我陪你把重点过一遍吧。",
    "下午好呀，有想问的问题或者想聊的心事随时找我。",
  ],
  evening: [
    "晚上好，今天辛苦啦，要不要一起复盘一下今天的收获？",
    "晚上好呀，写篇日记或者轻松聊聊天都很不错。",
    "傍晚安静下来了，今晚打算复习哪一块呢？",
  ],
  night: [
    "晚上了，该休息啦，别熬夜太久哦。",
    "夜深了，今天就先到这里吧，明天我还在。",
    "已经很晚啦，早点睡个好觉，晚安。",
  ],
};

let larkGreetingSlot = "";
let larkGreetingIndex = 0;

function getLarkTimeSlot(hour = new Date().getHours()) {
  if (hour >= 5 && hour < 11) return "morning";
  if (hour >= 11 && hour < 14) return "noon";
  if (hour >= 14 && hour < 18) return "afternoon";
  if (hour >= 18 && hour < 22) return "evening";
  return "night";
}

function updateLarkGreeting(advance = false) {
  const textEl = document.getElementById("larkGreetingText");
  if (!textEl) return;
  const slot = getLarkTimeSlot();
  const list = LARK_TIME_GREETINGS[slot] || LARK_TIME_GREETINGS.morning;
  if (slot !== larkGreetingSlot) {
    larkGreetingSlot = slot;
    larkGreetingIndex = 0;
  } else if (advance) {
    larkGreetingIndex = (larkGreetingIndex + 1) % list.length;
  }
  textEl.textContent = list[larkGreetingIndex];
}

function initLarkGreeting() {
  updateLarkGreeting(false);
  const btn = document.getElementById("larkGreetingBubble");
  if (btn && !btn.dataset.boundGreeting) {
    btn.dataset.boundGreeting = "1";
    btn.addEventListener("click", () => updateLarkGreeting(true));
  }
  window.addEventListener("yunque:view", (ev) => {
    if (ev?.detail?.view === "home") updateLarkGreeting(false);
  });
}

  renderAiDiary();
  renderPendingFiles(); rebuildSentMedia(); renderTrajectory(); initializeEmotionDragging();
  setupAcademicProfileEvents();
  loadProfiles();
  initLarkGreeting();
  updateEmotionPinState(); if(state.emotionPosition){els.emotionWidget.style.left=`${state.emotionPosition.left}px`;els.emotionWidget.style.top=`${state.emotionPosition.top}px`;els.emotionWidget.style.right="auto"}
  await checkAuth();
  setView("home");
  showApp();
}

initialize();
