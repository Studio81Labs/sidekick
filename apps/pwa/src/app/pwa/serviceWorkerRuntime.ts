export function isHtmlResponse(response: Response): boolean {
  return (
    response.headers
      .get("content-type")
      ?.split(";", 1)[0]
      ?.trim()
      .toLowerCase() === "text/html"
  );
}

export function isExpectedPrecacheResponse(
  pathname: string,
  response: Response,
): boolean {
  if (!response.ok || response.redirected) return false;
  return pathname === "/"
    ? isHtmlResponse(response)
    : !isHtmlResponse(response);
}

export async function precacheVersion(
  cacheName: string,
  pathnames: readonly string[],
): Promise<void> {
  try {
    const responses = await Promise.all(
      pathnames.map(async (pathname) => {
        const response = await fetch(pathname, { cache: "reload" });
        if (!isExpectedPrecacheResponse(pathname, response)) {
          throw new Error(`Invalid precache response for ${pathname}`);
        }
        return [pathname, response] as const;
      }),
    );
    const cache = await caches.open(cacheName);
    await Promise.all(
      responses.map(([pathname, response]) =>
        cache.put(pathname, response.clone()),
      ),
    );
  } catch (error) {
    await caches.delete(cacheName);
    throw error;
  }
}

export async function isPwaOriginReachable(
  signal?: AbortSignal,
): Promise<boolean> {
  if (!navigator.onLine) return false;
  try {
    const response = await fetch("/manifest.webmanifest", {
      cache: "no-store",
      credentials: "same-origin",
      method: "HEAD",
      signal,
    });
    return response.ok && !isHtmlResponse(response);
  } catch {
    return false;
  }
}

export async function networkFirstNavigation(
  request: Request,
  cacheName: string,
): Promise<Response> {
  try {
    // The install-time HTML and its hashed assets are one immutable version.
    // Online navigation may display newer HTML, but the active worker must not
    // persist it before the matching waiting worker is explicitly activated.
    return await fetch(request);
  } catch (error) {
    const cache = await caches.open(cacheName);
    const shell = await cache.match("/");
    if (shell) return shell;
    throw error;
  }
}
