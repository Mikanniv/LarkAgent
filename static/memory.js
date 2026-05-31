const els = {
  form: document.getElementById("memoryForm"),
  query: document.getElementById("memoryQuery"),
  k: document.getElementById("memoryK"),
  userId: document.getElementById("memoryUserId"),
  type: document.getElementById("memoryType"),
  clearButton: document.getElementById("memoryClearButton"),
  listButton: document.getElementById("memoryListButton"),
  results: document.getElementById("memoryResults"),
  resultTitle: document.getElementById("memoryResultTitle"),
  resultMeta: document.getElementById("memoryResultMeta"),
};

const API_BASE = resolveApiBase();
const state = {
  authUser: null,
};
const CHINA_TIME_ZONE = "Asia/Shanghai";
const chinaDisplayFormatter = new Intl.DateTimeFormat("zh-CN", {
  timeZone: CHINA_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});

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

function authRequired() {
  try {
    return new URL(API_BASE).hostname === "worker.lark.irises.me";
  } catch {
    return !["127.0.0.1", "localhost", "::1", "0.0.0.0"].includes(window.location.hostname);
  }
}

async function loadCurrentUser() {
  if (!authRequired()) {
    els.userId.readOnly = false;
    els.userId.title = "本地调试模式，可以手动切换 user_id。";
    return;
  }
  const response = await fetch(apiUrl("/api/auth/me"), { credentials: "include" });
  const payload = await response.json();
  state.authUser = payload.user || null;
  if (state.authUser) {
    els.userId.value = state.authUser.id;
    els.userId.readOnly = true;
    els.userId.title = "登录模式下由 Worker 注入当前账号，不能手动查询其他用户。";
  }
}

function formatNumber(value, digits = 2) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(digits) : "-";
}

function formatChinaTimestamp(value) {
  if (!value) {
    return value;
  }
  const normalized = String(value).replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${chinaDisplayFormatter.format(date).replaceAll("/", "-")} +08:00`;
}

function typeLabel(type) {
  return {
    event: "事件",
    routine: "习惯",
    preference: "偏好",
    relationship: "关系",
    summary: "总结",
  }[type] || type || "-";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function metadataRows(metadata = {}) {
  const rows = [
    ["date", metadata.date],
    ["timestamp", formatChinaTimestamp(metadata.timestamp)],
    ["owner", metadata.user],
    ["user_id", metadata.user_id],
    ["type", metadata.type],
    ["source", metadata.source],
    ["confidence", formatNumber(metadata.confidence)],
    ["importance", formatNumber(metadata.importance)],
    ["importance_0", formatNumber(metadata.importance_0)],
  ];
  if (metadata.has_emotion) {
    rows.push(["valence", formatNumber(metadata.valence)]);
    rows.push(["arousal", formatNumber(metadata.arousal)]);
  }
  rows.push(["text", String(Boolean(metadata.text ?? metadata.text_available))]);
  rows.push(["audio", String(Boolean(metadata.audio ?? metadata.audio_available))]);
  rows.push(["video", String(Boolean(metadata.video ?? metadata.video_available))]);
  return rows
    .filter(([, value]) => value !== undefined && value !== null && value !== "")
    .map(([key, value]) => `<span><strong>${escapeHtml(key)}</strong>${escapeHtml(value)}</span>`)
    .join("");
}

function renderItems(payload) {
  const items = payload.items || [];
  els.resultTitle.textContent = payload.mode === "recall" ? "Top-k 召回结果" : "最近记忆";
  const filteredCount = payload.filtered_count ?? "-";
  els.resultMeta.textContent = `当前筛选条目数：${filteredCount}；collection 总条目数：${payload.count}；user_id：${payload.user_id || "全部"}；返回 ${items.length} 条`;
  if (!items.length) {
    els.results.innerHTML = `<article class="memory-empty">暂无结果。可以先和云雀聊天产生长期记忆，或去命令行运行 seed demo。</article>`;
    return;
  }
  els.results.innerHTML = items
    .map((item, index) => {
      const metadata = item.metadata || {};
      const score = item.score === null || item.score === undefined ? "" : `<span>召回分 ${formatNumber(item.score, 3)}</span>`;
      const distance =
        item.distance === null || item.distance === undefined ? "" : `<span>距离 ${formatNumber(item.distance, 3)}</span>`;
      const similarity =
        item.semantic_similarity === null || item.semantic_similarity === undefined
          ? ""
          : `<span>相似度 ${formatNumber(item.semantic_similarity, 3)}</span>`;
      return `
        <article class="memory-card">
          <div class="memory-card-top">
            <span class="mini-tag">#${index + 1}</span>
            <span class="mini-tag">${escapeHtml(typeLabel(metadata.type))}</span>
            ${score}
            ${distance}
            ${similarity}
          </div>
          <p>${escapeHtml(item.document)}</p>
          <div class="memory-meta-grid">${metadataRows(metadata)}</div>
          <footer>${escapeHtml(item.id || "")}</footer>
        </article>
      `;
    })
    .join("");
}

async function fetchMemories({ query = "", listOnly = false } = {}) {
  if (authRequired() && !state.authUser) {
    throw new Error("请先回到聊天页登录，再查看当前账号的长期记忆。");
  }
  const params = new URLSearchParams();
  if (!listOnly && query.trim()) {
    params.set("query", query.trim());
  }
  params.set("k", els.k.value || "5");
  if (!authRequired() && els.userId.value.trim()) {
    params.set("user_id", els.userId.value.trim());
  }
  if (els.type.value) {
    params.set("type", els.type.value);
  }
  els.resultTitle.textContent = "正在查询";
  els.resultMeta.textContent = "等待后端返回 ChromaDB 结果。";
  els.results.innerHTML = "";
  const response = await fetch(apiUrl(`/api/memory?${params.toString()}`), { credentials: "include" });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  renderItems(await response.json());
}

async function clearCurrentMemories() {
  const userId = authRequired() ? state.authUser?.id || "" : els.userId.value.trim() || "local_user";
  if (authRequired() && !userId) {
    throw new Error("请先登录后再查看或清空记忆。");
  }
  const type = els.type.value;
  const scope = type ? `${userId} / ${type}` : `${userId} / 全部类型`;
  const confirmed = window.confirm(`确定清空 ${scope} 的长期记忆吗？这个操作不可撤销。`);
  if (!confirmed) {
    return;
  }
  els.resultTitle.textContent = "正在清空";
  els.resultMeta.textContent = "正在删除当前筛选范围内的长期记忆。";
  const response = await fetch(apiUrl("/api/memory/clear"), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ user_id: userId, type }),
  });
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }
  const payload = await response.json();
  els.resultTitle.textContent = "已清空";
  els.resultMeta.textContent = `已删除 ${payload.deleted || 0} 条记忆；collection 条目数：${payload.count ?? "-"}`;
  await fetchMemories({ listOnly: true });
}

els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await fetchMemories({ query: els.query.value });
  } catch (error) {
    els.resultTitle.textContent = "查询失败";
    els.resultMeta.textContent = String(error.message || error);
  }
});

els.listButton.addEventListener("click", async () => {
  try {
    await fetchMemories({ listOnly: true });
  } catch (error) {
    els.resultTitle.textContent = "查询失败";
    els.resultMeta.textContent = String(error.message || error);
  }
});

els.clearButton.addEventListener("click", async () => {
  try {
    await clearCurrentMemories();
  } catch (error) {
    els.resultTitle.textContent = "清空失败";
    els.resultMeta.textContent = String(error.message || error);
  }
});

loadCurrentUser()
  .then(() => fetchMemories({ listOnly: true }))
  .catch((error) => {
    els.resultTitle.textContent = "查询失败";
    els.resultMeta.textContent = String(error.message || error);
  });
