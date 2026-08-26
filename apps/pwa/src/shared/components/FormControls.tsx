import { ChevronDown } from "lucide-react";
import {
  cloneElement,
  forwardRef,
  type AnchorHTMLAttributes,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type LabelHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
  useId,
} from "react";

import "./FormControls.css";

export type SelectControlProps = SelectHTMLAttributes<HTMLSelectElement> & {
  containerClassName?: string;
  density?: "default" | "compact";
};

type ButtonControlVariant =
  | "primary"
  | "secondary"
  | "ghost"
  | "danger"
  | "unstyled";
type TextControlAppearance = "default" | "borderless" | "inverse";
type TextControlDensity = "default" | "compact";

export type ButtonControlProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  iconOnly?: boolean;
  variant?: ButtonControlVariant;
};

export type DownloadLinkControlProps =
  AnchorHTMLAttributes<HTMLAnchorElement> & {
    disabled?: boolean;
  };

export type FileInputControlProps = Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type"
>;

type FormFieldControlProps = {
  "aria-describedby"?: string;
  id?: string;
};

export type FormFieldProps = Omit<
  LabelHTMLAttributes<HTMLLabelElement>,
  "children"
> & {
  children: ReactElement<FormFieldControlProps>;
  description?: ReactNode;
  htmlFor?: string;
  label: ReactNode;
  labelClassName?: string;
};

export type TextInputProps = InputHTMLAttributes<HTMLInputElement> & {
  appearance?: TextControlAppearance;
  density?: TextControlDensity;
};

export type TextAreaControlProps =
  TextareaHTMLAttributes<HTMLTextAreaElement> & {
    appearance?: TextControlAppearance;
    density?: TextControlDensity;
  };

function joinClassNames(...classNames: Array<string | undefined>) {
  return classNames.filter(Boolean).join(" ");
}

const BUTTON_VARIANT_CLASS_NAMES: Record<
  ButtonControlVariant,
  string | undefined
> = {
  primary: undefined,
  secondary: "secondary-button",
  ghost: "ghost-button",
  danger: "danger-button",
  unstyled: "unstyled-button",
};

export const ButtonControl = forwardRef<HTMLButtonElement, ButtonControlProps>(
  (
    {
      className,
      iconOnly = false,
      type = "button",
      variant = "primary",
      ...props
    },
    ref,
  ) => (
    <button
      {...props}
      ref={ref}
      type={type}
      className={joinClassNames(
        "button-control",
        BUTTON_VARIANT_CLASS_NAMES[variant],
        iconOnly ? "icon-action" : undefined,
        className,
      )}
    />
  ),
);

ButtonControl.displayName = "ButtonControl";

export const DownloadLinkControl = forwardRef<
  HTMLAnchorElement,
  DownloadLinkControlProps
>(({ className, disabled = false, onClick, tabIndex, ...props }, ref) => (
  <a
    {...props}
    ref={ref}
    className={joinClassNames(className, disabled ? "disabled" : undefined)}
    aria-disabled={disabled}
    tabIndex={disabled ? -1 : tabIndex}
    onClick={(event) => {
      if (disabled) {
        event.preventDefault();
        return;
      }
      onClick?.(event);
    }}
  />
));

DownloadLinkControl.displayName = "DownloadLinkControl";

export const FileInputControl = forwardRef<
  HTMLInputElement,
  FileInputControlProps
>(({ className, ...props }, ref) => (
  <input
    {...props}
    ref={ref}
    type="file"
    className={joinClassNames("file-input-control", className)}
  />
));

FileInputControl.displayName = "FileInputControl";

export function FormField({
  children,
  className,
  description,
  htmlFor,
  label,
  labelClassName,
  ...props
}: FormFieldProps) {
  const generatedId = useId();
  const controlId = htmlFor ?? children.props.id ?? `form-field-${generatedId}`;
  const descriptionId = description ? `${controlId}-description` : undefined;
  const describedBy =
    [children.props["aria-describedby"], descriptionId]
      .filter(Boolean)
      .join(" ") || undefined;
  return (
    <label
      {...props}
      htmlFor={controlId}
      className={joinClassNames("form-field-control", className)}
    >
      <span className={joinClassNames("form-field-copy", labelClassName)}>
        <span className="form-field-label">
          {description ? <strong>{label}</strong> : label}
        </span>
        {description ? (
          <small
            aria-hidden="true"
            className="form-field-description"
            id={descriptionId}
          >
            {description}
          </small>
        ) : null}
      </span>
      {cloneElement(children, {
        "aria-describedby": describedBy,
        id: controlId,
      })}
    </label>
  );
}

export const TextInput = forwardRef<HTMLInputElement, TextInputProps>(
  (
    { appearance = "default", className, density = "default", ...props },
    ref,
  ) => (
    <input
      {...props}
      ref={ref}
      className={joinClassNames(
        "text-input-control",
        appearance !== "default" ? `text-control-${appearance}` : undefined,
        density === "compact" ? "text-control-compact" : undefined,
        className,
      )}
    />
  ),
);

TextInput.displayName = "TextInput";

export const TextAreaControl = forwardRef<
  HTMLTextAreaElement,
  TextAreaControlProps
>(
  (
    { appearance = "default", className, density = "default", ...props },
    ref,
  ) => (
    <textarea
      {...props}
      ref={ref}
      className={joinClassNames(
        "text-area-control",
        appearance !== "default" ? `text-control-${appearance}` : undefined,
        density === "compact" ? "text-control-compact" : undefined,
        className,
      )}
    />
  ),
);

TextAreaControl.displayName = "TextAreaControl";

export const SelectControl = forwardRef<HTMLSelectElement, SelectControlProps>(
  (
    {
      children,
      className,
      containerClassName,
      density = "default",
      disabled,
      ...props
    },
    ref,
  ) => (
    <span
      className={joinClassNames(
        "select-control",
        density === "compact" ? "select-control-compact" : undefined,
        containerClassName,
      )}
      data-disabled={disabled || undefined}
    >
      <select
        {...props}
        ref={ref}
        className={joinClassNames("select-control-input", className)}
        disabled={disabled}
      >
        {children}
      </select>
      <ChevronDown
        className="select-control-icon"
        size={14}
        strokeWidth={2}
        aria-hidden="true"
      />
    </span>
  ),
);

SelectControl.displayName = "SelectControl";
