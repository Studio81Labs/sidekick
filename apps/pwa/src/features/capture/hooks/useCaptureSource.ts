import { useEffect, useRef, useState } from "react";

import {
  captureName,
  displayMediaOptions,
  displaySurfaceLabel,
  displaySurfaceMatchesMode,
  getDisplaySurface,
  stopMediaStream,
  wrongShareModeMessage,
} from "../lib/screenCapture";
import { messageFromError } from "../../../shared/lib/errors";
import {
  shareModeLabel,
  type InputMode,
  type ShareMode,
} from "../lib/captureSource";

interface UseCaptureSourceOptions {
  initialFiles?: readonly File[];
  onError: (message: string | null) => void;
}

export function useCaptureSource({
  initialFiles = [],
  onError,
}: UseCaptureSourceOptions) {
  const [files, setFiles] = useState<File[]>(() => [...initialFiles]);
  const [inputMode, setInputMode] = useState<InputMode>("live");
  const [shareMode, setShareMode] = useState<ShareMode>("window");
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [sourceLabel, setSourceLabel] = useState<string | null>(null);
  const [previewVisible, setPreviewVisible] = useState(false);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  // A browser chooser cannot be cancelled once getDisplayMedia has opened it.
  // Advance this synchronously when the owner stops or unmounts the capture
  // surface so a subsequently granted stream is stopped instead of escaping
  // the now-locked administrator session.
  const shareRequestRef = useRef(0);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      shareRequestRef.current += 1;
    };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    video.srcObject = stream;
    if (stream) {
      try {
        const playPromise = video.play();
        void playPromise?.catch?.(() => undefined);
      } catch {
        // Browsers can delay playback until the element is visible.
      }
    }
  }, [stream]);

  useEffect(() => {
    if (!stream) return;
    const tracks = stream.getTracks();
    const onEnded = () => {
      setStream((current) => (current === stream ? null : current));
      setSourceLabel(null);
      setPreviewVisible(false);
    };
    tracks.forEach((track) => track.addEventListener("ended", onEnded));
    return () => {
      tracks.forEach((track) => {
        track.removeEventListener("ended", onEnded);
        track.stop();
      });
    };
  }, [stream]);

  async function startShare(mode: ShareMode = shareMode) {
    const shareRequest = shareRequestRef.current + 1;
    shareRequestRef.current = shareRequest;
    if (!navigator.mediaDevices?.getDisplayMedia) {
      onError("Screen sharing is not supported in this browser");
      return;
    }
    onError(null);
    try {
      const nextStream = await navigator.mediaDevices.getDisplayMedia(
        displayMediaOptions(mode),
      );
      if (!mountedRef.current || shareRequest !== shareRequestRef.current) {
        stopMediaStream(nextStream);
        return;
      }
      const displaySurface = getDisplaySurface(nextStream);
      if (!displaySurfaceMatchesMode(displaySurface, mode)) {
        stopMediaStream(nextStream);
        setSourceLabel(null);
        setStream(null);
        setPreviewVisible(false);
        onError(wrongShareModeMessage(displaySurface, mode));
        return;
      }
      setSourceLabel(
        displaySurfaceLabel(displaySurface) ?? shareModeLabel(mode),
      );
      setStream(nextStream);
      setPreviewVisible(true);
    } catch (error) {
      if (mountedRef.current && shareRequest === shareRequestRef.current) {
        onError(messageFromError(error, "Screen sharing was cancelled"));
      }
    }
  }

  function stopShare() {
    shareRequestRef.current += 1;
    setSourceLabel(null);
    setStream(null);
    setPreviewVisible(false);
  }

  async function captureFile(): Promise<File> {
    const video = videoRef.current;
    if (!video || !stream) {
      throw new Error("Start screen sharing before capturing");
    }
    if (video.videoWidth === 0 || video.videoHeight === 0) {
      throw new Error(
        "Screen share is still loading; try capture again in a moment",
      );
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const context = canvas.getContext("2d");
    if (!context) throw new Error("Could not prepare screen capture");
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((capturedBlob) => {
        if (capturedBlob) resolve(capturedBlob);
        else reject(new Error("Could not encode screen capture"));
      }, "image/png");
    });
    return new File([blob], captureName(), { type: "image/png" });
  }

  return {
    captureFile,
    files,
    inputMode,
    previewVisible,
    screenSharing: stream !== null,
    setFiles,
    setInputMode,
    setPreviewVisible,
    setShareMode,
    shareMode,
    sourceLabel,
    startShare,
    stopShare,
    videoRef,
  };
}
