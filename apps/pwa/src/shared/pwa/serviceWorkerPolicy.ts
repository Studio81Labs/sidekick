export const POKER_HERO_CACHE_PREFIX = "poker-hero-shell-";

function matchesPrivatePath(pathname: string): boolean {
  return (
    pathname === "/api" || pathname.startsWith("/api/") || pathname === "/mcp"
  );
}

export function isNetworkOnlyPath(pathname: string): boolean {
  let candidate = pathname;
  for (let depth = 0; depth < 4; depth += 1) {
    if (matchesPrivatePath(candidate)) return true;
    if (!candidate.includes("%")) return false;
    try {
      candidate = decodeURIComponent(candidate);
    } catch {
      return true;
    }
  }
  return candidate.includes("%") || matchesPrivatePath(candidate);
}

export function isContentAddressedAssetPath(pathname: string): boolean {
  return /^\/assets\/.+-[A-Za-z0-9_-]{8,}\.[^/]+$/.test(pathname);
}

export function isHtmlContentType(contentType: string | null): boolean {
  return contentType?.split(";", 1)[0]?.trim().toLowerCase() === "text/html";
}
