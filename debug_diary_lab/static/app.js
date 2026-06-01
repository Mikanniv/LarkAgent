const els = {
  currentDateInput: document.getElementById("currentDateInput"),
  changeDayButton: document.getElementById("changeDayButton"),
  manualGenerateButton: document.getElementById("manualGenerateButton"),
  resetButton: document.getElementById("resetButton"),
  statusText: document.getElementById("statusText"),
  selectedDateTag: document.getElementById("selectedDateTag"),
  chatList: document.getElementById("chatList"),
  chatForm: document.getElementById("chatForm"),
  messageInput: document.getElementById("messageInput"),
  calendarGrid: document.getElementById("calendarGrid"),
  monthLabel: document.getElementById("monthLabel"),
  diaryStatus: document.getElementById("diaryStatus"),
  diaryContent: document.getElementById("diaryContent"),
};

let state = {
  currentDate: "",
  selectedDate: "",
  month: null,
};

function api(path) {
  return path;
}

async function request(path, options = {}) {
  const response = await fetch(api(path), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `HTTP ${response.status}`);
  }
  return payload;
}

function setStatus(text) {
  els.statusText.textContent = text;
}

function formatMonthLabel(year, month) {
  return `${year}-${String(month).padStart(2, "0")}`;
}

function dateParts(dateKey) {
  const [year, month, day] = dateKey.split("-").map(Number);
  return { year, month, day };
}

function dateKey(year, month, day) {
  return `${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function renderChat(messages) {
  els.chatList.innerHTML = "";
  if (!messages.length) {
    els.chatList.innerHTML = `<article class="bubble assistant"><span class="role">云雀</span>这一天还没有聊天。先发一句，然后切到下一天试试。</article>`;
    return;
  }
  messages.forEach((item) => {
    const bubble = document.createElement("article");
    bubble.className = `bubble ${item.role}`;
    const role = item.role === "user" ? "你" : "云雀";
    bubble.innerHTML = `<span class="role">${role}</span>${escapeHtml(item.content)}`;
    els.chatList.appendChild(bubble);
  });
  els.chatList.scrollTop = els.chatList.scrollHeight;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderCalendar(monthPayload, selectedDate) {
  const { year, month, message_dates: messageDates, diary_dates: diaryDates, pending_dates: pendingDates } = monthPayload;
  const messageSet = new Set(messageDates);
  const diarySet = new Set(diaryDates);
  const pendingSet = new Set(pendingDates);
  els.monthLabel.textContent = formatMonthLabel(year, month);
  els.calendarGrid.innerHTML = "";

  const first = new Date(year, month - 1, 1);
  const startOffset = (first.getDay() + 6) % 7;
  const start = new Date(year, month - 1, 1 - startOffset);
  for (let index = 0; index < 42; index += 1) {
    const current = new Date(start);
    current.setDate(start.getDate() + index);
    const key = dateKey(current.getFullYear(), current.getMonth() + 1, current.getDate());
    const button = document.createElement("button");
    button.type = "button";
    button.className = "day";
    if (current.getMonth() + 1 !== month) {
      button.classList.add("is-outside");
    }
    if (key === selectedDate) {
      button.classList.add("is-selected");
    }
    const dots = [];
    if (messageSet.has(key)) dots.push(`<span class="dot chat" title="有聊天"></span>`);
    if (diarySet.has(key)) dots.push(`<span class="dot diary" title="已生成AI记"></span>`);
    if (pendingSet.has(key)) dots.push(`<span class="dot pending" title="待生成"></span>`);
    button.innerHTML = `<strong>${current.getDate()}</strong><div class="dots">${dots.join("")}</div>`;
    button.addEventListener("click", () => loadState(key));
    els.calendarGrid.appendChild(button);
  }
}

function render(payload) {
  state.currentDate = payload.current_date;
  state.selectedDate = payload.selected_date;
  state.month = payload.month;
  els.currentDateInput.value = payload.current_date;
  els.selectedDateTag.textContent = payload.selected_date;
  renderChat(payload.messages || []);
  renderCalendar(payload.month, payload.selected_date);
  els.diaryStatus.textContent = payload.ai_diary?.status || "not_ready";
  els.diaryContent.textContent = payload.ai_diary?.content || "";
}

async function loadState(date = "") {
  const query = date ? `?date=${encodeURIComponent(date)}` : "";
  const payload = await request(`/api/state${query}`);
  render(payload);
}

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = els.messageInput.value.trim();
  if (!message) return;
  els.messageInput.value = "";
  setStatus("正在写入调试聊天...");
  const payload = await request("/api/chat", {
    method: "POST",
    body: JSON.stringify({ date: state.selectedDate || state.currentDate, message }),
  });
  render(payload);
  setStatus("已写入，当前日期已标记为待生成。");
});

els.changeDayButton.addEventListener("click", async () => {
  const nextDate = els.currentDateInput.value;
  if (!nextDate) return;
  setStatus("正在切换日期并触发生成...");
  const payload = await request("/api/day", {
    method: "POST",
    body: JSON.stringify({ date: nextDate }),
  });
  render(payload);
  setStatus(payload.generated.length ? `已生成：${payload.generated.join("，")}` : "没有需要生成的旧日期。");
});

els.manualGenerateButton.addEventListener("click", async () => {
  setStatus("正在手动生成当前选中日期...");
  const payload = await request("/api/generate", {
    method: "POST",
    body: JSON.stringify({ date: state.selectedDate || state.currentDate }),
  });
  render(payload);
  setStatus(payload.generated.length ? `已生成：${payload.generated.join("，")}` : "当前日期没有聊天内容，无法生成。");
});

els.resetButton.addEventListener("click", async () => {
  if (!window.confirm("确定清空调试 SQLite 吗？不会影响正式数据。")) return;
  const payload = await request("/api/reset", { method: "POST", body: "{}" });
  render(payload);
  setStatus("调试数据已清空。");
});

loadState().catch((error) => setStatus(error.message));

