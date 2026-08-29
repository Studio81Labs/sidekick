import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PipelineDialog, type PipelineDialogProps } from "./PipelineDialog";
import type {
  PipelineCapabilities,
  PipelineSelection,
} from "../../../shared/types/pipeline";

afterEach(cleanup);

const capabilities: PipelineCapabilities = {
  defaults: {
    parser_provider: "ocr_cv",
    parser_layout_profile: "fortuna",
  },
  parser_providers: [
    {
      id: "ocr_cv",
      label: "Template OCR",
      available: true,
      unavailable_reason: null,
    },
    {
      id: "llm_vision",
      label: "External vision",
      available: false,
      unavailable_reason: "External parser URL is not configured",
    },
  ],
  parser_layout_profiles: [
    {
      id: "fortuna",
      label: "Fortuna",
      available: true,
      unavailable_reason: null,
    },
    {
      id: "generic",
      label: "Generic",
      available: true,
      unavailable_reason: null,
    },
  ],
  administrative_ocr_test: { enabled: false },
};

const selection: PipelineSelection = { ...capabilities.defaults };

function dialogProps(
  overrides: Partial<PipelineDialogProps> = {},
): PipelineDialogProps {
  return {
    capabilities,
    compatibleLayouts: capabilities.parser_layout_profiles,
    loading: false,
    onClose: vi.fn(),
    onParserChange: vi.fn(),
    onParserLayoutChange: vi.fn(),
    selection,
    ...overrides,
  };
}

describe("PipelineDialog", () => {
  it("renders installed plugins and delegates controlled selection changes", async () => {
    const props = dialogProps();
    render(<PipelineDialog {...props} />);

    expect(
      screen.getByRole("dialog", { name: "Analysis plugins" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Recognition")).toHaveValue("ocr_cv");
    expect(screen.getByLabelText("Table layout")).toHaveValue("fortuna");
    expect(screen.queryByLabelText("Recommendation")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Solver engine")).not.toBeInTheDocument();
    expect(
      screen.getByText(/External parser URL is not configured/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "External vision (unavailable)" }),
    ).toBeDisabled();

    await userEvent.selectOptions(
      screen.getByLabelText("Recognition"),
      "ocr_cv",
    );
    await userEvent.selectOptions(
      screen.getByLabelText("Table layout"),
      "generic",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Close analysis plugin settings" }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Done" }));

    expect(props.onParserChange).toHaveBeenCalledWith("ocr_cv");
    expect(props.onParserLayoutChange).toHaveBeenCalledWith("generic");
    expect(props.onClose).toHaveBeenCalledTimes(2);
  });

  it("renders loading and unavailable states", () => {
    const { rerender } = render(
      <PipelineDialog {...dialogProps({ loading: true })} />,
    );

    expect(
      screen.getByText("Reading installed plugins..."),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Recognition")).not.toBeInTheDocument();

    rerender(
      <PipelineDialog
        {...dialogProps({ capabilities: null, selection: null })}
      />,
    );

    expect(
      screen.getByText("Plugin details are unavailable."),
    ).toBeInTheDocument();
  });
});
