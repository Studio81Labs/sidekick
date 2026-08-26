export type InputMode = "live" | "upload";
export type ShareMode = "browser" | "window" | "monitor";

const SHARE_MODE_LABELS: Readonly<Record<ShareMode, string>> = {
  browser: "Tab",
  window: "Window",
  monitor: "Screen",
};

export function shareModeLabel(mode: ShareMode): string {
  return SHARE_MODE_LABELS[mode];
}
