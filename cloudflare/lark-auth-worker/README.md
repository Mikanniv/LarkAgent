# Yunque Auth Worker

Cloudflare Worker for Yunque authentication and API proxying.

It owns:

- `/api/auth/register`
- `/api/auth/login`
- `/api/auth/logout`
- `/api/auth/me`
- authenticated proxying for other `/api/*` requests

It does not run emotion models, Chroma, AI diary generation, or Python inference.

## Setup

1. Install the local Wrangler dependency:

```bash
npm install
```

2. Apply the D1 schema:

```bash
npm run db:init
```

3. Set the shared backend secret:

```bash
npm run secret:internal
```

4. Deploy:

```bash
npm run deploy
```

## Routing

Recommended DNS/routing:

```text
lark.irises.me          -> Cloudflare Pages frontend
worker.lark.irises.me   -> this Worker
api.lark.irises.me      -> existing Python backend origin
```

The frontend should call `https://worker.lark.irises.me`.

The Worker forwards authenticated business requests to `ORIGIN_BASE`, currently
configured as `https://api.lark.irises.me`.

## Backend contract

After authentication, the Worker forwards:

```text
X-Yunque-User-Id: <user id>
X-Yunque-Internal-Secret: <shared secret>
```

The Python backend should reject requests with a missing or wrong
`X-Yunque-Internal-Secret`, then use `X-Yunque-User-Id` instead of `local_user`.
