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
  const el = $("companionToast");
  if (!el) return;
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { if ($("companionToast")) $("companionToast").hidden = true; }, 3500);
}
function render() {
  const connected = Boolean(desktop.state);
  const visible = connected && desktop.state.visible;
  const label = visible ? "隐藏桌宠" : "显示桌宠";
  if ($("petToggleLabel")) $("petToggleLabel").textContent = label;
  if ($("sidebarPetLabel")) $("sidebarPetLabel").textContent = label;
  if ($("settingsPetToggle")) $("settingsPetToggle").textContent = label;
  $("petToggleButton")?.setAttribute("aria-pressed", String(visible));
  $("sidebarPetButton")?.setAttribute("aria-pressed", String(visible));
  if ($("petConnectionStatus")) {
    $("petConnectionStatus").textContent = connected ? "已连接云雀桌面，可在其他应用旁陪伴。" : "启动本机的云雀桌面后，即可连接。";
  }
  const gazeToggle = $("gazeFollowToggle");
  if (gazeToggle) {
    gazeToggle.checked = character.supportsGaze && gazeEnabled;
    gazeToggle.disabled = !character.supportsGaze;
  }
  character.setEnabled(gazeEnabled);
  document.querySelectorAll("[data-pet-form]").forEach(button => {
    const active = button.dataset.petForm === preferredForm;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}
$("mainCharacter")?.addEventListener("character-ready", () => {
  updateCachedCharRect();
  render();
});
$("mainCharacter")?.addEventListener("character-error", () => {
  if ($("gazeFollowDescription")) {
    $("gazeFollowDescription").textContent = "动态形象未能加载，请刷新页面重试。";
  }
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
$("petToggleButton")?.addEventListener("click", togglePet);
$("sidebarPetButton")?.addEventListener("click", togglePet);
$("settingsPetToggle")?.addEventListener("click", togglePet);
if ($("desktopSetupClose")) $("desktopSetupClose").onclick = () => $("desktopSetupDialog")?.close();
if ($("desktopSetupLaunch")) {
  $("desktopSetupLaunch").onclick = () => {
    const link = document.createElement("a");
    link.href = "yunque://show-pet"; link.click();
    if ($("desktopSetupStatus")) $("desktopSetupStatus").textContent = "等待桌面云雀启动…首次使用请先运行本机的桌面程序。";
    desktop.refresh();
  };
}
if ($("desktopSetupRetry")) {
  $("desktopSetupRetry").onclick = async () => {
    if (await desktop.refresh()) { await togglePet(); $("desktopSetupDialog")?.close(); }
    else if ($("desktopSetupStatus")) $("desktopSetupStatus").textContent = "还没有连接上，请确认本机的云雀桌面已启动。";
  };
}
if ($("gazeFollowToggle")) {
  $("gazeFollowToggle").onchange = async event => {
    gazeEnabled = event.target.checked;
    save(keys.gaze, gazeEnabled ? "1" : "0");
    if (gazeEnabled) updateCachedCharRect();
    render();
    if (desktop.state) {
      try { await desktop.command("set-gaze", gazeEnabled); }
      catch { toast("网页设置已保存，桌面暂未同步，请重新连接。"); }
    }
  };
}
document.querySelectorAll("[data-pet-form]").forEach(button => button.onclick = async () => {
  preferredForm = button.dataset.petForm;
  save(keys.form, preferredForm); render();
  if (desktop.state) {
    try { await desktop.command("set-form", preferredForm); }
    catch { toast("形态已在网页保存，桌面暂未同步。"); }
  }
});
document.querySelectorAll("[data-open-view]").forEach(button => button.onclick = () => setView(button.dataset.openView));
if ($("homeBackButton")) $("homeBackButton").onclick = () => setView("home");
if ($("brandHomeButton")) $("brandHomeButton").onclick = () => setView("home");
if ($("quickSettingsButton")) $("quickSettingsButton").onclick = () => setView("settings");
if ($("accountButton")) {
  $("accountButton").onclick = () => {
    $("introScreen")?.classList.remove("is-hidden");
    if ($("authForm")) $("authForm").hidden = false;
    $("authUsername")?.focus();
  };
}
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

// Interactive floating tilt + cursor spotlight for home glass cards
if (!window.matchMedia("(prefers-reduced-motion: reduce)").matches && window.matchMedia("(hover: hover)").matches) {
  document.querySelectorAll(".home-quick-card, .lark-greeting-bubble").forEach(card => {
    const maxTilt = card.classList.contains("lark-greeting-bubble") ? 2.5 : 4.2;
    const liftY = card.classList.contains("lark-greeting-bubble") ? -5 : -6;
    card.addEventListener("pointermove", event => {
      const rect = card.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const px = (event.clientX - rect.left) / rect.width;
      const py = (event.clientY - rect.top) / rect.height;
      card.style.setProperty("--mx", `${(px * 100).toFixed(1)}%`);
      card.style.setProperty("--my", `${(py * 100).toFixed(1)}%`);
      const rx = ((0.5 - py) * maxTilt * 2).toFixed(2);
      const ry = ((px - 0.5) * maxTilt * 2).toFixed(2);
      card.style.transform = `perspective(820px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(${liftY}px) scale(1.015)`;
    }, { passive: true });
    card.addEventListener("pointerleave", () => {
      card.style.transform = "";
    });
  });
}

// Left floating sidebar proximity auto-expand & auto-collapse
const floatingSidebar = document.querySelector(".companion-app .topbar");
if (floatingSidebar) {
  let sidebarExpanded = false;
  document.addEventListener("pointermove", event => {
    const x = event.clientX;
    if (!sidebarExpanded && x <= 74) {
      sidebarExpanded = true;
      floatingSidebar.classList.add("is-expanded");
    } else if (sidebarExpanded && x > 210 && !floatingSidebar.matches(":hover")) {
      sidebarExpanded = false;
      floatingSidebar.classList.remove("is-expanded");
    }
  }, { passive: true });
  document.documentElement.addEventListener("pointerleave", () => {
    sidebarExpanded = false;
    floatingSidebar.classList.remove("is-expanded");
  });
}
