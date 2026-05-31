const SESSION_COOKIE = "yunque_session";
const PASSWORD_ITERATIONS = 60000;

const encoder = new TextEncoder();

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return corsResponse(null, env, 204, {}, request);
    }

    try {
      if (url.pathname === "/api/auth/register" && request.method === "POST") {
        return register(request, env);
      }
      if (url.pathname === "/api/auth/login" && request.method === "POST") {
        return login(request, env);
      }
      if (url.pathname === "/api/auth/logout" && request.method === "POST") {
        return logout(request, env);
      }
      if (url.pathname === "/api/auth/me" && request.method === "GET") {
        const session = await getSessionUser(request, env);
        return json({ ok: true, user: session?.user || null }, env, 200, {}, request);
      }
      if (url.pathname === "/face_landmarker.task" && request.method === "GET") {
        return proxyPublicAsset(request, env);
      }
      if (url.pathname.startsWith("/api/")) {
        return proxyToPython(request, env);
      }
      return json({ ok: false, error: "not_found" }, env, 404, {}, request);
    } catch (error) {
      return json({ ok: false, error: error.message || "internal_error" }, env, 500, {}, request);
    }
  },
};

async function register(request, env) {
  const { username, password } = await readJson(request);
  const normalized = normalizeUsername(username);
  validatePassword(password);

  const existing = await env.DB.prepare("SELECT id FROM users WHERE username_key = ?")
    .bind(normalized.key)
    .first();
  if (existing) {
    return json({ ok: false, error: "username_taken" }, env, 409, {}, request);
  }

  const userId = crypto.randomUUID();
  const passwordHash = await hashPassword(password);
  const now = new Date().toISOString();
  await env.DB.prepare(
    "INSERT INTO users (id, username, username_key, password_hash, created_at) VALUES (?, ?, ?, ?, ?)"
  )
    .bind(userId, normalized.display, normalized.key, passwordHash, now)
    .run();

  const session = await createSession(env, userId);
  return json(
    { ok: true, user: { id: userId, username: normalized.display } },
    env,
    201,
    { "Set-Cookie": buildSessionCookie(session.token, env) },
    request
  );
}

async function login(request, env) {
  const { username, password } = await readJson(request);
  const normalized = normalizeUsername(username);
  validatePassword(password);

  const user = await env.DB.prepare(
    "SELECT id, username, password_hash FROM users WHERE username_key = ?"
  )
    .bind(normalized.key)
    .first();
  if (!user || !(await verifyPassword(password, user.password_hash))) {
    return json({ ok: false, error: "invalid_credentials" }, env, 401, {}, request);
  }

  const session = await createSession(env, user.id);
  return json(
    { ok: true, user: { id: user.id, username: user.username } },
    env,
    200,
    { "Set-Cookie": buildSessionCookie(session.token, env) },
    request
  );
}

async function logout(request, env) {
  const token = getCookie(request, SESSION_COOKIE);
  if (token) {
    await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?")
      .bind(await sha256Base64url(token))
      .run();
  }
  return json(
    { ok: true },
    env,
    200,
    { "Set-Cookie": clearSessionCookie() },
    request
  );
}

async function proxyToPython(request, env) {
  const session = await getSessionUser(request, env);
  if (!session) {
    return json({ ok: false, error: "unauthorized" }, env, 401, {}, request);
  }

  const url = new URL(request.url);
  const originUrl = new URL(url.pathname + url.search, env.ORIGIN_BASE);
  const headers = new Headers(request.headers);
  headers.set("X-Yunque-User-Id", session.user.id);
  headers.set("X-Yunque-Internal-Secret", env.INTERNAL_SECRET || "");
  headers.delete("Cookie");
  headers.delete("Host");

  const response = await fetch(originUrl, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD" ? undefined : request.body,
    redirect: "manual",
  });
  return withCors(response, env, request);
}

async function proxyPublicAsset(request, env) {
  const url = new URL(request.url);
  const originUrl = new URL(url.pathname + url.search, env.ORIGIN_BASE);
  const response = await fetch(originUrl, { method: request.method });
  return withCors(response, env, request);
}

async function getSessionUser(request, env) {
  const token = getCookie(request, SESSION_COOKIE);
  if (!token) {
    return null;
  }
  const tokenHash = await sha256Base64url(token);
  const row = await env.DB.prepare(
    `SELECT sessions.user_id, sessions.expires_at, users.username
     FROM sessions
     JOIN users ON users.id = sessions.user_id
     WHERE sessions.token_hash = ?`
  )
    .bind(tokenHash)
    .first();
  if (!row) {
    return null;
  }
  if (new Date(row.expires_at).getTime() <= Date.now()) {
    await env.DB.prepare("DELETE FROM sessions WHERE token_hash = ?").bind(tokenHash).run();
    return null;
  }
  return {
    user: {
      id: row.user_id,
      username: row.username,
    },
  };
}

async function createSession(env, userId) {
  const token = randomToken(32);
  const tokenHash = await sha256Base64url(token);
  const now = new Date();
  const maxAge = sessionMaxAge(env);
  const expiresAt = new Date(now.getTime() + maxAge * 1000).toISOString();
  await env.DB.prepare(
    "INSERT INTO sessions (token_hash, user_id, expires_at, created_at) VALUES (?, ?, ?, ?)"
  )
    .bind(tokenHash, userId, expiresAt, now.toISOString())
    .run();
  return { token, expiresAt };
}

async function readJson(request) {
  try {
    return await request.json();
  } catch {
    throw new Error("invalid_json");
  }
}

function normalizeUsername(username) {
  const display = String(username || "").trim();
  if (display.length < 2 || display.length > 32) {
    throw new Error("invalid_username");
  }
  return {
    display,
    key: display.toLocaleLowerCase(),
  };
}

function validatePassword(password) {
  if (typeof password !== "string" || password.length < 8 || password.length > 128) {
    throw new Error("invalid_password");
  }
}

async function hashPassword(password) {
  const salt = randomBytes(16);
  const hash = await pbkdf2(password, salt, PASSWORD_ITERATIONS);
  return `pbkdf2_sha256$${PASSWORD_ITERATIONS}$${base64url(salt)}$${base64url(hash)}`;
}

async function verifyPassword(password, stored) {
  const parts = String(stored || "").split("$");
  if (parts.length !== 4 || parts[0] !== "pbkdf2_sha256") {
    return false;
  }
  const iterations = Number(parts[1]);
  const salt = fromBase64url(parts[2]);
  const expected = fromBase64url(parts[3]);
  const actual = await pbkdf2(password, salt, iterations);
  return timingSafeEqual(actual, expected);
}

async function pbkdf2(password, salt, iterations) {
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt,
      iterations,
    },
    key,
    256
  );
  return new Uint8Array(bits);
}

function timingSafeEqual(a, b) {
  if (a.length !== b.length) {
    return false;
  }
  let diff = 0;
  for (let index = 0; index < a.length; index += 1) {
    diff |= a[index] ^ b[index];
  }
  return diff === 0;
}

async function sha256Base64url(value) {
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(value));
  return base64url(new Uint8Array(digest));
}

function randomToken(size) {
  return base64url(randomBytes(size));
}

function randomBytes(size) {
  const bytes = new Uint8Array(size);
  crypto.getRandomValues(bytes);
  return bytes;
}

function base64url(bytes) {
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function fromBase64url(value) {
  const padded = String(value).replace(/-/g, "+").replace(/_/g, "/").padEnd(
    Math.ceil(String(value).length / 4) * 4,
    "="
  );
  const binary = atob(padded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function getCookie(request, name) {
  const cookieHeader = request.headers.get("Cookie") || "";
  for (const item of cookieHeader.split(";")) {
    const [key, ...valueParts] = item.trim().split("=");
    if (key === name) {
      return valueParts.join("=");
    }
  }
  return "";
}

function buildSessionCookie(token, env) {
  return [
    `${SESSION_COOKIE}=${token}`,
    "Path=/",
    `Max-Age=${sessionMaxAge(env)}`,
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
  ].join("; ");
}

function clearSessionCookie() {
  return [
    `${SESSION_COOKIE}=`,
    "Path=/",
    "Max-Age=0",
    "HttpOnly",
    "Secure",
    "SameSite=Lax",
  ].join("; ");
}

function sessionMaxAge(env) {
  return Math.max(3600, Number(env.SESSION_MAX_AGE_SECONDS || 604800));
}

function allowedOrigins(env) {
  return String(env.ALLOWED_ORIGINS || env.ALLOWED_ORIGIN || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function corsHeaders(env, request = null) {
  const requestOrigin = typeof request === "string" ? request : request?.headers?.get("Origin") || "";
  const origins = allowedOrigins(env);
  const origin = origins.includes(requestOrigin) ? requestOrigin : origins[0] || "";
  const headers = new Headers();
  if (origin) {
    headers.set("Access-Control-Allow-Origin", origin);
    headers.set("Access-Control-Allow-Credentials", "true");
    headers.set("Vary", "Origin");
  }
  headers.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type");
  headers.set("Access-Control-Max-Age", "86400");
  return headers;
}

function corsResponse(body, env, status = 200, extraHeaders = {}, request = null) {
  const headers = corsHeaders(env, request);
  for (const [key, value] of Object.entries(extraHeaders)) {
    headers.set(key, value);
  }
  return new Response(body, { status, headers });
}

function json(payload, env, status = 200, extraHeaders = {}, request = null) {
  return corsResponse(JSON.stringify(payload), env, status, {
    "Content-Type": "application/json; charset=utf-8",
    ...extraHeaders,
  }, request);
}

function withCors(response, env, request = null) {
  const headers = new Headers(response.headers);
  const cors = corsHeaders(env, request);
  for (const [key, value] of cors.entries()) {
    headers.set(key, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}
