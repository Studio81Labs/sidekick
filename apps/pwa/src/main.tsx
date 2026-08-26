import React from "react";
import ReactDOM from "react-dom/client";

import "./app/global.css";
import {
  AppErrorBoundary,
  captureBrowserException,
  configureBrowserErrorMonitoring,
  FatalError,
} from "./app/errorMonitoring";

async function bootstrap() {
  await configureBrowserErrorMonitoring();
  const root = ReactDOM.createRoot(document.getElementById("root")!);

  try {
    const { default: App } = await import("./app/App");
    root.render(
      <React.StrictMode>
        <AppErrorBoundary>
          <App />
        </AppErrorBoundary>
      </React.StrictMode>,
    );
  } catch (error) {
    captureBrowserException(error, "application_bootstrap");
    root.render(<FatalError />);
  }
}

void bootstrap();
