#!/usr/bin/env node

import http from "node:http";
import https from "node:https";

const listenHost = process.env.LARK_PROXY_HOST || "127.0.0.1";
const listenPort = Number(process.env.LARK_PROXY_PORT || 8787);
const targetOrigin = new URL(
  process.env.LARK_PROXY_TARGET || "https://worker.lark.irises.me",
);

function corsHeaders(origin) {
  return {
    "access-control-allow-origin": origin || "http://127.0.0.1:5073",
    "access-control-allow-credentials": "true",
    "access-control-allow-headers": "Content-Type, Cookie",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-max-age": "86400",
    vary: "Origin",
  };
}

function rewriteSetCookie(value) {
  const cookies = Array.isArray(value) ? value : [value];
  return cookies
    .filter(Boolean)
    .map((cookie) =>
      cookie
        .split(";")
        .map((part) => part.trim())
        .filter((part) => !/^secure$/i.test(part))
        .filter((part) => !/^domain=/i.test(part))
        .join("; "),
    );
}

function proxyRequest(clientReq, clientRes) {
  const origin = clientReq.headers.origin || "";

  if (clientReq.method === "OPTIONS") {
    clientRes.writeHead(204, corsHeaders(origin));
    clientRes.end();
    return;
  }

  const targetUrl = new URL(clientReq.url || "/", targetOrigin);
  const headers = { ...clientReq.headers };
  delete headers.host;
  delete headers.origin;
  headers.host = targetOrigin.host;

  const upstreamReq = https.request(
    targetUrl,
    {
      method: clientReq.method,
      headers,
    },
    (upstreamRes) => {
      const responseHeaders = {
        ...upstreamRes.headers,
        ...corsHeaders(origin),
      };

      if (upstreamRes.headers["set-cookie"]) {
        responseHeaders["set-cookie"] = rewriteSetCookie(
          upstreamRes.headers["set-cookie"],
        );
      }

      delete responseHeaders["content-encoding"];
      delete responseHeaders["content-length"];

      clientRes.writeHead(upstreamRes.statusCode || 502, responseHeaders);
      upstreamRes.pipe(clientRes);
    },
  );

  upstreamReq.on("error", (error) => {
    clientRes.writeHead(502, {
      "content-type": "application/json; charset=utf-8",
      ...corsHeaders(origin),
    });
    clientRes.end(
      JSON.stringify({
        ok: false,
        error: "proxy_upstream_error",
        detail: error.message,
      }),
    );
  });

  clientReq.pipe(upstreamReq);
}

const server = http.createServer(proxyRequest);

server.listen(listenPort, listenHost, () => {
  console.log(
    `Lark dev proxy listening on http://${listenHost}:${listenPort} -> ${targetOrigin.origin}`,
  );
});
