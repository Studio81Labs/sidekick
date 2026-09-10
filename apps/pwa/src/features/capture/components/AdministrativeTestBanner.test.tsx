import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdministrativeTestBanner } from "./AdministrativeTestBanner";

afterEach(cleanup);

describe("AdministrativeTestBanner", () => {
  it("marks the capture surface as administrative and can lock it", async () => {
    const onLock = vi.fn();
    render(<AdministrativeTestBanner lockDisabled={false} onLock={onLock} />);

    expect(
      screen.getByRole("note", { name: "Administrative OCR test mode" }),
    ).toHaveTextContent(
      "Uploads and captures produce administrative OCR test data, not player analysis.",
    );
    await userEvent.click(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    );

    expect(onLock).toHaveBeenCalledOnce();
  });

  it("disables locking while an upload is running", () => {
    render(<AdministrativeTestBanner lockDisabled onLock={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: "Lock administrator tools" }),
    ).toBeDisabled();
  });
});
