const { test } = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const { createBridge, validCommand } = require("../bridge.cjs");
const { normalizePreferences, clampPosition } = require("../preferences.cjs");

test("preferences recover safely from invalid saved values and clamp to an available display", () => {
  assert.deepEqual(normalizePreferences(null), { form: "bird", gazeEnabled: true, position: null });
  assert.deepEqual(normalizePreferences({ form: "other", position: { x: Infinity, y: 5 } }).position, null);
  assert.deepEqual(clampPosition({ x: -999, y: 9999 }, { x: 0, y: 25, width: 1440, height: 875 }, { width: 250, height: 295 }), { x: 0, y: 605 });
  assert.deepEqual(clampPosition({ x: -1000, y: 100 }, { x: -1920, y: 0, width: 1920, height: 1080 }, { width: 250, height: 295 }), { x: -1000, y: 100 });
});
test("only explicit, typed companion commands are accepted", () => {
  assert.equal(validCommand({ action: "set-form", value: "chibi" }), true);
  assert.equal(validCommand({ action: "set-visible", value: "false" }), false);
  assert.equal(validCommand({ action: "capture-screen", value: true }), false);
  assert.equal(validCommand({ action: "set-form", value: "../secret" }), false);
});
test("the loopback bridge rejects untrusted origins, unauthenticated writes and path traversal", async t => {
  let state = { visible: false, form: "bird", gazeEnabled: true };
  const origin = "http://localhost:4173";
  const bridge = createBridge({
    staticRoot: path.resolve(__dirname, "../../static"), origins: [origin],
    getState: () => state,
    command: (action, value) => { if (action === "set-visible") state = { ...state, visible: value }; },
  });
  await new Promise(resolve => bridge.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise(resolve => bridge.close(resolve)));
  const base = `http://127.0.0.1:${bridge.address().port}`;
  const foreign = await fetch(`${base}/bridge/state`, { headers: { Origin: "https://untrusted.example" } });
  assert.equal(foreign.status, 403);
  const handshake = await fetch(`${base}/bridge/state`, { headers: { Origin: origin } });
  assert.equal(handshake.headers.get("Access-Control-Allow-Origin"), origin);
  const { token } = await handshake.json();
  const body = JSON.stringify({ action: "set-visible", value: true });
  const withoutToken = await fetch(`${base}/bridge/command`, { method: "POST", headers: { Origin: origin, "Content-Type": "application/json" }, body });
  assert.equal(withoutToken.status, 403); assert.equal(state.visible, false);
  const missingOrigin = await fetch(`${base}/bridge/command`, { method: "POST", headers: { "X-Yunque-Desktop": token, "Content-Type": "application/json" }, body });
  assert.equal(missingOrigin.status, 403);
  const valid = await fetch(`${base}/bridge/command`, { method: "POST", headers: { Origin: origin, "X-Yunque-Desktop": token, "Content-Type": "application/json" }, body });
  assert.equal(valid.status, 200); assert.equal((await valid.json()).state.visible, true);
  const invalid = await fetch(`${base}/bridge/command`, { method: "POST", headers: { Origin: origin, "X-Yunque-Desktop": token, "Content-Type": "application/json" }, body: JSON.stringify({ action: "capture-screen" }) });
  assert.equal(invalid.status, 400);
  const traversal = await fetch(`${base}/..%2f..%2f.env`);
  assert.equal(traversal.status, 404);
  const page = await fetch(`${base}/`);
  assert.equal(page.status, 200); assert.match(await page.text(), /homeGreeting/);
});
