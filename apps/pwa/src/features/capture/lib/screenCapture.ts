import { shareModeLabel, type ShareMode } from "./captureSource";

export type ExtendedDisplayMediaOptions = DisplayMediaStreamOptions & {
  monitorTypeSurfaces?: "include" | "exclude";
  preferCurrentTab?: boolean;
  selfBrowserSurface?: "include" | "exclude";
  surfaceSwitching?: "include" | "exclude";
};

export type DisplayMediaTrackSettings = MediaTrackSettings & {
  displaySurface?: unknown;
};

export function captureName(): string {
  return `screen-capture-${new Date().toISOString().replace(/[:.]/g, "-")}.png`;
}

export function displaySurfaceLabel(displaySurface: unknown): string | null {
  if (displaySurface === "browser") {
    return "Tab";
  }
  if (displaySurface === "window") {
    return "Window";
  }
  if (displaySurface === "monitor") {
    return "Screen";
  }
  return null;
}

export function displayMediaOptions(
  mode: ShareMode,
): ExtendedDisplayMediaOptions {
  const options: ExtendedDisplayMediaOptions = {
    audio: false,
    monitorTypeSurfaces: mode === "monitor" ? "include" : "exclude",
    preferCurrentTab: false,
    selfBrowserSurface: "exclude",
    surfaceSwitching: mode === "browser" ? "include" : "exclude",
    video: {
      frameRate: 8,
      displaySurface: mode,
    } as MediaTrackConstraints,
  };

  return options;
}

export function displaySurfaceMatchesMode(
  displaySurface: unknown,
  mode: ShareMode,
): boolean {
  if (
    displaySurface !== "browser" &&
    displaySurface !== "window" &&
    displaySurface !== "monitor"
  ) {
    return true;
  }
  return displaySurface === mode;
}

export function stopMediaStream(stream: MediaStream): void {
  stream.getTracks().forEach((track) => track.stop());
}

export function wrongShareModeMessage(
  displaySurface: unknown,
  mode: ShareMode,
): string {
  const selectedLabel =
    displaySurfaceLabel(displaySurface) ?? "Different source";
  const expectedLabel = shareModeLabel(mode).toLowerCase();
  return `${selectedLabel} was selected. Choose a ${expectedLabel} in the browser share picker, or switch the source type before sharing.`;
}

export function getDisplaySurface(stream: MediaStream): unknown {
  return (
    stream.getVideoTracks()[0]?.getSettings() as
      | DisplayMediaTrackSettings
      | undefined
  )?.displaySurface;
}
