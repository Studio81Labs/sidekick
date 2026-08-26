import { type ReactNode } from "react";
import { Toaster } from "sonner";

type AnalyzerLayoutProps = {
  children: ReactNode;
};

export function AnalyzerLayout({ children }: AnalyzerLayoutProps) {
  return (
    <main className="app-shell">
      <Toaster
        closeButton
        containerAriaLabel="App notifications"
        expand={false}
        offset={{ right: 18, top: 88 }}
        position="top-right"
        richColors
        toastOptions={{
          classNames: {
            closeButton: "app-toast-close",
            error: "app-toast-error",
            title: "app-toast-title",
            toast: "app-toast",
            warning: "app-toast-warning",
          },
          duration: 6000,
        }}
      />
      {children}
    </main>
  );
}

export function AnalyzerWorkspaceLayout({ children }: AnalyzerLayoutProps) {
  return <section className="app-workspace">{children}</section>;
}

export function AnalyzerControlRail({ children }: AnalyzerLayoutProps) {
  return (
    <aside className="control-rail" aria-label="Capture, queue and history">
      {children}
    </aside>
  );
}

export function AnalyzerDialogHost({ children }: AnalyzerLayoutProps) {
  return <>{children}</>;
}
