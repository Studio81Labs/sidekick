import { createRef, type MouseEvent as ReactMouseEvent } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  ButtonControl,
  DownloadLinkControl,
  FileInputControl,
  FormField,
  SelectControl,
  TextAreaControl,
  TextInput,
} from "./FormControls";

describe("ButtonControl", () => {
  it("defaults to a non-submitting primary button and forwards behavior", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();

    render(<ButtonControl onClick={onClick}>Analyze</ButtonControl>);

    const button = screen.getByRole("button", { name: "Analyze" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("button-control");

    await user.click(button);

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("applies semantic variants, icon sizing, and explicit submit behavior", () => {
    render(
      <ButtonControl
        type="submit"
        variant="danger"
        iconOnly
        className="delete-hand"
        aria-label="Delete hand"
        disabled
      />,
    );

    const button = screen.getByRole("button", { name: "Delete hand" });
    expect(button).toHaveAttribute("type", "submit");
    expect(button).toBeDisabled();
    expect(button).toHaveClass(
      "button-control",
      "danger-button",
      "icon-action",
      "delete-hand",
    );
  });

  it("supports controls whose consumers own all visual states", () => {
    render(<ButtonControl variant="unstyled">Segment</ButtonControl>);

    expect(screen.getByRole("button", { name: "Segment" })).toHaveClass(
      "button-control",
      "unstyled-button",
    );
  });
});

describe("DownloadLinkControl", () => {
  it("preserves native download behavior when enabled", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn((event: ReactMouseEvent<HTMLAnchorElement>) => {
      event.preventDefault();
    });

    render(
      <DownloadLinkControl
        href="/api/export"
        download="hands.zip"
        className="export-link"
        onClick={onClick}
      >
        Export hands
      </DownloadLinkControl>,
    );

    const link = screen.getByRole("link", { name: "Export hands" });
    expect(link).toHaveAttribute("href", "/api/export");
    expect(link).toHaveAttribute("download", "hands.zip");
    expect(link).toHaveClass("export-link");
    expect(link).toHaveAttribute("aria-disabled", "false");

    await user.click(link);

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("removes disabled downloads from tab order and blocks activation", () => {
    const onClick = vi.fn();

    render(
      <DownloadLinkControl href="/api/export" disabled onClick={onClick}>
        Export disabled hands
      </DownloadLinkControl>,
    );

    const link = screen.getByRole("link", { name: "Export disabled hands" });
    const clickEvent = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
    });

    expect(link).toHaveClass("disabled");
    expect(link).toHaveAttribute("aria-disabled", "true");
    expect(link).toHaveAttribute("tabindex", "-1");
    expect(link.dispatchEvent(clickEvent)).toBe(false);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("FileInputControl", () => {
  it("provides a hidden file input and forwards native upload behavior", async () => {
    const user = userEvent.setup();
    const inputRef = createRef<HTMLInputElement>();
    const onChange = vi.fn();

    render(
      <FileInputControl
        ref={inputRef}
        aria-label="Import screenshots"
        accept="image/*"
        multiple
        onChange={onChange}
      />,
    );

    const input = screen.getByLabelText("Import screenshots");
    const files = [
      new File(["first"], "first.png", { type: "image/png" }),
      new File(["second"], "second.png", { type: "image/png" }),
    ];

    expect(input).toHaveAttribute("type", "file");
    expect(input).toHaveAttribute("accept", "image/*");
    expect(input).toHaveAttribute("multiple");
    expect(input).toHaveClass("file-input-control");
    expect(inputRef.current).toBe(input);

    await user.upload(input, files);

    expect(Array.from((input as HTMLInputElement).files ?? [])).toEqual(files);
    expect(onChange).toHaveBeenCalledTimes(1);
  });
});

describe("FormField", () => {
  it("associates a control with shared label and description markup", () => {
    render(
      <FormField
        className="provider-field"
        description="Used for post-hand analysis"
        htmlFor="provider"
        label="Provider"
        labelClassName="provider-label"
      >
        <TextInput id="provider" defaultValue="Local solver" />
      </FormField>,
    );

    const provider = screen.getByRole("textbox", { name: "Provider" });
    expect(provider).toHaveValue("Local solver");
    expect(provider).toHaveAccessibleDescription("Used for post-hand analysis");
    expect(
      screen.getByText("Provider").closest(".form-field-copy"),
    ).toHaveClass("form-field-copy", "provider-label");
    expect(screen.getByText("Used for post-hand analysis")).toHaveClass(
      "form-field-description",
    );
    expect(screen.getByText("Provider").closest("label")).toHaveClass(
      "form-field-control",
      "provider-field",
    );
  });

  it("supports wrapping labels without a description", () => {
    render(
      <FormField label="Title">
        <TextInput defaultValue="Button bluff" />
      </FormField>,
    );

    expect(screen.getByRole("textbox", { name: "Title" })).toHaveValue(
      "Button bluff",
    );
  });
});

describe("text controls", () => {
  it("forwards native input properties and custom classes", () => {
    render(
      <TextInput
        aria-label="Pot size"
        appearance="borderless"
        className="pot-input"
        defaultValue="12.5"
        density="compact"
        inputMode="decimal"
        disabled
      />,
    );

    const input = screen.getByRole("textbox", { name: "Pot size" });
    expect(input).toHaveValue("12.5");
    expect(input).toBeDisabled();
    expect(input).toHaveAttribute("inputmode", "decimal");
    expect(input).toHaveClass(
      "text-input-control",
      "text-control-borderless",
      "text-control-compact",
      "pot-input",
    );
  });

  it("forwards native textarea behavior and custom classes", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <TextAreaControl
        aria-label="Lesson note"
        appearance="inverse"
        className="lesson-note"
        maxLength={24}
        onChange={onChange}
      />,
    );

    const textarea = screen.getByRole("textbox", { name: "Lesson note" });
    expect(textarea).toHaveClass(
      "text-area-control",
      "text-control-inverse",
      "lesson-note",
    );
    expect(textarea).toHaveAttribute("maxlength", "24");

    await user.type(textarea, "Review river sizing");

    expect(textarea).toHaveValue("Review river sizing");
    expect(onChange).toHaveBeenCalled();
  });
});

describe("SelectControl", () => {
  it("preserves native select behavior and applies shared styling", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();

    render(
      <SelectControl
        aria-label="Street"
        defaultValue="flop"
        onChange={onChange}
      >
        <option value="flop">Flop</option>
        <option value="turn">Turn</option>
      </SelectControl>,
    );

    const select = screen.getByRole("combobox", { name: "Street" });
    expect(select).toHaveClass("select-control-input");

    await user.selectOptions(select, "turn");

    expect(select).toHaveValue("turn");
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it("forwards disabled state and custom classes", () => {
    render(
      <SelectControl
        aria-label="Provider"
        className="provider-select"
        containerClassName="provider-control"
        density="compact"
        disabled
      >
        <option>Local solver</option>
      </SelectControl>,
    );

    const select = screen.getByRole("combobox", { name: "Provider" });
    expect(select).toBeDisabled();
    expect(select).toHaveClass("select-control-input", "provider-select");
    expect(select.parentElement).toHaveClass(
      "select-control",
      "provider-control",
    );
    expect(select.parentElement).toHaveClass("select-control-compact");
    expect(select.parentElement).toHaveAttribute("data-disabled", "true");
  });
});
