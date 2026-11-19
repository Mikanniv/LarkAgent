const { app, BrowserWindow, ipcMain, Menu, Tray, nativeImage, screen, dialog, session } = require("electron");
const path = require("node:path");
const { createBridge, DEFAULT_ORIGINS, validCommand } = require("./bridge.cjs");
const { readPreferences, writePreferences, clampPosition } = require("./preferences.cjs");

const PORT = 17643;
const LOCAL_ORIGIN = `http://127.0.0.1:${PORT}`;
const STATIC_ROOT = path.resolve(__dirname, "../static");
const PET_SIZE = { width: 250, height: 295 };
const userDataOverride = process.env.LARK_USER_DATA || process.env.YUNQUE_USER_DATA;
if (userDataOverride) app.setPath("userData", path.resolve(userDataOverride));
app.setName("云雀桌面");
let mainWindow, petWindow, tray, bridge, preferencesFile, state, cursorTimer, saveTimer, quitting = false, dragging = null;
const snapshot = () => ({ visible: state.visible, form: state.form, gazeEnabled: state.gazeEnabled, position: state.position });
function persist() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    try { writePreferences(preferencesFile, state); }
    catch (error) { console.error("Unable to save companion preferences:", error.message); }
  }, 150);
}
function broadcast() {
  for (const window of [mainWindow, petWindow]) if (window && !window.isDestroyed()) window.webContents.send("companion:state", snapshot());
  rebuildTray(); persist();
}
function allowedNavigation(url) { try { return new URL(url).origin === LOCAL_ORIGIN; } catch { return false; } }
function protectWindow(window) {
  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.on("will-navigate", (event, url) => { if (!allowedNavigation(url)) event.preventDefault(); });
}
function createMain() {
  if (mainWindow && !mainWindow.isDestroyed()) { mainWindow.show(); mainWindow.focus(); return; }
  mainWindow = new BrowserWindow({
    title: "云雀", width: 1280, height: 850, minWidth: 720, minHeight: 620,
    backgroundColor: "#f7f9fc", show: false,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  protectWindow(mainWindow);
  mainWindow.loadURL(LOCAL_ORIGIN);
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.on("close", event => { if (!quitting) { event.preventDefault(); mainWindow.hide(); } });
}
function positionPet() {
  const area = state.position ? screen.getDisplayNearestPoint(state.position).workArea : screen.getPrimaryDisplay().workArea;
  const position = clampPosition(state.position, area, PET_SIZE);
  state.position = position;
  petWindow.setBounds({ ...position, ...PET_SIZE });
}
function createPet() {
  petWindow = new BrowserWindow({
    ...PET_SIZE, show: false, transparent: true, backgroundColor: "#00000000", frame: false,
    resizable: false, maximizable: false, minimizable: false, fullscreenable: false,
    hasShadow: false, alwaysOnTop: true, skipTaskbar: true, focusable: false,
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  protectWindow(petWindow); positionPet();
  petWindow.setAlwaysOnTop(true, "floating");
  if (process.platform === "darwin") petWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  petWindow.loadURL(`${LOCAL_ORIGIN}/pet.html`);
  petWindow.on("close", event => { if (!quitting) { event.preventDefault(); applyCommand("set-visible", false); } });
  petWindow.webContents.once("did-finish-load", () => {
    petWindow.webContents.send("companion:state", snapshot());
    if (state.visible) petWindow.showInactive();
  });
}
function applyCommand(action, value) {
  if (!validCommand({ action, value })) throw new Error("Invalid companion command");
  if (action === "set-visible") {
    state.visible = value;
    if (!value) { dragging = null; petWindow.hide(); }
    else { positionPet(); petWindow.showInactive(); }
  }
  if (action === "set-form") state.form = value;
  if (action === "set-gaze") state.gazeEnabled = value;
  if (action === "open-main") createMain();
  broadcast(); return snapshot();
}
function menuTemplate() {
  return [
    { label: "打开云雀", click: createMain },
    { type: "separator" },
    { label: "鸟型", type: "radio", checked: state.form === "bird", click: () => applyCommand("set-form", "bird") },
    { label: "Q版小人", type: "radio", checked: state.form === "chibi", click: () => applyCommand("set-form", "chibi") },
    { type: "separator" },
    { label: "视线跟随（待接入动态形象）", enabled: false },
    { label: state.visible ? "隐藏桌宠" : "显示桌宠", click: () => applyCommand("set-visible", !state.visible) },
    { type: "separator" },
    { label: "退出云雀桌面", click: () => app.quit() },
  ];
}
function rebuildTray() { if (tray) tray.setContextMenu(Menu.buildFromTemplate(menuTemplate())); }
function trustedSender(event, petOnly = false) {
  return (petOnly ? [petWindow] : [petWindow, mainWindow]).some(window => window && !window.isDestroyed() && event.sender === window.webContents) && allowedNavigation(event.senderFrame?.url || "");
}
function setupIPC() {
  ipcMain.handle("companion:get-state", event => { if (!trustedSender(event)) throw new Error("Unknown sender"); return snapshot(); });
  ipcMain.handle("companion:command", (event, input) => { if (!trustedSender(event) || !validCommand(input)) throw new Error("Invalid sender or command"); return applyCommand(input.action, input.value); });
  ipcMain.on("companion:menu", event => { if (trustedSender(event, true)) Menu.buildFromTemplate(menuTemplate()).popup({ window: petWindow }); });
  ipcMain.on("companion:hit-test", (event, hit) => { if (trustedSender(event, true) && !dragging) petWindow.setIgnoreMouseEvents(!hit, { forward: true }); });
  ipcMain.on("companion:drag-start", event => {
    if (!trustedSender(event, true)) return;
    const cursor = screen.getCursorScreenPoint(); const [x, y] = petWindow.getPosition();
    dragging = { x: cursor.x - x, y: cursor.y - y };
    petWindow.setIgnoreMouseEvents(false);
  });
  ipcMain.on("companion:drag-end", event => {
    if (!trustedSender(event, true)) return;
    dragging = null; const [x, y] = petWindow.getPosition(); state.position = { x, y }; positionPet(); broadcast();
  });
}
function setupCursor() {
  // Reads pointer coordinates only; no screen image, app content or capture API.
  cursorTimer = setInterval(() => {
    if (!state.visible || !petWindow || petWindow.isDestroyed()) return;
    const cursor = screen.getCursorScreenPoint();
    if (dragging) {
      const position = clampPosition({ x: cursor.x - dragging.x, y: cursor.y - dragging.y }, screen.getDisplayNearestPoint(cursor).workArea, PET_SIZE);
      petWindow.setPosition(position.x, position.y); state.position = position;
    }
    if (state.gazeEnabled) {
      const [x, y] = petWindow.getPosition();
      petWindow.webContents.send("companion:cursor", { x: (cursor.x - x - PET_SIZE.width / 2) / 300, y: (cursor.y - y - PET_SIZE.height * .4) / 300 });
    }
  }, 50);
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", (_event, argv) => { if (argv.some(value => value.startsWith("yunque://show-pet"))) applyCommand("set-visible", true); else createMain(); });
  app.on("open-url", (event, url) => { event.preventDefault(); if (url.startsWith("yunque://show-pet") && state) applyCommand("set-visible", true); });
  app.whenReady().then(async () => {
    preferencesFile = path.join(app.getPath("userData"), "companion-preferences.json");
    state = { ...readPreferences(preferencesFile), visible: false };
    setupIPC();
    session.defaultSession.setPermissionRequestHandler((_contents, permission, callback, details) => callback(permission === "media" && details.mediaTypes?.every(type => type === "audio") === true));
    session.defaultSession.setDisplayMediaRequestHandler((_request, callback) => callback({}));
    bridge = createBridge({
      staticRoot: STATIC_ROOT, getState: snapshot, command: applyCommand,
      apiBase: process.env.LARK_API_BASE || process.env.YUNQUE_API_BASE || "http://127.0.0.1:8001",
      origins: [...DEFAULT_ORIGINS, ...((process.env.LARK_WEB_ORIGINS || process.env.YUNQUE_WEB_ORIGINS || "").split(",").filter(Boolean))],
    });
    try { await new Promise((resolve, reject) => { bridge.once("error", reject); bridge.listen(PORT, "127.0.0.1", resolve); }); }
    catch (error) { dialog.showErrorBox("云雀桌面暂时无法启动", `本地连接端口 ${PORT} 不可用，请关闭重复程序后重试。\n${error.message}`); app.quit(); return; }
    createPet(); createMain();
    const icon = nativeImage.createFromPath(path.join(STATIC_ROOT, "branding/lark-icon.png")).resize({ width: 20, height: 20 });
    tray = new Tray(icon); tray.setToolTip("云雀桌面"); rebuildTray();
    tray.on("click", createMain);
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      { label: "云雀", submenu: [{ label: "打开云雀", click: createMain }, { role: "quit", label: "退出云雀桌面" }] },
      { role: "editMenu", label: "编辑" },
      { label: "窗口", submenu: [{ role: "minimize", label: "最小化" }, { label: "显示桌宠", click: () => applyCommand("set-visible", true) }] },
    ]));
    if (process.platform !== "darwin") {
      if (process.defaultApp) app.setAsDefaultProtocolClient("yunque", process.execPath, [path.resolve(__dirname)]);
      else app.setAsDefaultProtocolClient("yunque");
    } else if (!process.defaultApp) {
      app.setAsDefaultProtocolClient("yunque");
    }
    if (process.argv.some(value => value === "--show-pet" || value.startsWith("yunque://show-pet"))) applyCommand("set-visible", true);
    screen.on("display-removed", () => { positionPet(); broadcast(); });
    screen.on("display-metrics-changed", () => { positionPet(); broadcast(); });
    setupCursor();
    console.log(`云雀桌面已启动：${LOCAL_ORIGIN}`);
  }).catch(error => { console.error(error); app.quit(); });
}
app.on("activate", (_event, hasVisibleWindows) => { if (state && !hasVisibleWindows) createMain(); });
app.on("window-all-closed", () => { /* Keep the menu bar companion running. */ });
app.on("before-quit", () => {
  quitting = true; clearInterval(cursorTimer); clearTimeout(saveTimer);
  if (state && preferencesFile) { try { writePreferences(preferencesFile, state); } catch {} }
  bridge?.close(); tray?.destroy();
});
