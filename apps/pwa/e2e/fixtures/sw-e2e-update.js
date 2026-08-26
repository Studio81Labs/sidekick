self.addEventListener("install", () => undefined);
self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
self.addEventListener("message", (event) => {
  if (event.data?.type === "POKER_HERO_ACTIVATE_UPDATE") {
    event.waitUntil(
      new Promise((resolve) => setTimeout(resolve, 1_000)).then(() =>
        self.skipWaiting(),
      ),
    );
  }
});
