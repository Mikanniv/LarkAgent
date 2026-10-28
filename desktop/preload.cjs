const { contextBridge, ipcRenderer } = require("electron");
const subscribe = (channel, callback) => {
  const listener = (_event, value) => callback(value);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
};
contextBridge.exposeInMainWorld("yunqueDesktop", {
  apiBase: "",
  getState: () => ipcRenderer.invoke("companion:get-state"),
  command: (action, value) => ipcRenderer.invoke("companion:command", { action, value }),
  onState: callback => subscribe("companion:state", callback),
  onCursor: callback => subscribe("companion:cursor", callback),
  onOpenChat: callback => subscribe("companion:open-chat", callback),
  setHitTest: hit => ipcRenderer.send("companion:hit-test", Boolean(hit)),
  beginDrag: () => ipcRenderer.send("companion:drag-start"),
  endDrag: () => ipcRenderer.send("companion:drag-end"),
  showMenu: () => ipcRenderer.send("companion:menu"),
});
