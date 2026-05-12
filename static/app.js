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
  speechReplyPending: false,
  proactivePending: false,
  proactiveCooldownUntil: 0,
  lastProactiveAt: 0,
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
  appShell: document.getElementById("appShell"),
  backendStatus: document.getElementById("backendStatus"),
  captureStatus: document.getElementById("captureStatus"),
  agentStatus: document.getElementById("agentStatus"),
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
const PROACTIVE_IDLE_MS = 120000;
const PROACTIVE_COOLDOWN_MS = 120000;
const EMOTION_MONITOR_INTERVAL_MS = 1000;
const CHAT_HISTORY_STORAGE_KEY = "yunque.chat.history.v1";
const MAX_STORED_CHAT_MESSAGES = 80;

function resolveApiBase() {
  if (["127.0.0.1", "localhost", "::1", "0.0.0.0"].includes(window.location.hostname)) {
    return window.location.origin.replace(/\/$/, "");
  }
  const metaBase = document.querySelector('meta[name="app-api-base"]')?.content?.trim() || "";
  if (metaBase) {
    return metaBase.replace(/\/$/, "");
  }
  return window.location.origin.replace(/\/$/, "");
}

function apiUrl(path) {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${normalizedPath}`;
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
  if (els.introScreen) {
    els.introScreen.style.display = "none";
  }
  if (els.appShell) {
    els.appShell.classList.remove("app-shell-hidden");
  }
  if (!state.lastUserInteractionAt && !state.lastInteractionAt) {
    state.lastUserInteractionAt = Date.now();
    state.lastInteractionAt = state.lastUserInteractionAt;
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
  return normalizeChatRole(role) === "assistant" ? "Agent" : "User";
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
  if (state.history.length > MAX_STORED_CHAT_MESSAGES) {
    state.history = state.history.slice(-MAX_STORED_CHAT_MESSAGES);
  }
}

function saveChatHistory() {
  try {
    pruneChatHistory();
    window.localStorage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify(state.history));
  } catch (error) {
    // 本地存储不可用时不影响聊天主流程。
  }
}

function loadChatHistory() {
  try {
    const raw = window.localStorage.getItem(CHAT_HISTORY_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    state.history = Array.isArray(parsed) ? parsed.map(normalizeHistoryItem).filter(Boolean) : [];
    pruneChatHistory();
  } catch (error) {
    state.history = [];
  }
}

function renderChatHistory() {
  els.chatList.innerHTML = "";
  if (!state.history.length) {
    addBubble("assistant", "我已经准备好啦！你可以输入想和我说的话，我会结合多模态来回应你。");
    return;
  }
  state.history.forEach((item) => addBubble(item.role, item.content));
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
    <div class="bubble-role">Agent</div>
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
    ? "云雀写下的用户观察记录。"
    : "编辑或查看当前日期对应的用户日记。";
}

function renderDiarySelection(payload) {
  const selected = payload.selected;
  state.diaryDates = payload.dates || [];
  state.selectedDiaryDate = selected.date;
  state.selectedDiaryIsToday = Boolean(selected.is_today);
  state.visibleCalendarMonth = monthKeyFromDate(selected.date);
  renderCalendar();
  els.diarySelectedDate.textContent = formatDiaryDate(selected.date);
  els.diaryEditState.textContent = selected.is_today ? "今日日记" : "历史日记";
  els.userDiary.readOnly = false;
  els.userDiary.value = selected.user_markdown || "";
  els.aiDiary.textContent = selected.ai_markdown || "AI 记忆会根据对话和当前状态自动更新。";
}

async function loadDiary(dateText = "") {
  try {
    const query = dateText ? `?date=${encodeURIComponent(dateText)}` : "";
    const response = await fetch(apiUrl(`/api/diary${query}`));
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
    const response = await fetch(apiUrl(`/api/diary?date=${encodeURIComponent(state.selectedDiaryDate)}`));
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
  window.setTimeout(async () => {
    const transcript = consumeSpeechTranscript();
    if (!hasClearSemanticText(transcript)) {
      state.speechReplyPending = false;
      return;
    }
    addBubble("user", transcript);
    const typingBubble = addTypingBubble();
    state.lastUserInteractionAt = Date.now();
    state.lastInteractionAt = Date.now();
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
    if (!state.selectedDiaryDate || result.memory.date === state.selectedDiaryDate) {
      state.selectedDiaryDate = result.memory.date;
      state.selectedDiaryIsToday = Boolean(result.memory.is_today);
      if (!state.diaryDates.includes(result.memory.date)) {
        state.diaryDates = [result.memory.date, ...state.diaryDates].sort((a, b) => b.localeCompare(a));
      }
      state.visibleCalendarMonth = monthKeyFromDate(result.memory.date);
      renderCalendar();
      els.diarySelectedDate.textContent = formatDiaryDate(result.memory.date);
      els.diaryEditState.textContent = result.memory.is_today ? "今日日记" : "历史日记";
      els.aiDiary.textContent = result.memory.ai_markdown || "AI 记忆会根据当天对话和状态自动更新。";
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
      history: state.history,
      audio: {},
      video: {},
      ...media,
      timestamp: chinaTimestamp(),
    };

    els.agentStatus.textContent = "Agent 思考中";
    const response = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const result = await response.json();
    if (visibleUserText) {
      state.history.push({ role: "user", content: visibleUserText });
    }
    if (result.agent.reply) {
      state.history.push({ role: "assistant", content: result.agent.reply });
    }
    saveChatHistory();
    state.lastInteractionAt = Date.now();
    if (visibleUserText) {
      state.lastUserInteractionAt = Date.now();
      state.lastPeriodicEmotionAt = 0;
    }
    updateDashboard(result);
    return result;
  } finally {
    state.chatRequestPending = false;
  }
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
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "",
        transcript: "",
        analyze_reason: reason,
        history: state.history,
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
    await triggerProactiveReply("emotion_shift");
  }
}

async function checkIdleProactiveReply() {
  if (state.proactivePending || state.chatRequestPending || els.messageInput.value.trim()) {
    return;
  }
  const now = Date.now();
  const lastUserAt = state.lastUserInteractionAt || state.lastInteractionAt || now;
  if (now - lastUserAt >= PROACTIVE_IDLE_MS) {
    await triggerProactiveReply("idle_120s");
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
  els.agentStatus.textContent = "Agent 正在输入";
  const typingBubble = addTypingBubble();

  try {
    const response = await fetch(apiUrl("/api/chat"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "",
        transcript: consumeSpeechTranscript(),
        proactive: true,
        proactive_reason: reason,
        history: state.history,
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
    if (result.agent.reply) {
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
els.enterAppButton?.addEventListener("click", enterApp);
els.sidebarEmotionTab?.addEventListener("click", () => setSidebarView("emotion"));
els.sidebarDiaryTab?.addEventListener("click", () => setSidebarView("diary"));
els.userDiary.addEventListener("input", scheduleUserDiarySave);
els.calendarPrev.addEventListener("click", () => moveCalendarMonth(-1));
els.calendarNext.addEventListener("click", () => moveCalendarMonth(1));
els.journalAiTab.addEventListener("click", () => setJournalMode("ai"));
els.journalUserTab.addEventListener("click", () => setJournalMode("user"));
els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.chatRequestPending) {
    return;
  }
  const message = els.messageInput.value.trim();
  if (!message) {
    return;
  }

  addBubble("user", message);
  els.messageInput.value = "";
  const typingBubble = addTypingBubble();
  state.lastInteractionAt = Date.now();
  state.lastUserInteractionAt = Date.now();

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

loadDiary();
setJournalMode("ai");
setSidebarView("emotion");
loadChatHistory();
renderChatHistory();
renderFeatureList(els.audioFeatureList, AUDIO_FEATURE_META, {});
renderFeatureList(els.videoFeatureList, VIDEO_FEATURE_META, {});
startDiaryRefreshLoop();
pingBackend();
if (shouldOpenChatDirectly()) {
  enterApp();
}
