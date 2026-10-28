export const BRIDGE_URL = "http://127.0.0.1:17643";

export class DesktopClient extends EventTarget {
  constructor() {
    super();
    this.native = window.yunqueDesktop;
    this.state = null;
    this.token = "";
    this.polling = false;
    this.pollDelay = 2000;
    this.stopped = false;
    this.onVisibility = () => { if (!document.hidden) this.refresh(); };
    this.onOnline = () => this.refresh();
  }
  async request(path, options = {}) {
    const response = await fetch(`${BRIDGE_URL}${path}`, {
      ...options, credentials: "omit", cache: "no-store", signal: AbortSignal.timeout(1800),
    });
    if (!response.ok) throw new Error("桌面连接暂不可用");
    return response.json();
  }
  accept(state) {
    this.state = state;
    this.dispatchEvent(new CustomEvent("state", { detail: state }));
  }
  async refresh() {
    try {
      if (this.native) this.accept(await this.native.getState());
      else {
        const payload = await this.request("/bridge/state");
        this.token = payload.token;
        this.accept(payload.state);
      }
      this.pollDelay = 1500;
      return true;
    } catch {
      this.pollDelay = 6000;
      if (this.state !== null) { this.state = null; this.dispatchEvent(new Event("disconnected")); }
      return false;
    }
  }
  async command(action, value) {
    if (this.native) { this.accept(await this.native.command(action, value)); return; }
    if (!this.token && !await this.refresh()) throw new Error("请先启动云雀桌面");
    try {
      const payload = await this.request("/bridge/command", {
        method: "POST", headers: { "Content-Type": "application/json", "X-Yunque-Desktop": this.token },
        body: JSON.stringify({ action, value }),
      });
      this.accept(payload.state);
    } catch (error) { this.token = ""; throw error; }
  }
  start() {
    if (this.polling) return;
    this.polling = true;
    if (this.native) this.unsubscribe = this.native.onState(state => this.accept(state));
    document.addEventListener("visibilitychange", this.onVisibility);
    window.addEventListener("online", this.onOnline);
    const poll = async () => {
      if (this.stopped) return;
      if (!document.hidden || !this.state) await this.refresh();
      if (!this.stopped) this.timer = setTimeout(poll, this.native ? 15000 : this.pollDelay);
    };
    poll();
  }
  stop() {
    this.stopped = true; clearTimeout(this.timer); this.unsubscribe?.();
    document.removeEventListener("visibilitychange", this.onVisibility);
    window.removeEventListener("online", this.onOnline);
  }
}
