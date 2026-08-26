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
