/// <reference lib="webworker" />

import {
  POKER_HERO_CACHE_PREFIX,
  isHtmlContentType,
  isNetworkOnlyPath,
} from "../../shared/pwa/serviceWorkerPolicy";

const worker = self as unknown as ServiceWorkerGlobalScope;
const CACHE_NAME = "__POKER_HERO_CACHE_NAME__";
const PRECACHE_URLS = "__POKER_HERO_PRECACHE_URLS__" as unknown as string[];
const PRECACHE_PATHS = new Set(PRECACHE_URLS);

worker.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)),
  );
});

worker.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter(
              (key) =>
                key.startsWith(POKER_HERO_CACHE_PREFIX) && key !== CACHE_NAME,
            )
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => worker.clients.claim()),
  );
});

worker.addEventListener("message", (event) => {
  if (event.data?.type === "POKER_HERO_ACTIVATE_UPDATE") {
    event.waitUntil(worker.skipWaiting());
  }
});

worker.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (
    url.origin !== worker.location.origin ||
    isNetworkOnlyPath(url.pathname)
  ) {
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(networkFirstNavigation(request));
    return;
  }

  if (PRECACHE_PATHS.has(url.pathname) && url.pathname !== "/") {
    event.respondWith(contentAddressedAsset(request, url.pathname));
  }
});

async function networkFirstNavigation(request: Request): Promise<Response> {
  try {
    const response = await fetch(request);
    if (
      response.ok &&
      response.type === "basic" &&
      isHtmlContentType(response.headers.get("content-type"))
    ) {
      const cache = await caches.open(CACHE_NAME);
      await cache.put("/", response.clone()).catch(() => undefined);
    }
    return response;
  } catch (error) {
    const cache = await caches.open(CACHE_NAME);
    const shell = await cache.match("/");
    if (shell) return shell;
    throw error;
  }
}

async function contentAddressedAsset(
  request: Request,
  pathname: string,
): Promise<Response> {
  const cache = await caches.open(CACHE_NAME);
  const cached = await cache.match(pathname);
  if (cached) return cached;

  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    await cache.put(pathname, response.clone());
  }
  return response;
}
