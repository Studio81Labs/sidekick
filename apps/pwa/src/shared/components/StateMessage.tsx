import type { HTMLAttributes, ReactNode } from "react";

import "./StateMessage.css";

export type StateMessageProps = HTMLAttributes<HTMLElement> & {
  as?: "div" | "p" | "span";
  centered?: boolean;
  children: ReactNode;
  framed?: boolean;
  size?: "default" | "small" | "compact";
  tone?: "default" | "inverse";
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function StateMessage({
  as: Element = "div",
  centered = false,
  children,
  className,
  framed = false,
  size = "default",
  tone = "default",
  ...props
}: StateMessageProps) {
  return (
    <Element
      {...props}
      className={joinClassNames(
        "state-message",
        size !== "default" ? `state-message-${size}` : undefined,
        tone === "inverse" ? "state-message-inverse" : undefined,
        centered ? "state-message-centered" : undefined,
        framed ? "state-message-framed" : undefined,
        className,
      )}
    >
      {children}
    </Element>
  );
}
