import type { ButtonHTMLAttributes } from "react";

import { ButtonControl } from "./FormControls";
import "./ToggleControl.css";

type ToggleControlProps = Omit<
  ButtonHTMLAttributes<HTMLButtonElement>,
  "aria-checked" | "children" | "role"
> & {
  checked: boolean;
  description: string;
  title: string;
};

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

export function ToggleControl({
  checked,
  className,
  description,
  title,
  type = "button",
  ...props
}: ToggleControlProps) {
  return (
    <ButtonControl
      {...props}
      type={type}
      variant="unstyled"
      className={joinClassNames("toggle-control", className)}
      role="switch"
      aria-checked={checked}
    >
      <span className="toggle-control-copy">
        <strong>{title}</strong>
        <small>{description}</small>
      </span>
      <span
        className={checked ? "switch-control active" : "switch-control"}
        aria-hidden="true"
      >
        <span />
      </span>
    </ButtonControl>
  );
}
