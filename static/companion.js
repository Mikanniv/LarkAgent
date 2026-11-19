import { mountCharacter } from "./character.js";
import { DesktopClient } from "./desktop-client.js";

const $ = id => document.getElementById(id);
const read = (key, fallback) => { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } };
const save = (key, value) => { try { localStorage.setItem(key, value); } catch { /* Private browsing may disable storage. */ } };
const keys = { gaze: "yunque.companion.gaze", form: "yunque.companion.form" };
let gazeEnabled = read(keys.gaze, "1") !== "0";
let preferredForm = read(keys.form, "bird");
let wasConnected = false;
let toastTimer;
let pointerFrame;
let togglePending = false;
const character = mountCharacter($("mainCharacter"));
const desktop = new DesktopClient();

function toast(message) {
  $("companionToast").textContent = message;
  $("companionToast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("companionToast").hidden = true; }, 3500);
}
function render() {
  const connected = Boolean(desktop.state);
  const visible = connected && desktop.state.visible;
  $("petToggleLabel").textContent = visible ? "隐藏桌宠" : "显示桌宠";
  if ($("sidebarPetLabel")) $("sidebarPetLabel").textContent = visible ? "隐藏桌宠" : "显示桌宠";
  $("settingsPetToggle").textContent = visible ? "隐藏桌宠" : "显示桌宠";
  $("petToggleButton").setAttribute("aria-pressed", String(visible));
  if ($("sidebarPetButton")) $("sidebarPetButton").setAttribute("aria-pressed", String(visible));
  $("petConnectionStatus").textContent = connected ? "已连接云雀桌面，可在其他应用旁陪伴。" : "启动本机的云雀桌面后，即可连接。";
  $("gazeFollowToggle").checked = character.supportsGaze && gazeEnabled;
  $("gazeFollowToggle").disabled = !character.supportsGaze;
  character.setEnabled(gazeEnabled);
  document.querySelectorAll("[data-pet-form]").forEach(button => {
    const active = button.dataset.petForm === preferredForm;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}
$("mainCharacter").addEventListener("character-ready", render);
$("mainCharacter").addEventListener("character-error", () => {
  $("gazeFollowDescription").textContent = "动态形象未能加载，请刷新页面重试。";
  render();
});
desktop.addEventListener("state", event => {
  const firstConnection = !wasConnected;
  wasConnected = true;
  if (firstConnection) {
    // Existing desktop preferences are authoritative across the web and tray menu.
    const remote = event.detail;
    gazeEnabled = remote.gazeEnabled;
    preferredForm = remote.form;
  } else {
    gazeEnabled = event.detail.gazeEnabled;
    preferredForm = event.detail.form;
  }
  save(keys.gaze, gazeEnabled ? "1" : "0"); save(keys.form, preferredForm);
  render();
  if ($("desktopSetupDialog").open && event.detail.visible) $("desktopSetupDialog").close();
});
desktop.addEventListener("disconnected", () => { wasConnected = false; render(); });

async function togglePet() {
  if (togglePending) return;
  togglePending = true;
  try {
    if (!desktop.state && !await desktop.refresh()) { $("desktopSetupDialog").showModal(); return; }
    await desktop.command("set-visible", !desktop.state.visible);
  } catch (error) { toast(error.message); }
  finally { togglePending = false; }
}
$("petToggleButton").addEventListener("click", togglePet);
$("sidebarPetButton")?.addEventListener("click", togglePet);
$("settingsPetToggle").addEventListener("click", togglePet);
$("desktopSetupClose").onclick = () => $("desktopSetupDialog").close();
$("desktopSetupLaunch").onclick = () => {
  const link = document.createElement("a");
  link.href = "yunque://show-pet"; link.click();
  $("desktopSetupStatus").textContent = "等待桌面云雀启动…首次使用请先运行本机的桌面程序。";
  desktop.refresh();
};
$("desktopSetupRetry").onclick = async () => {
  if (await desktop.refresh()) { await togglePet(); $("desktopSetupDialog").close(); }
  else $("desktopSetupStatus").textContent = "还没有连接上，请确认本机的云雀桌面已启动。";
};
$("gazeFollowToggle").onchange = async event => {
  gazeEnabled = event.target.checked;
  save(keys.gaze, gazeEnabled ? "1" : "0"); render();
  if (desktop.state) {
    try { await desktop.command("set-gaze", gazeEnabled); }
    catch { toast("网页设置已保存，桌面暂未同步，请重新连接。"); }
  }
};
document.querySelectorAll("[data-pet-form]").forEach(button => button.onclick = async () => {
  preferredForm = button.dataset.petForm;
  save(keys.form, preferredForm); render();
  if (desktop.state) {
    try { await desktop.command("set-form", preferredForm); }
    catch { toast("形态已在网页保存，桌面暂未同步。"); }
  }
});
document.querySelectorAll("[data-open-view]").forEach(button => button.onclick = () => setView(button.dataset.openView));
$("homeBackButton").onclick = $("brandHomeButton").onclick = () => setView("home");
if ($("quickSettingsButton")) $("quickSettingsButton").onclick = () => setView("settings");
$("accountButton").onclick = () => {
  $("introScreen").classList.remove("is-hidden");
  $("authForm").hidden = false;
  $("authUsername").focus();
};
document.addEventListener("keydown", event => {
  if (event.key === "Escape" && !$("introScreen").classList.contains("is-hidden")) $("introScreen").classList.add("is-hidden");
});
let cachedCharRect = null;
function updateCachedCharRect() {
  const el = $("mainCharacter");
  if (el) cachedCharRect = el.getBoundingClientRect();
}
window.addEventListener("resize", updateCachedCharRect, { passive: true });
$("companionStage")?.addEventListener("transitionend", updateCachedCharRect, { passive: true });
window.addEventListener("yunque:view", (e) => {
  character.pauseForTransition?.(420);
  setTimeout(updateCachedCharRect, 450);
});

document.addEventListener("pointermove", event => {
  if (!character.supportsGaze || !gazeEnabled) return;
  if (pointerFrame) return;
  const cx = event.clientX;
  const cy = event.clientY;
  pointerFrame = requestAnimationFrame(() => {
    pointerFrame = 0;
    if (!cachedCharRect || !cachedCharRect.width) updateCachedCharRect();
    const rect = cachedCharRect;
    if (!rect || !rect.width) return;
    character.lookAt((cx - rect.left - rect.width / 2) / 280, (cy - rect.top - rect.height * .27) / 280);
  });
}, { passive: true });
document.documentElement.addEventListener("pointerleave", () => character.lookAt(0, 0));
window.addEventListener("blur", () => character.lookAt(0, 0));
window.addEventListener("yunque:open-chat", () => setView("chat"));
if (window.yunqueDesktop) $("desktopSetupLaunch").hidden = true;
window.yunqueDesktop?.onOpenChat(() => setView("chat"));
render(); desktop.start();
window.addEventListener("pagehide", () => desktop.stop(), { once: true });
