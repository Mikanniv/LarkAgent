const state = {
  stream: null,
  audioContext: null,
  analyser: null,
  source: null,
  mediaRecorder: null,
  recordedChunks: [],
  speechRecognition: null,
  speechTranscript: "",
  faceLandmarker: null,
  lastVideoTime: -1,
  mediapipeReady: false,
  history: [],
  proactiveTimer: null,
  captureLoopTimer: null,
  emotionMonitorTimer: null,
  diaryRefreshTimer: null,
  diarySaveTimer: null,
  speechReplyTimer: null,
  selectedDiaryDate: "",
  diaryDates: [],
  selectedDiaryIsToday: true,
  visibleCalendarMonth: "",
  journalMode: "ai",
  lastInteractionAt: 0,
  lastUserInteractionAt: 0,
  lastEmotionComputedAt: 0,
  lastPeriodicEmotionAt: 0,
  emotionRequestPending: false,
  chatRequestPending: false,
  chatRequestPromise: null,
  speechReplyPending: false,
  proactivePending: false,
  proactiveIdleLevel: 1,
  nextIdleProactiveAt: 0,
  proactiveCooldownUntil: 0,
  lastProactiveAt: 0,
  authUser: null,
  activeSidebarView: "emotion",
  videoStats: {
    brightness: 0,
    motion: 0,
    contrast: 0,
    faceFocus: 0,
    smile: 0,
    frown: 0,
    mouthOpen: 0,
    browRaise: 0,
    eyeWiden: 0,
    jawOpen: 0,
    cheekRaise: 0,
    squint: 0,
    saturation: 0,
    warmth: 0,
    symmetry: 0,
    stability: 0,
    available: false,
  },
  audioStats: {
    volume: 0,
    peak: 0,
    centroid: 0,
    flux: 0,
    zcr: 0,
    rms: 0,
    pitch: 0,
    rolloff: 0,
    flatness: 0,
    spread: 0,
    dynamicRange: 0,
    available: false,
  },
};

const els = {
  introScreen: document.getElementById("introScreen"),
  enterAppButton: document.getElementById("enterAppButton"),
  authToggleButton: document.getElementById("authToggleButton"),
  authForm: document.getElementById("authForm"),
  authUsername: document.getElementById("authUsername"),
  authPassword: document.getElementById("authPassword"),
  authLoginButton: document.getElementById("authLoginButton"),
  authRegisterButton: document.getElementById("authRegisterButton"),
  authStatus: document.getElementById("authStatus"),
  appShell: document.getElementById("appShell"),
  backendStatus: document.getElementById("backendStatus"),
  captureStatus: document.getElementById("captureStatus"),
  agentStatus: document.getElementById("agentStatus"),
  clearDataButton: document.getElementById("clearDataButton"),
  toggleCapture: document.getElementById("toggleCapture"),
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  chatList: document.getElementById("chatList"),
  video: document.getElementById("video"),
  frameCanvas: document.getElementById("frameCanvas"),
  videoBadge: document.getElementById("videoBadge"),
  audioBadge: document.getElementById("audioBadge"),
  emotionLabel: document.getElementById("emotionLabel"),
  fusionScore: document.getElementById("fusionScore"),
  valenceValue: document.getElementById("valenceValue"),
  arousalValue: document.getElementById("arousalValue"),
  emotionBars: document.getElementById("emotionBars"),
  fusionRaw: document.getElementById("fusionRaw"),
  textRaw: document.getElementById("textRaw"),
  audioRaw: document.getElementById("audioRaw"),
  videoRaw: document.getElementById("videoRaw"),
  emotionRing: document.getElementById("emotionRing"),
  sidebarEmotionTab: document.getElementById("sidebarEmotionTab"),
  sidebarDiaryTab: document.getElementById("sidebarDiaryTab"),
  emotionView: document.getElementById("emotionView"),
  diaryView: document.getElementById("diaryView"),
  aiDiary: document.getElementById("aiDiary"),
  aiDiaryActions: document.getElementById("aiDiaryActions"),
  aiDiaryConfirmButton: document.getElementById("aiDiaryConfirmButton"),
  aiDiaryCorrectButton: document.getElementById("aiDiaryCorrectButton"),
  aiDiaryCorrectionModal: document.getElementById("aiDiaryCorrectionModal"),
  aiDiaryCorrectionInput: document.getElementById("aiDiaryCorrectionInput"),
  aiDiaryCorrectionCancel: document.getElementById("aiDiaryCorrectionCancel"),
  aiDiaryCorrectionSubmit: document.getElementById("aiDiaryCorrectionSubmit"),
  userDiary: document.getElementById("userDiary"),
  diaryDateCount: document.getElementById("diaryDateCount"),
  diarySelectedDate: document.getElementById("diarySelectedDate"),
  diaryEditState: document.getElementById("diaryEditState"),
  calendarPrev: document.getElementById("calendarPrev"),
  calendarNext: document.getElementById("calendarNext"),
  calendarMonthLabel: document.getElementById("calendarMonthLabel"),
  calendarGrid: document.getElementById("calendarGrid"),
  journalAiTab: document.getElementById("journalAiTab"),
  journalUserTab: document.getElementById("journalUserTab"),
  journalHint: document.getElementById("journalHint"),
  audioFeatureList: document.getElementById("audioFeatureList"),
  videoFeatureList: document.getElementById("videoFeatureList"),
};

let previousSpectrum = [];
let previousFrame = null;
const API_BASE = resolveApiBase();
const CHINA_TIME_ZONE = "Asia/Shanghai";
const chinaDateTimeFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: CHINA_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const EMOTION_IDLE_DELAY_MS = 15000;
const EMOTION_PERIODIC_INTERVAL_MS = 10000;
const PROACTIVE_IDLE_BASE_MS = 2 * 60 * 1000;
const PROACTIVE_IDLE_MAX_MS = 128 * 60 * 1000;
const PROACTIVE_COOLDOWN_MS = 120000;
const EMOTION_MONITOR_INTERVAL_MS = 1000;
const CHAT_HISTORY_STORAGE_KEY = "yunque.chat.history.v1";
const CHAT_DISPLAY_LIMIT = 20;
const CHAT_CONTEXT_LIMIT = 6;
const MAX_LOCAL_CHAT_MESSAGES = 6;

function proactiveIdleDelay(level = state.proactiveIdleLevel) {
  const safeLevel = Math.max(1, Number(level) || 1);
  return Math.min(2 ** (safeLevel - 1) * PROACTIVE_IDLE_BASE_MS, PROACTIVE_IDLE_MAX_MS);
}

function resetProactiveIdleSchedule(now = Date.now()) {
  state.proactiveIdleLevel = 1;
  state.nextIdleProactiveAt = now + proactiveIdleDelay(1);
}

function advanceProactiveIdleSchedule(now = Date.now()) {
  state.proactiveIdleLevel = Math.min(state.proactiveIdleLevel + 1, 7);
  state.nextIdleProactiveAt = now + proactiveIdleDelay(state.proactiveIdleLevel);
}

function resolveApiBase() {
  const metaBase = document.querySelector('meta[name="app-api-base"]')?.content?.trim() || "";
  if (new URLSearchParams(window.location.search).get("cloud-auth") === "1" && metaBase) {
    return metaBase.replace(/\/$/, "");
  }
  if (["127.0.0.1", "localhost", "::1", "0.0.0.0"].includes(window.location.hostname)) {
    return window.location.origin.replace(/\/$/, "");
  }
  if (metaBase) {
    return metaBase.replace(/\/$/, "");
  }
  return window.location.origin.replace(/\/$/, "");
}

function apiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalizedPath}`;
}

function authRequired() {
  try {
    return new URL(API_BASE).hostname === "worker.lark.irises.me";
  } catch {
    return !["127.0.0.1", "localhost", "::1", "0.0.0.0"].includes(window.location.hostname);
  }
}

function setAuthStatus(text) {
  if (els.authStatus) {
    els.authStatus.textContent = text;
  }
}

function setAuthPopover(open) {
  if (els.authForm) {
    els.authForm.hidden = !open;
  }
}

function updateAuthUi(user) {
  state.authUser = user || null;
  if (!els.authForm) {
    return;
  }
  if (!authRequired()) {
    els.authForm.hidden = true;
    if (els.authToggleButton) {
      els.authToggleButton.hidden = true;
    }
    els.enterAppButton.disabled = false;
    return;
  }
  els.enterAppButton.disabled = !state.authUser;
  if (state.authUser) {
    setAuthPopover(false);
    if (els.authToggleButton) {
      els.authToggleButton.textContent = `已登录：${state.authUser.username}`;
    }
    setAuthStatus(`已登录：${state.authUser.username}`);
  } else {
    if (els.authToggleButton) {
      els.authToggleButton.textContent = "登录 / 注册";
    }
    setAuthStatus("请先登录或注册，云雀会按账号隔离长期记忆。");
  }
}

async function loadCurrentUser() {
  if (!authRequired()) {
    updateAuthUi({ id: "local_user", username: "本地调试" });
    return;
  }
  try {
    const response = await fetch(apiUrl("/api/auth/me"), { credentials: "include" });
    const payload = await response.json();
    updateAuthUi(payload.user || null);
  } catch (error) {
    updateAuthUi(null);
  }
}

async function submitAuth(mode) {
  const username = els.authUsername?.value.trim() || "";
  const password = els.authPassword?.value || "";
  if (!username || password.length < 8) {
    setAuthStatus("请输入用户名和至少 8 位密码。");
    return;
  }
  setAuthStatus(mode === "register" ? "正在注册..." : "正在登录...");
  try {
    const response = await fetch(apiUrl(`/api/auth/${mode}`), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const payload = await readApiResponse(response);
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    els.authPassword.value = "";
    updateAuthUi(payload.user);
    loadDiary();
    startDiaryRefreshLoop();
    pingBackend();
  } catch (error) {
    setAuthStatus(authErrorMessage(mode, error));
  }
}

async function readApiResponse(response) {
  const text = await response.text();
  if (!text) {
    return {};
  }
  try {
    return JSON.parse(text);
  } catch {
    return { ok: false, error: `HTTP ${response.status}` };
  }
}

function authErrorMessage(mode, error) {
  const reason = error?.message || "";
  const messages = {
    invalid_username: "用户名需要 2 到 32 个字符。",
    invalid_password: "密码需要 8 到 128 位。",
    username_taken: "这个用户名已经被使用了。",
    invalid_credentials: "用户名或密码不对。",
  };
  if (messages[reason]) {
    return messages[reason];
  }
  if (reason.startsWith("HTTP 5")) {
    return "登录服务暂时异常，稍后再试或重新部署 Worker。";
  }
  return mode === "register" ? "注册失败，请稍后再试。" : "登录失败，请稍后再试。";
}

function chinaDateParts(date = new Date()) {
  return Object.fromEntries(chinaDateTimeFormatter.formatToParts(date).map((part) => [part.type, part.value]));
}

function chinaDateKey(date = new Date()) {
  const parts = chinaDateParts(date);
  return `${parts.year}-${parts.month}-${parts.day}`;
}

function chinaTimestamp(date = new Date()) {
  const parts = chinaDateParts(date);
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+08:00`;
}

function enterApp() {
  if (authRequired() && !state.authUser) {
    setAuthStatus("请先登录或注册，再进入云雀。");
    setAuthPopover(true);
    return;
  }
  if (els.introScreen) {
    els.introScreen.style.display = "none";
  }
  if (els.appShell) {
    els.appShell.classList.remove("app-shell-hidden");
  }
  if (!state.lastUserInteractionAt && !state.lastInteractionAt) {
    state.lastUserInteractionAt = Date.now();
    state.lastInteractionAt = state.lastUserInteractionAt;
    resetProactiveIdleSchedule(state.lastUserInteractionAt);
  }
  startEmotionMonitorLoop();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function shouldOpenChatDirectly() {
  const params = new URLSearchParams(window.location.search);
  return params.get("view") === "chat" || params.get("from") === "memory";
}

const AUDIO_FEATURE_META = [
  ["logF0", "对数基频 logF0", "LibROSA yin 提取后取对数"],
  ...Array.from({ length: 20 }, (_, index) => {
    const number = String(index + 1).padStart(2, "0");
    return [`mfcc_${number}`, `MFCC ${number}`, "梅尔频率倒谱系数"];
  }),
  ...Array.from({ length: 12 }, (_, index) => {
    const number = String(index + 1).padStart(2, "0");
    return [`cqt_${number}`, `CQT ${number}`, "常 Q 变换谱特征"];
  }),
];

const VIDEO_FEATURE_META = [
  ["smile", "笑容 smile", "MediaPipe 嘴角上扬"],
  ["frown", "皱眉 frown", "眉部下压与嘴角下压"],
  ["mouthOpen", "张口 mouthOpen", "嘴部张开程度"],
  ["browRaise", "挑眉 browRaise", "眉毛上抬程度"],
  ["eyeWiden", "睁眼 eyeWiden", "眼睛睁大程度"],
  ["jawOpen", "张颌 jawOpen", "下颌张开程度"],
  ["cheekRaise", "脸颊抬起 cheekRaise", "脸颊上提程度"],
  ["squint", "眯眼 squint", "眼部眯起程度"],
  ["blink", "眨眼 blink", "左右眼 blink 均值"],
];

function average(values) {
  if (!values.length) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function getBlendshapeScore(categories, names) {
  const scores = names
    .map((name) => categories.find((item) => item.categoryName === name)?.score ?? 0)
    .filter((value) => Number.isFinite(value));
  return clamp(average(scores), 0, 1);
}

async function ensureFaceLandmarker() {
  if (state.faceLandmarker || state.mediapipeReady) {
    return;
  }

  try {
    const vision = await import("https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14");
    const filesetResolver = await vision.FilesetResolver.forVisionTasks(
      "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/wasm",
    );
    state.faceLandmarker = await vision.FaceLandmarker.createFromOptions(filesetResolver, {
      baseOptions: {
        modelAssetPath: apiUrl("/face_landmarker.task"),
      },
      runningMode: "VIDEO",
      outputFaceBlendshapes: true,
      outputFacialTransformationMatrixes: true,
      numFaces: 1,
    });
    state.mediapipeReady = true;
    els.videoBadge.textContent = "表情识别已启动";
  } catch (error) {
    state.mediapipeReady = false;
    els.videoBadge.textContent = "表情识别加载失败";
  }
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeChatRole(role) {
  return role === "assistant" || role === "agent" ? "assistant" : "user";
}

function bubbleClassForRole(role) {
  return normalizeChatRole(role) === "assistant" ? "agent" : "user";
}

function roleLabel(role) {
  return normalizeChatRole(role) === "assistant" ? "云雀" : "你";
}

function normalizeHistoryItem(item) {
  if (!item || typeof item !== "object") {
    return null;
  }
  const content = String(item.content || "").trim();
  if (!content) {
    return null;
  }
  return {
    role: normalizeChatRole(item.role),
    content,
  };
}

function pruneChatHistory() {
  if (state.history.length > CHAT_DISPLAY_LIMIT) {
    state.history = state.history.slice(-CHAT_DISPLAY_LIMIT);
  }
}

function saveChatHistory() {
  try {
    pruneChatHistory();
    window.localStorage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify(state.history.slice(-MAX_LOCAL_CHAT_MESSAGES)));
  } catch (error) {
    // 本地存储不可用时不影响聊天主流程。
  }
}

function loadLocalChatHistory() {
  try {
    const raw = window.localStorage.getItem(CHAT_HISTORY_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    state.history = Array.isArray(parsed) ? parsed.map(normalizeHistoryItem).filter(Boolean) : [];
    pruneChatHistory();
    saveChatHistory();
  } catch (error) {
    state.history = [];
  }
}

async function loadChatHistory() {
  try {
    const response = await fetch(apiUrl(`/api/chat/history?limit=${CHAT_DISPLAY_LIMIT}`), { credentials: "include" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    state.history = Array.isArray(payload.items) ? payload.items.map(normalizeHistoryItem).filter(Boolean) : [];
    pruneChatHistory();
    saveChatHistory();
  } catch (error) {
    loadLocalChatHistory();
  }
}

function recentContextHistory() {
  return state.history.slice(-CHAT_CONTEXT_LIMIT).map((item) => ({
    role: normalizeChatRole(item.role),
    content: item.content,
  }));
}

function syncChatHistoryFromResult(result) {
  if (!Array.isArray(result?.chat_history)) {
    saveChatHistory();
    return;
  }
  state.history = result.chat_history.map(normalizeHistoryItem).filter(Boolean);
  pruneChatHistory();
  saveChatHistory();
}

function renderChatHistory() {
  els.chatList.innerHTML = "";
  if (!state.history.length) {
    addBubble("assistant", "你好！我是云雀。今天有什么想要分享的事情吗，我会认真倾听的～");
    return;
  }
  state.history.forEach((item) => addBubble(item.role, item.content));
}

function clearLocalChatCache() {
  state.history = [];
  try {
    window.localStorage.removeItem(CHAT_HISTORY_STORAGE_KEY);
  } catch (error) {
    // 本地存储不可用时不影响服务端清理。
  }
  renderChatHistory();
}

async function clearUserData() {
  const confirmed = window.confirm(
    "确定清除当前浏览器对话缓存，并删除当前账号与 local_user 的长期记忆和日记吗？这个操作不可撤销。"
  );
  if (!confirmed) {
    return;
  }

  clearLocalChatCache();
  els.agentStatus.textContent = "正在清理数据";
  try {
    const response = await fetch(apiUrl("/api/user/clear"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ include_local_user: true }),
    });
    const payload = await readApiResponse(response);
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || `HTTP ${response.status}`);
    }
    els.agentStatus.textContent = "缓存已清除";
    await loadDiary();
  } catch (error) {
    els.agentStatus.textContent = "清理失败";
    addBubble("assistant", "本地对话缓存已经清掉了，但后端记忆/日记清理失败，请检查后端和 R2 配置。");
  }
}

function addBubble(role, content) {
  const normalizedRole = normalizeChatRole(role);
  const wrapper = document.createElement("div");
  wrapper.className = `bubble bubble-${bubbleClassForRole(normalizedRole)}`;
  wrapper.innerHTML = `
    <div class="bubble-role">${roleLabel(normalizedRole)}</div>
    <div class="bubble-body"></div>
  `;
  wrapper.querySelector(".bubble-body").textContent = content;
  els.chatList.appendChild(wrapper);
  els.chatList.scrollTop = els.chatList.scrollHeight;
  return wrapper;
}

function addTypingBubble() {
  const wrapper = document.createElement("div");
  wrapper.className = "bubble bubble-agent bubble-typing";
  wrapper.innerHTML = `
    <div class="bubble-role">云雀</div>
    <div class="bubble-body">
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
      <span class="typing-dot"></span>
    </div>
  `;
  els.chatList.appendChild(wrapper);
  els.chatList.scrollTop = els.chatList.scrollHeight;
  return wrapper;
}

function setSidebarView(view) {
  state.activeSidebarView = view;
  const showEmotion = view === "emotion";
  els.sidebarEmotionTab.classList.toggle("is-active", showEmotion);
  els.sidebarDiaryTab.classList.toggle("is-active", !showEmotion);
  els.emotionView.classList.toggle("is-active", showEmotion);
  els.diaryView.classList.toggle("is-active", !showEmotion);
}

function formatDiaryDate(dateText) {
  if (!dateText) {
    return "今天";
  }
  const today = chinaDateKey();
  if (dateText === today) {
    return `${dateText} · 今天`;
  }
  return dateText;
}

function monthKeyFromDate(dateText) {
  return (dateText || chinaDateKey()).slice(0, 7);
}

function moveCalendarMonth(offset) {
  const [yearText, monthText] = (state.visibleCalendarMonth || monthKeyFromDate(state.selectedDiaryDate)).split("-");
  const year = Number(yearText);
  const monthIndex = Number(monthText) - 1;
  const next = new Date(year, monthIndex + offset, 1);
  state.visibleCalendarMonth = `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, "0")}`;
  renderCalendar();
}

function renderCalendar() {
  const monthKey = state.visibleCalendarMonth || monthKeyFromDate(state.selectedDiaryDate);
  state.visibleCalendarMonth = monthKey;
  const [yearText, monthText] = monthKey.split("-");
  const year = Number(yearText);
  const monthIndex = Number(monthText) - 1;
  const monthStart = new Date(year, monthIndex, 1);
  const monthEnd = new Date(year, monthIndex + 1, 0);
  const leading = (monthStart.getDay() + 6) % 7;
  const totalCells = Math.ceil((leading + monthEnd.getDate()) / 7) * 7;
  const today = chinaDateKey();
  const dateSet = new Set(state.diaryDates);

  els.calendarMonthLabel.textContent = `${year}年${monthIndex + 1}月`;
  els.calendarGrid.innerHTML = "";
  els.diaryDateCount.textContent = `${state.diaryDates.length} 天`;

  for (let cellIndex = 0; cellIndex < totalCells; cellIndex += 1) {
    const cellDate = new Date(year, monthIndex, cellIndex - leading + 1);
    const dateText = `${cellDate.getFullYear()}-${String(cellDate.getMonth() + 1).padStart(2, "0")}-${String(cellDate.getDate()).padStart(2, "0")}`;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "calendar-day";
    if (cellDate.getMonth() !== monthIndex) {
      button.classList.add("is-outside");
    }
    if (dateText === state.selectedDiaryDate) {
      button.classList.add("is-active");
    }
    if (dateText === today) {
      button.classList.add("is-today");
    }
    if (dateSet.has(dateText)) {
      button.classList.add("has-entry");
    }
    button.textContent = String(cellDate.getDate());
    button.addEventListener("click", () => {
      if (dateSet.has(dateText) || dateText === today) {
        loadDiary(dateText);
      }
    });
    els.calendarGrid.appendChild(button);
  }
}

function renderFeatureList(target, meta, values) {
  if (!target) {
    return;
  }
  target.innerHTML = "";
  meta.forEach(([key, label, help]) => {
    const item = document.createElement("div");
    item.className = "feature-item";
    item.innerHTML = `
      <div class="feature-main">
        <span class="feature-name">${label}</span>
        <span class="feature-help">${help}</span>
      </div>
      <strong class="feature-value">${Number(values?.[key] ?? 0).toFixed(2)}</strong>
    `;
    target.appendChild(item);
  });
}

function setJournalMode(mode) {
  state.journalMode = mode;
  const isAi = mode === "ai";
  els.journalAiTab.classList.toggle("is-active", isAi);
  els.journalUserTab.classList.toggle("is-active", !isAi);
  els.aiDiary.classList.toggle("is-active", isAi);
  els.userDiary.classList.toggle("is-active", !isAi);
  els.journalHint.textContent = isAi
    ? "云雀的用户观察记录。"
    : "编辑或查看用户日记。";
}

function appendDiaryText(parent, className, text) {
  const node = document.createElement("p");
  node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function appendDiarySection(parent, title, items) {
  if (!items?.length) {
    return;
  }
  const section = document.createElement("section");
  section.className = "ai-diary-section";
  const heading = document.createElement("h4");
  heading.textContent = title;
  section.appendChild(heading);
  const list = document.createElement("ul");
  items.forEach((item) => {
    const row = document.createElement("li");
    const id = document.createElement("span");
    id.className = "ai-diary-item-id";
    id.textContent = item?.id || "-";
    const content = document.createElement("span");
    content.textContent = item?.content || String(item || "");
    row.append(id, content);
    list.appendChild(row);
  });
  section.appendChild(list);
  parent.appendChild(section);
}

function renderStructuredAiDiary(container, selected) {
  const structured = selected.ai_structured || {};
  const summary = structured.summary || {};
  const content = structured.content || {};
  container.innerHTML = "";
  const article = document.createElement("article");
  article.className = "ai-diary-template";

  const title = document.createElement("h3");
  title.textContent = `AI记 ${selected.date || structured.date || ""}`;
  article.appendChild(title);
  appendDiaryText(article, "ai-diary-intro", "今天聊完之后，云雀想先把对你的理解记下来。如果哪里不对，你直接改我就好。");

  const summarySection = document.createElement("section");
  summarySection.className = "ai-diary-section ai-diary-summary";
  const summaryTitle = document.createElement("h4");
  summaryTitle.textContent = "今天的整体感觉";
  summarySection.appendChild(summaryTitle);
  appendDiaryText(summarySection, "ai-diary-summary-text", summary.overall_state || "云雀今天还没有足够的状态线索。");
  appendDiaryText(
    summarySection,
    "ai-diary-emotion-line",
    `主情绪：${summary.emotion_label || "中性"} · valence ${Number(summary.valence || 0).toFixed(2)} · arousal ${Number(summary.arousal || 0).toFixed(2)}`
  );
  article.appendChild(summarySection);

  appendDiarySection(article, "云雀觉得今天比较重要的事", content.events || []);
  appendDiarySection(article, "云雀观察到的状态模式", content.routines || []);
  appendDiarySection(article, "云雀现在记下来的你的偏好", content.preferences || []);
  appendDiarySection(article, "云雀留意到的关系线索", content.relationships || []);

  const help = document.createElement("section");
  help.className = "ai-diary-section ai-diary-help";
  const helpTitle = document.createElement("h4");
  helpTitle.textContent = "如果云雀理解错了";
  help.appendChild(helpTitle);
  ["“P1 不对，应改成……”", "“E2 可以删掉”", "“补充一条偏好：……”"].forEach((text) => {
    appendDiaryText(help, "ai-diary-help-line", text);
  });
  article.appendChild(help);
  container.appendChild(article);
}

function renderAiDiaryState(selected) {
  const placeholder = selected.ai_placeholder || "云雀正在努力总结中...";
  els.aiDiary.classList.toggle("is-structured", Boolean(selected.ai_structured));
  if (selected.ai_structured) {
    renderStructuredAiDiary(els.aiDiary, selected);
  } else {
    els.aiDiary.textContent = selected.ai_markdown || placeholder;
  }
  const canReview = Boolean(selected.ai_review_available);
  if (els.aiDiaryActions) {
    els.aiDiaryActions.hidden = !canReview;
  }
  if (canReview) {
    els.diaryEditState.textContent = "AI记待确认";
  } else if (selected.ai_status === "confirmed") {
    els.diaryEditState.textContent = "AI记已确认";
  } else if (selected.ai_status === "corrected") {
    els.diaryEditState.textContent = "AI记已修正";
  } else {
    els.diaryEditState.textContent = selected.is_today ? "今日日记" : "历史日记";
  }
}

function renderDiarySelection(payload) {
  const selected = payload.selected;
  state.diaryDates = payload.dates || [];
  state.selectedDiaryDate = selected.date;
  state.selectedDiaryIsToday = Boolean(selected.is_today);
  state.visibleCalendarMonth = monthKeyFromDate(selected.date);
  renderCalendar();
  els.diarySelectedDate.textContent = formatDiaryDate(selected.date);
  els.userDiary.readOnly = false;
  els.userDiary.value = selected.user_markdown || "";
  renderAiDiaryState(selected);
}

async function loadDiary(dateText = "") {
  try {
    const query = dateText ? `?date=${encodeURIComponent(dateText)}` : "";
    const response = await fetch(apiUrl(`/api/diary${query}`), { credentials: "include" });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    renderDiarySelection(payload);
  } catch (error) {
    els.aiDiary.textContent = "日记文件读取失败，请稍后重试。";
  }
}

async function saveUserDiary() {
  try {
    const response = await fetch(apiUrl("/api/diary/user"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: state.selectedDiaryDate, markdown: els.userDiary.value }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    renderDiarySelection(payload);
    els.diaryEditState.textContent = "用户日记已保存";
  } catch (error) {
    els.diaryEditState.textContent = "用户日记保存失败";
  }
}

function scheduleUserDiarySave() {
  if (state.diarySaveTimer) {
    window.clearTimeout(state.diarySaveTimer);
  }
  state.diarySaveTimer = window.setTimeout(saveUserDiary, 500);
}

async function refreshAiDiary() {
  if (!state.selectedDiaryIsToday || !state.selectedDiaryDate) {
    return;
  }
  try {
    const response = await fetch(apiUrl(`/api/diary?date=${encodeURIComponent(state.selectedDiaryDate)}`), {
      credentials: "include",
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    renderDiarySelection(payload);
  } catch (error) {
    return;
  }
}

function startDiaryRefreshLoop() {
  if (state.diaryRefreshTimer) {
    window.clearInterval(state.diaryRefreshTimer);
  }
  state.diaryRefreshTimer = window.setInterval(refreshAiDiary, 15000);
}

function openAiDiaryCorrectionModal() {
  els.aiDiaryCorrectionInput.value = "";
  els.aiDiaryCorrectionModal.hidden = false;
  window.setTimeout(() => els.aiDiaryCorrectionInput.focus(), 0);
}

function closeAiDiaryCorrectionModal() {
  els.aiDiaryCorrectionModal.hidden = true;
  els.aiDiaryCorrectionInput.value = "";
}

async function submitAiDiaryReview(action, correction = "") {
  if (!state.selectedDiaryDate) {
    return;
  }
  try {
    const response = await fetch(apiUrl("/api/diary/review"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        date: state.selectedDiaryDate,
        action,
        correction,
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const payload = await response.json();
    if (!payload.ok) {
      throw new Error(payload.error || "review_failed");
    }
    renderDiarySelection(payload);
    els.diaryEditState.textContent = action === "correct" ? "AI记修改已提交" : "AI记已确认";
    closeAiDiaryCorrectionModal();
  } catch (error) {
    els.diaryEditState.textContent = "AI记确认失败";
  }
}

function styleFromValence(valence) {
  if (valence >= 0.28) {
    return "conic-gradient(from 20deg, #78d69b, #4cc6cf, #ffd071, #78d69b)";
  }
  if (valence <= -0.28) {
    return "conic-gradient(from 20deg, #ff6f6f, #ff8a5b, #ffd071, #ff6f6f)";
  }
  return "conic-gradient(from 20deg, #4cc6cf, #8fd4ff, #ffd071, #4cc6cf)";
}

async function pingBackend() {
  try {
    const response = await fetch(apiUrl("/api/analyze"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "", audio: {}, video: {}, history: [], timestamp: chinaTimestamp() }),
    });
    els.backendStatus.textContent = response.ok ? "后端已连接" : "后端不可用";
  } catch (error) {
    els.backendStatus.textContent = "后端不可用";
  }
}

async function toggleCapture() {
  if (state.stream) {
    stopCapture();
    return;
  }

  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: true,
    });
  } catch (error) {
    els.captureStatus.textContent = "权限被拒绝";
    return;
  }

  els.video.srcObject = state.stream;
  els.captureStatus.textContent = "多模态采集中";
  els.videoBadge.textContent = "视频采集中";
  els.audioBadge.textContent = "音频采集中";
  els.toggleCapture.textContent = "停止采集";
  setupAudioPipeline(state.stream);
  startRawMediaRecorder(state.stream);
  startSpeechRecognition();
  await ensureFaceLandmarker();
  startFeatureLoop();
  state.lastInteractionAt = Date.now();
  state.lastUserInteractionAt = Date.now();
  resetProactiveIdleSchedule(state.lastUserInteractionAt);
  state.lastEmotionComputedAt = Date.now();
  state.lastPeriodicEmotionAt = 0;
  startEmotionMonitorLoop();
}

function stopCapture() {
  if (state.stream) {
    stopRawMediaRecorder();
    stopSpeechRecognition();
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
  }
  if (state.audioContext) {
    state.audioContext.close();
    state.audioContext = null;
  }
  state.analyser = null;
  state.lastVideoTime = -1;
  previousSpectrum = [];
  previousFrame = null;
  state.audioStats.available = false;
  state.videoStats.available = false;
  if (state.captureLoopTimer) {
    window.clearInterval(state.captureLoopTimer);
    state.captureLoopTimer = null;
  }
  state.proactivePending = false;
  els.video.srcObject = null;
  els.captureStatus.textContent = "采集已停止";
  els.videoBadge.textContent = "视频未启动";
  els.audioBadge.textContent = "音频未启动";
  els.toggleCapture.textContent = "开始采集";
}

function setupAudioPipeline(stream) {
  const AudioContextClass = window.AudioContext || window.webkitAudioContext;
  state.audioContext = new AudioContextClass();
  state.source = state.audioContext.createMediaStreamSource(stream);
  state.analyser = state.audioContext.createAnalyser();
  state.analyser.fftSize = 1024;
  state.source.connect(state.analyser);
}

function chooseMediaRecorderMimeType() {
  const candidates = [
    "video/webm;codecs=vp8,opus",
    "video/webm",
    "audio/webm;codecs=opus",
    "audio/webm",
  ];
  return candidates.find((type) => window.MediaRecorder?.isTypeSupported(type)) || "";
}

function startRawMediaRecorder(stream) {
  if (!window.MediaRecorder) {
    return;
  }
  const mimeType = chooseMediaRecorderMimeType();
  const options = mimeType ? { mimeType } : {};
  try {
    state.recordedChunks = [];
    state.mediaRecorder = new MediaRecorder(stream, options);
    state.mediaRecorder.addEventListener("dataavailable", (event) => {
      if (event.data?.size) {
        state.recordedChunks.push(event.data);
        state.recordedChunks = state.recordedChunks.slice(-6);
      }
    });
    state.mediaRecorder.start(1000);
  } catch (error) {
    state.mediaRecorder = null;
    state.recordedChunks = [];
  }
}

function stopRawMediaRecorder() {
  if (state.mediaRecorder && state.mediaRecorder.state !== "inactive") {
    state.mediaRecorder.stop();
  }
  state.mediaRecorder = null;
  state.recordedChunks = [];
}

function startSpeechRecognition() {
  const SpeechRecognitionClass = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognitionClass) {
    return;
  }
  try {
    state.speechRecognition = new SpeechRecognitionClass();
    state.speechRecognition.lang = "zh-CN";
    state.speechRecognition.continuous = true;
    state.speechRecognition.interimResults = false;
    state.speechRecognition.addEventListener("result", (event) => {
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const transcript = event.results[index]?.[0]?.transcript?.trim();
        if (transcript) {
          state.speechTranscript = `${state.speechTranscript} ${transcript}`.trim();
        }
      }
      maybeReplyToSpeechTranscript();
    });
    state.speechRecognition.start();
  } catch (error) {
    state.speechRecognition = null;
  }
}

function stopSpeechRecognition() {
  if (state.speechRecognition) {
    state.speechRecognition.stop();
  }
  state.speechRecognition = null;
  state.speechTranscript = "";
}

function consumeSpeechTranscript() {
  const transcript = state.speechTranscript.trim();
  state.speechTranscript = "";
  return transcript;
}

function clearPendingSpeechReply(resetTranscript = false) {
  if (state.speechReplyTimer) {
    window.clearTimeout(state.speechReplyTimer);
    state.speechReplyTimer = null;
  }
  state.speechReplyPending = false;
  if (resetTranscript) {
    state.speechTranscript = "";
  }
}

function hasClearSemanticText(text) {
  const normalized = (text || "").replace(/\s+/g, "");
  if (normalized.length < 2) {
    return false;
  }
  return !["嗯", "啊", "呃", "哦", "喂"].includes(normalized);
}

function maybeReplyToSpeechTranscript() {
  if (state.speechReplyPending || state.chatRequestPending || els.messageInput.value.trim()) {
    return;
  }
  if (!hasClearSemanticText(state.speechTranscript)) {
    return;
  }
  state.speechReplyPending = true;
  state.speechReplyTimer = window.setTimeout(async () => {
    state.speechReplyTimer = null;
    if (state.chatRequestPending || els.messageInput.value.trim()) {
      state.speechReplyPending = false;
      return;
    }
    const transcript = consumeSpeechTranscript();
    if (!hasClearSemanticText(transcript)) {
      state.speechReplyPending = false;
      return;
    }
    addBubble("user", transcript);
    const typingBubble = addTypingBubble();
    state.lastUserInteractionAt = Date.now();
    state.lastInteractionAt = Date.now();
    resetProactiveIdleSchedule(state.lastUserInteractionAt);
    try {
      const result = await sendMessage("", { transcript });
      state.proactiveCooldownUntil = Date.now() + PROACTIVE_COOLDOWN_MS;
      typingBubble.remove();
      addBubble("assistant", result.agent.reply);
    } catch (error) {
      typingBubble.remove();
      addBubble("assistant", "后端请求失败了，请稍后再试一次。");
      els.agentStatus.textContent = "请求失败";
    } finally {
      state.speechReplyPending = false;
    }
  }, 250);
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

async function buildRecentMediaPayload() {
  if (!state.recordedChunks.length) {
    return {};
  }
  const type = state.recordedChunks[0].type || "video/webm";
  const blob = new Blob(state.recordedChunks, { type });
  if (!blob.size) {
    return {};
  }
  return { video_data: await blobToDataUrl(blob) };
}

function captureAudioFeatures() {
  if (!state.analyser) {
    return;
  }

  const length = state.analyser.frequencyBinCount;
  const spectrum = new Uint8Array(length);
  const waveform = new Uint8Array(length);
  state.analyser.getByteFrequencyData(spectrum);
  state.analyser.getByteTimeDomainData(waveform);

  const normalized = Array.from(spectrum, (value) => value / 255);
  const volume = normalized.reduce((sum, value) => sum + value, 0) / normalized.length;
  const peak = Math.max(...normalized);
  const rms = Math.sqrt(normalized.reduce((sum, value) => sum + value * value, 0) / normalized.length);
  let weighted = 0;
  let weightSum = 0;
  normalized.forEach((value, index) => {
    weighted += value * index;
    weightSum += value;
  });
  const centroid = weightSum ? clamp(weighted / weightSum / normalized.length, 0, 1) : 0;
  const rolloffIndex = normalized.findIndex((value) => value > peak * 0.85);
  const rolloff = rolloffIndex < 0 ? 0 : clamp(rolloffIndex / normalized.length, 0, 1);

  let flux = 0;
  if (previousSpectrum.length === normalized.length) {
    normalized.forEach((value, index) => {
      flux += Math.abs(value - previousSpectrum[index]);
    });
    flux /= normalized.length;
  }

  let zcr = 0;
  for (let index = 1; index < waveform.length; index += 1) {
    const prev = waveform[index - 1] - 128;
    const current = waveform[index] - 128;
    if ((prev >= 0 && current < 0) || (prev < 0 && current >= 0)) {
      zcr += 1;
    }
  }
  zcr = clamp(zcr / waveform.length, 0, 1);

  const flatness = clamp(
    normalized.reduce((sum, value) => sum + Math.log(value + 1e-6), 0) / normalized.length + 6,
    0,
    1,
  );
  const spread = clamp(
    Math.sqrt(normalized.reduce((sum, value) => sum + (value - volume) ** 2, 0) / normalized.length) * 2,
    0,
    1,
  );
  const dynamicRange = clamp(peak - Math.min(...normalized), 0, 1);
  const pitch = clamp(1 - zcr + centroid * 0.4, 0, 1);

  previousSpectrum = normalized;
  state.audioStats = {
    volume: clamp(volume, 0, 1),
    peak: clamp(peak, 0, 1),
    centroid,
    flux: clamp(flux * 2.6, 0, 1),
    zcr,
    rms,
    pitch,
    rolloff,
    flatness,
    spread,
    dynamicRange,
    available: true,
  };

}

function captureVideoFeatures() {
  if (!state.stream || els.video.readyState < 2) {
    return;
  }

  const canvas = els.frameCanvas;
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(els.video, 0, 0, canvas.width, canvas.height);
  const frame = ctx.getImageData(0, 0, canvas.width, canvas.height).data;

  let brightnessSum = 0;
  let contrastSum = 0;
  let motionSum = 0;
  let satSum = 0;
  let warmSum = 0;
  const luminances = [];

  for (let index = 0; index < frame.length; index += 16) {
    const r = frame[index];
    const g = frame[index + 1];
    const b = frame[index + 2];
    const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
    brightnessSum += lum;
    luminances.push(lum);
    const maxColor = Math.max(r, g, b);
    const minColor = Math.min(r, g, b);
    satSum += (maxColor - minColor) / 255;
    warmSum += clamp((r - b + 255) / 510, 0, 1);

    if (previousFrame) {
      motionSum += Math.abs(lum - previousFrame[index] / 255);
    }
  }

  const brightness = brightnessSum / luminances.length;
  for (const value of luminances) {
    contrastSum += Math.abs(value - brightness);
  }

  const contrast = clamp((contrastSum / luminances.length) * 2.5, 0, 1);
  const motion = clamp((motionSum / luminances.length) * 3.2, 0, 1);
  const saturation = clamp(satSum / luminances.length, 0, 1);
  const warmth = clamp(warmSum / luminances.length, 0, 1);
  const faceFocus = clamp(0.55 * (1 - Math.abs(brightness - 0.56)) + contrast * 0.45, 0, 1);
  const symmetry = clamp(1 - Math.abs(brightness - 0.5) * 1.8, 0, 1);
  const stability = clamp(1 - motion, 0, 1);
  let smile = 0;
  let frown = 0;
  let mouthOpen = 0;
  let browRaise = 0;
  let eyeWiden = 0;
  let jawOpen = 0;
  let cheekRaise = 0;
  let squint = 0;

  if (state.faceLandmarker && els.video.currentTime !== state.lastVideoTime) {
    state.lastVideoTime = els.video.currentTime;
    const result = state.faceLandmarker.detectForVideo(els.video, performance.now());
    const categories = result.faceBlendshapes?.[0]?.categories ?? [];
    if (categories.length) {
      smile = getBlendshapeScore(categories, ["mouthSmileLeft", "mouthSmileRight"]);
      frown = getBlendshapeScore(categories, ["mouthFrownLeft", "mouthFrownRight", "browDownLeft", "browDownRight"]);
      mouthOpen = getBlendshapeScore(categories, ["mouthOpen", "mouthPucker", "mouthShrugUpper"]);
      browRaise = getBlendshapeScore(categories, ["browOuterUpLeft", "browOuterUpRight", "browInnerUp"]);
      eyeWiden = getBlendshapeScore(categories, ["eyeWideLeft", "eyeWideRight"]);
      jawOpen = getBlendshapeScore(categories, ["jawOpen"]);
      cheekRaise = getBlendshapeScore(categories, ["cheekSquintLeft", "cheekSquintRight"]);
      squint = getBlendshapeScore(categories, ["eyeSquintLeft", "eyeSquintRight"]);
      els.videoBadge.textContent = `表情识别中 笑容 ${smile.toFixed(2)} 皱眉 ${frown.toFixed(2)}`;
    }
  }

  previousFrame = frame.slice();
  state.videoStats = {
    brightness,
    motion,
    contrast,
    faceFocus,
    smile,
    frown,
    mouthOpen,
    browRaise,
    eyeWiden,
    jawOpen,
    cheekRaise,
    squint,
    saturation,
    warmth,
    symmetry,
    stability,
    available: true,
  };

}

function renderBars(items) {
  els.emotionBars.innerHTML = "";
  items.forEach((item) => {
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.innerHTML = `
      <div class="bar-head"><span>${item.name}</span><strong>${item.value.toFixed(2)}</strong></div>
      <div class="bar-track"><div class="bar-fill" style="width:${item.value * 100}%"></div></div>
    `;
    els.emotionBars.appendChild(bar);
  });
}

function updateDashboard(result) {
  const emotion = result.emotion;
  els.agentStatus.textContent = result.agent.source === "none" ? "情绪已更新" : "云雀已回应";

  els.emotionLabel.textContent = emotion.label;
  els.fusionScore.textContent = result.scores.fusion.toFixed(2);
  els.valenceValue.textContent = emotion.valence.toFixed(2);
  els.arousalValue.textContent = emotion.arousal.toFixed(2);
  els.fusionRaw.textContent = result.scores.fusion.toFixed(2);
  els.textRaw.textContent = result.scores.text.toFixed(2);
  els.audioRaw.textContent = result.scores.audio.toFixed(2);
  els.videoRaw.textContent = result.scores.video.toFixed(2);
  els.emotionRing.style.background = styleFromValence(emotion.valence);

  state.lastEmotionComputedAt = Date.now();

  renderBars(result.emotion_bars);
  renderFeatureList(els.audioFeatureList, AUDIO_FEATURE_META, result.media_features?.audio || {});
  renderFeatureList(els.videoFeatureList, VIDEO_FEATURE_META, result.media_features?.video || {});
  if (result.memory) {
    if (!state.selectedDiaryDate || result.memory.date === state.selectedDiaryDate || state.selectedDiaryIsToday) {
      state.selectedDiaryDate = result.memory.date;
      state.selectedDiaryIsToday = Boolean(result.memory.is_today);
      if (!state.diaryDates.includes(result.memory.date)) {
        state.diaryDates = [result.memory.date, ...state.diaryDates].sort((a, b) => b.localeCompare(a));
      }
      state.visibleCalendarMonth = monthKeyFromDate(result.memory.date);
      renderCalendar();
      els.diarySelectedDate.textContent = formatDiaryDate(result.memory.date);
      renderAiDiaryState(result.memory);
      if (document.activeElement !== els.userDiary) {
        els.userDiary.value = result.memory.user_markdown || "";
      }
    }
  }
}

async function sendMessage(message, options = {}) {
  if (state.chatRequestPending) {
    throw new Error("chat_request_pending");
  }
  state.chatRequestPending = true;
  state.chatRequestPromise = (async () => {
    captureAudioFeatures();
    captureVideoFeatures();
    try {
      const media = await buildRecentMediaPayload();
      const transcript = options.transcript || (message ? "" : consumeSpeechTranscript());
      const visibleUserText = message || transcript;

      const payload = {
        message,
        transcript,
        proactive_reason: options.proactiveReason || "",
        history: recentContextHistory(),
        audio: {},
        video: {},
        ...media,
        timestamp: chinaTimestamp(),
      };

      els.agentStatus.textContent = "云雀思考中";
      const response = await fetch(apiUrl("/api/chat"), {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const result = await response.json();
      if (Array.isArray(result.chat_history)) {
        syncChatHistoryFromResult(result);
      } else {
        if (visibleUserText) {
          state.history.push({ role: "user", content: visibleUserText });
        }
        if (result.agent.reply) {
          state.history.push({ role: "assistant", content: result.agent.reply });
        }
        saveChatHistory();
      }
      state.lastInteractionAt = Date.now();
      if (visibleUserText) {
        state.lastUserInteractionAt = Date.now();
        state.lastPeriodicEmotionAt = 0;
        resetProactiveIdleSchedule(state.lastUserInteractionAt);
      }
      updateDashboard(result);
      return result;
    } finally {
      state.chatRequestPending = false;
      state.chatRequestPromise = null;
    }
  })();
  return state.chatRequestPromise;
}

async function computeEmotionOnly(reason = "periodic") {
  if (!state.stream || state.emotionRequestPending || state.chatRequestPending) {
    return null;
  }
  state.emotionRequestPending = true;
  captureAudioFeatures();
  captureVideoFeatures();
  const media = await buildRecentMediaPayload();
  try {
    const response = await fetch(apiUrl("/api/analyze"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "",
        transcript: "",
        analyze_reason: reason,
        history: recentContextHistory(),
        audio: {},
        video: {},
        ...media,
        timestamp: chinaTimestamp(),
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const result = await response.json();
    state.lastPeriodicEmotionAt = Date.now();
    updateDashboard(result);
    return result;
  } catch (error) {
    return null;
  } finally {
    state.emotionRequestPending = false;
  }
}

async function checkEmotionSchedule() {
  if (!state.stream || state.proactivePending || state.emotionRequestPending || state.chatRequestPending) {
    return;
  }
  if (els.messageInput.value.trim()) {
    return;
  }
  if (hasClearSemanticText(state.speechTranscript)) {
    maybeReplyToSpeechTranscript();
    return;
  }
  const now = Date.now();
  const lastComputedAt = state.lastEmotionComputedAt || state.lastUserInteractionAt || state.lastInteractionAt || 0;
  if (state.lastPeriodicEmotionAt) {
    if (now - state.lastPeriodicEmotionAt < EMOTION_PERIODIC_INTERVAL_MS) {
      return;
    }
  } else if (!lastComputedAt || now - lastComputedAt < EMOTION_IDLE_DELAY_MS) {
    return;
  }
  const result = await computeEmotionOnly("idle_periodic");
  if (result?.emotion_state?.significant_change) {
    resetProactiveIdleSchedule(Date.now());
    await triggerProactiveReply("emotion_shift");
  }
}

async function checkIdleProactiveReply() {
  if (state.proactivePending || state.chatRequestPending || els.messageInput.value.trim()) {
    return;
  }
  const now = Date.now();
  const lastUserAt = state.lastUserInteractionAt || state.lastInteractionAt || now;
  if (!state.nextIdleProactiveAt) {
    resetProactiveIdleSchedule(lastUserAt);
  }
  if (now >= state.nextIdleProactiveAt) {
    await triggerProactiveReply(`idle_${Math.round(proactiveIdleDelay() / 60000)}m`);
  }
}

async function triggerProactiveReply(reason = "idle") {
  if (state.proactivePending || state.chatRequestPending) {
    return;
  }
  if (els.messageInput.value.trim()) {
    return;
  }
  const now = Date.now();
  if (now < state.proactiveCooldownUntil) {
    return;
  }
  if (now - state.lastProactiveAt < PROACTIVE_COOLDOWN_MS) {
    return;
  }

  if (state.stream) {
    captureAudioFeatures();
    captureVideoFeatures();
  }
  const media = state.stream ? await buildRecentMediaPayload() : {};
  state.proactivePending = true;
  els.agentStatus.textContent = "云雀正在输入";
  const typingBubble = addTypingBubble();

  try {
    const response = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "",
        transcript: consumeSpeechTranscript(),
        proactive: true,
        proactive_reason: reason,
        history: recentContextHistory(),
        audio: {},
        video: {},
        ...media,
        timestamp: chinaTimestamp(),
      }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const result = await response.json();
    if (Array.isArray(result.chat_history)) {
      syncChatHistoryFromResult(result);
    } else if (result.agent.reply) {
      state.history.push({ role: "assistant", content: result.agent.reply });
      saveChatHistory();
    }
    state.lastInteractionAt = Date.now();
    state.lastProactiveAt = Date.now();
    state.proactiveCooldownUntil = Date.now() + PROACTIVE_COOLDOWN_MS;
    updateDashboard(result);
    typingBubble.remove();
    if (result.agent.reply) {
      addBubble("assistant", result.agent.reply);
    }
    if (reason === "emotion_shift") {
      resetProactiveIdleSchedule(Date.now());
    } else if (reason.startsWith("idle_")) {
      advanceProactiveIdleSchedule(Date.now());
    }
  } catch (error) {
    typingBubble.remove();
  } finally {
    state.proactivePending = false;
  }
}

function startEmotionMonitorLoop() {
  if (state.proactiveTimer) {
    window.clearInterval(state.proactiveTimer);
  }
  state.proactiveTimer = window.setInterval(() => {
    checkEmotionSchedule();
    checkIdleProactiveReply();
  }, EMOTION_MONITOR_INTERVAL_MS);
}

function startFeatureLoop() {
  if (state.captureLoopTimer) {
    window.clearInterval(state.captureLoopTimer);
  }

  const refreshFeatures = () => {
    if (!state.stream) {
      return;
    }
    captureAudioFeatures();
    captureVideoFeatures();
  };

  refreshFeatures();
  state.captureLoopTimer = window.setInterval(refreshFeatures, 400);
}

els.toggleCapture.addEventListener("click", toggleCapture);
els.clearDataButton?.addEventListener("click", clearUserData);
els.enterAppButton?.addEventListener("click", enterApp);
els.authToggleButton?.addEventListener("click", () => {
  if (!state.authUser) {
    setAuthPopover(els.authForm?.hidden);
    els.authUsername?.focus();
  }
});
els.authForm?.addEventListener("submit", (event) => {
  event.preventDefault();
  submitAuth("login");
});
els.authRegisterButton?.addEventListener("click", () => submitAuth("register"));
els.sidebarEmotionTab?.addEventListener("click", () => setSidebarView("emotion"));
els.sidebarDiaryTab?.addEventListener("click", () => setSidebarView("diary"));
els.userDiary.addEventListener("input", scheduleUserDiarySave);
els.calendarPrev.addEventListener("click", () => moveCalendarMonth(-1));
els.calendarNext.addEventListener("click", () => moveCalendarMonth(1));
els.journalAiTab.addEventListener("click", () => setJournalMode("ai"));
els.journalUserTab.addEventListener("click", () => setJournalMode("user"));
els.aiDiaryConfirmButton?.addEventListener("click", () => submitAiDiaryReview("confirm"));
els.aiDiaryCorrectButton?.addEventListener("click", openAiDiaryCorrectionModal);
els.aiDiaryCorrectionCancel?.addEventListener("click", closeAiDiaryCorrectionModal);
els.aiDiaryCorrectionModal?.addEventListener("click", (event) => {
  if (event.target === els.aiDiaryCorrectionModal) {
    closeAiDiaryCorrectionModal();
  }
});
els.aiDiaryCorrectionSubmit?.addEventListener("click", () => {
  const correction = els.aiDiaryCorrectionInput.value.trim();
  if (!correction) {
    els.diaryEditState.textContent = "请先填写修改意见";
    els.aiDiaryCorrectionInput.focus();
    return;
  }
  submitAiDiaryReview("correct", correction);
});
els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.chatRequestPending) {
    try {
      await state.chatRequestPromise;
    } catch (error) {
      // 等待上一条回复结束，不在这里额外提示失败。
    }
  }
  const message = els.messageInput.value.trim();
  if (!message) {
    return;
  }
  clearPendingSpeechReply(true);

  addBubble("user", message);
  els.messageInput.value = "";
  const typingBubble = addTypingBubble();
  state.lastInteractionAt = Date.now();
  state.lastUserInteractionAt = Date.now();
  resetProactiveIdleSchedule(state.lastUserInteractionAt);

  try {
    const result = await sendMessage(message);
    state.proactiveCooldownUntil = Date.now() + PROACTIVE_COOLDOWN_MS;
    typingBubble.remove();
    addBubble("assistant", result.agent.reply);
  } catch (error) {
    typingBubble.remove();
    addBubble("assistant", "后端请求失败了，请稍后再试一次。");
    els.agentStatus.textContent = "请求失败";
  }
});

window.addEventListener("beforeunload", stopCapture);

setJournalMode("ai");
setSidebarView("emotion");
renderChatHistory();
renderFeatureList(els.audioFeatureList, AUDIO_FEATURE_META, {});
renderFeatureList(els.videoFeatureList, VIDEO_FEATURE_META, {});
loadCurrentUser().then(async () => {
  if (!authRequired() || state.authUser) {
    await loadChatHistory();
    renderChatHistory();
    loadDiary();
    startDiaryRefreshLoop();
    pingBackend();
  } else {
    els.backendStatus.textContent = "请先登录";
  }
  if (shouldOpenChatDirectly()) {
    enterApp();
  }
});
