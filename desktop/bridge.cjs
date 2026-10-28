const http = require("node:http");
const https = require("node:https");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");

const DEFAULT_ORIGINS = [
  "http://127.0.0.1:17643", "http://localhost:17643",
  "http://127.0.0.1:8001", "http://localhost:8001",
  "http://127.0.0.1:4173", "http://localhost:4173",
  "https://lark.irises.me", "https://worker.lark.irises.me",
];
const MIME = { ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml", ".ico": "image/x-icon", ".glb": "model/gltf-binary", ".wasm": "application/wasm", ".p2lrt": "application/octet-stream", ".txt": "text/plain; charset=utf-8" };
const ACTIONS = new Set(["set-visible", "set-form", "set-gaze", "open-main"]);

function validCommand({ action, value } = {}) {
  return ACTIONS.has(action) && (action === "open-main" ||
    action === "set-form" && ["bird", "chibi"].includes(value) ||
    ["set-visible", "set-gaze"].includes(action) && typeof value === "boolean");
}
function createBridge({ staticRoot, getState, command, apiBase = "http://127.0.0.1:8001", origins = DEFAULT_ORIGINS }) {
  const token = crypto.randomBytes(32).toString("hex");
  const allowedOrigins = new Set(origins);
  const root = path.resolve(staticRoot);
  const api = new URL(apiBase);
  if (!["http:", "https:"].includes(api.protocol)) throw new Error("Unsupported API protocol");
  const server = http.createServer(async (req, res) => {
    const host = req.headers.host?.split(":")[0];
    if (!["127.0.0.1", "localhost"].includes(host)) { res.writeHead(403); res.end(); return; }
    const origin = req.headers.origin;
    if (origin && !allowedOrigins.has(origin)) { res.writeHead(403); res.end(); return; }
    if (origin) {
      res.setHeader("Access-Control-Allow-Origin", origin);
      res.setHeader("Vary", "Origin");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Yunque-Desktop");
      res.setHeader("Access-Control-Allow-Private-Network", "true");
    }
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("X-Content-Type-Options", "nosniff");
    const json = (status, data) => { res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" }); res.end(JSON.stringify(data)); };
    if (req.method === "OPTIONS") { res.writeHead(204); res.end(); return; }
    let url;
    try { url = new URL(req.url, "http://127.0.0.1"); }
    catch { json(400, { error: "Invalid URL" }); return; }
    if (url.pathname === "/bridge/state" && req.method === "GET") { json(200, { state: getState(), token }); return; }
    if (url.pathname === "/bridge/command" && req.method === "POST") {
      if (!origin || !allowedOrigins.has(origin) || req.headers["x-yunque-desktop"] !== token || !req.headers["content-type"]?.startsWith("application/json")) {
        json(403, { error: "Desktop connection not authorized" }); return;
      }
      try {
        let body = "";
        for await (const chunk of req) {
          body += chunk;
          if (Buffer.byteLength(body) > 2048) { json(413, { error: "Request too large" }); return; }
        }
        const input = JSON.parse(body);
        if (!validCommand(input)) { json(400, { error: "Invalid command" }); return; }
        await command(input.action, input.value);
        json(200, { state: getState() });
      } catch { json(400, { error: "Unable to apply desktop command" }); }
      return;
    }
    // Only the desktop app's own page can use its backend proxy.
    if (url.pathname.startsWith("/api/")) {
      if (origin && origin !== `http://${req.headers.host}`) { json(403, { error: "Use the website's own API connection" }); return; }
      const target = new URL(`${url.pathname}${url.search}`, api);
      const headers = { ...req.headers, host: api.host };
      delete headers.origin; delete headers["x-yunque-desktop"];
      const transport = api.protocol === "https:" ? https : http;
      const upstream = transport.request(target, { method: req.method, headers, timeout: 30000 }, response => {
        const responseHeaders = { ...response.headers };
        delete responseHeaders["access-control-allow-origin"];
        res.writeHead(response.statusCode, responseHeaders);
        response.pipe(res);
      });
      upstream.on("error", () => { if (!res.headersSent) json(503, { error: "尚未连接云雀后端，请先启动后端服务。" }); else res.destroy(); });
      upstream.on("timeout", () => upstream.destroy());
      req.pipe(upstream); return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") { json(405, { error: "Method not allowed" }); return; }
    let filename;
    try {
      filename = path.resolve(root, `.${decodeURIComponent(url.pathname === "/" ? "/index.html" : url.pathname)}`);
      if (!filename.startsWith(`${root}${path.sep}`)) throw new Error("Outside static root");
      const real = await fs.promises.realpath(filename);
      if (!real.startsWith(`${root}${path.sep}`)) throw new Error("Outside static root");
      const type = MIME[path.extname(filename)];
      if (!type || !(await fs.promises.stat(filename)).isFile()) throw new Error("Not an asset");
      res.setHeader("Content-Security-Policy", "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' http://127.0.0.1:17643; object-src 'none'; base-uri 'self'; frame-ancestors 'none'");
      res.writeHead(200, { "Content-Type": type });
      if (req.method === "HEAD") res.end(); else fs.createReadStream(filename).pipe(res);
    } catch { json(404, { error: "Not found" }); }
  });
  return server;
}
module.exports = { createBridge, validCommand, DEFAULT_ORIGINS };
