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
};

const els = Object.fromEntries(
  [
    "introScreen", "enterAppButton", "authToggleButton", "authForm", "authUsername",
    "authPassword", "authLoginButton", "authRegisterButton", "authStatus", "appShell",
    "appSidebar", "sidebarToggle", "mobileSidebarToggle", "sidebarScrim", "activeViewTitle",
    "backendStatus", "agentStatus", "sidebarChatTab", "sidebarDiaryTab", "sidebarMemoryTab",
    "sidebarSettingsTab", "diaryNewBadge", "memoryNewBadge", "chatView", "diaryView",
    "memoryView", "settingsView", "emotionWidget", "emotionToggle", "textScore",
    "fusionScore", "chatList", "chatForm", "messageInput", "diaryUserModeTab",
    "diaryAiModeTab", "userDiaryPane", "aiDiaryPane", "userDiaryDate", "userDiary",
    "userDiaryStatus", "diaryDeleteButton", "diarySaveButton", "aiDiaryList",
    "memoryLayers", "memoryItems", "memoryDetail", "proactiveReplyToggle", "clearDataButton",
    "revisionModal", "revisionInput", "revisionCancel", "revisionSubmit",
  ].map((id) => [id, document.getElementById(id)]),
);

const CHINA_TIME_ZONE = "Asia/Shanghai";
const API_BASE = resolveApiBase();
const VIEW_TITLES = { chat: "聊天", diary: "日记", memory: "长期记忆", settings: "设置" };
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
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  let payload = {};
  try {
    payload = await response.json();
  } catch {
    payload = {};
  }
  if (!response.ok) throw new Error(payload.error || `请求失败（${response.status}）`);
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
    setBackendOnline(true);
  } catch {
    setBackendOnline(false);
    renderChatHistory();
  }
}

function updateScores(scores = {}) {
  els.textScore.textContent = Number(scores.text || 0).toFixed(3);
  els.fusionScore.textContent = Number(scores.fusion || 0).toFixed(3);
}

async function sendChat(message, { proactive = false } = {}) {
  if (state.chatPending) return;
  state.chatPending = true;
  let typing = null;
  if (!proactive) {
    appendMessage("user", message);
  }
  typing = appendMessage("assistant", "···", { typing: true });
  els.agentStatus.textContent = "云雀正在思考";
  try {
    const payload = await requestJson("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message: proactive ? "" : message,
        proactive,
        proactive_reason: proactive ? "用户一段时间没有继续输入" : "",
        timestamp: chinaTimestamp(),
      }),
    });
    typing.remove();
    updateScores(payload.scores);
    const reply = payload.agent?.reply || "我在。";
    appendMessage("assistant", reply);
    state.history = payload.chat_history || state.history;
    els.agentStatus.textContent = "文本陪伴模式";
    setBackendOnline(true);
    state.lastInteractionAt = Date.now();
    await Promise.allSettled([fetchMemories(), fetchAiDiary()]);
  } catch (error) {
    typing?.remove();
    appendMessage("assistant", `暂时没有连接上后端：${error.message}`);
    els.agentStatus.textContent = "连接失败";
    setBackendOnline(false);
  } finally {
    state.chatPending = false;
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
    renderChatHistory();
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

[els.sidebarChatTab, els.sidebarDiaryTab, els.sidebarMemoryTab, els.sidebarSettingsTab]
  .forEach((button) => button.addEventListener("click", () => setView(button.dataset.view)));
els.sidebarToggle.addEventListener("click", () => setSidebarCollapsed(!state.sidebarCollapsed));
els.mobileSidebarToggle.addEventListener("click", () => els.appShell.classList.add("is-mobile-menu-open"));
els.sidebarScrim.addEventListener("click", () => els.appShell.classList.remove("is-mobile-menu-open"));
els.emotionToggle.addEventListener("click", () => {
  const collapsed = els.emotionWidget.classList.toggle("is-collapsed");
  els.emotionToggle.setAttribute("aria-expanded", String(!collapsed));
  els.emotionToggle.title = collapsed ? "展开情绪画像" : "收起情绪画像";
});
els.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = els.messageInput.value.trim();
  if (!message || state.chatPending) return;
  els.messageInput.value = "";
  els.messageInput.dispatchEvent(new Event("input", { bubbles: true }));
  sendChat(message);
});
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
  try {
    state.sidebarCollapsed = localStorage.getItem("yunque.web.sidebar.collapsed.v2") === "1";
    state.proactiveEnabled = localStorage.getItem("yunque.web.proactive.v2") !== "0";
  } catch {
    state.sidebarCollapsed = false;
    state.proactiveEnabled = true;
  }
  setSidebarCollapsed(state.sidebarCollapsed);
  els.proactiveReplyToggle.checked = state.proactiveEnabled;
  renderChatHistory();
  renderMemoryBrowser();
  renderAiDiary();
  await checkAuth();
}

initialize();
