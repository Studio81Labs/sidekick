self.addEventListener("install", () => undefined);
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("message", (event) => {
  if (event.data?.type === "POKER_HERO_ACTIVATE_UPDATE") {
    event.waitUntil(self.skipWaiting());
  }
});
