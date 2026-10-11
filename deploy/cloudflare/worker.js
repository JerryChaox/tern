import { DurableObject } from "cloudflare:workers";
import { Container, getContainer } from "@cloudflare/containers";

export class TernContainer extends Container {
  defaultPort = 8787;
  sleepAfter = "20m";
}

// Exact per-IP sliding window. State lives in memory; an evicted (idle) object simply starts fresh.
export class RateLimiter extends DurableObject {
  hits = [];
  allow(limit, windowMs) {
    const now = Date.now();
    this.hits = this.hits.filter((t) => now - t < windowMs);
    if (this.hits.length >= limit) return false;
    this.hits.push(now);
    return true;
  }
}

const DB_KEY = "tern.db";
const SYNC_EVERY_MS = 60_000;
let syncedAt = 0; // per isolate; a container idle long enough to sleep is re-checked anyway

export default {
  async fetch(request, env) {
    const allow = (env.ALLOW_IPS || "").split(",").map((s) => s.trim()).filter(Boolean);
    if (allow.length && !allow.includes(request.headers.get("cf-connecting-ip"))) {
      return new Response("Forbidden", { status: 403 });
    }
    const ip = request.headers.get("cf-connecting-ip") || "unknown";
    const limiter = env.RATE.get(env.RATE.idFromName(ip));
    if (!(await limiter.allow(Number(env.RATE_LIMIT), Number(env.RATE_WINDOW_S) * 1000))) {
      return new Response("Too many requests", { status: 429, headers: { "retry-after": env.RATE_WINDOW_S } });
    }
    const url = new URL(request.url);
    if (url.pathname.startsWith("/__tern")) return new Response("Not found", { status: 404 });
    if (request.method !== "GET" && request.method !== "HEAD") {
      return Response.json({ error: "线上为只读副本，修改请在本地进行" }, { status: 403 });
    }
    const container = getContainer(env.TERN, "main");
    await syncDatabase(container, env);
    return container.fetch(request);
  },
};

// Push the latest published database into the container when its copy is missing or stale.
async function syncDatabase(container, env) {
  if (Date.now() - syncedAt < SYNC_EVERY_MS) return;
  const head = await env.DATA.head(DB_KEY);
  if (!head) throw new Error(`R2 object ${DB_KEY} not found; publish from the local instance first`);
  const current = await (await container.fetch("http://tern/__tern/version")).json();
  if (current.etag !== head.etag) {
    const obj = await env.DATA.get(DB_KEY);
    const res = await container.fetch("http://tern/__tern/load", {
      method: "PUT",
      headers: { "x-etag": head.etag, "content-length": String(obj.size) },
      body: obj.body,
    });
    if (!res.ok) throw new Error(`database load failed: ${res.status} ${await res.text()}`);
  }
  syncedAt = Date.now();
}
