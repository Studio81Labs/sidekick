import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ActionHistoryField, ActionHistoryRow } from "./ActionHistoryField";

describe("ActionHistoryField", () => {
  it("renders a labeled action list and adds another action", async () => {
    const onAdd = vi.fn();
    render(
      <ActionHistoryField
        addLabel="Add action"
        emptyMessage="No actions recorded"
        heading="Current street history (total BB)"
        itemCount={1}
        onAdd={onAdd}
      >
        <ActionHistoryRow className="completed-action-history-row" index={0}>
          <span>OOP bets 5 BB</span>
        </ActionHistoryRow>
      </ActionHistoryField>,
    );

    const field = screen.getByRole("group", {
      name: "Current street history (total BB)",
    });
    expect(field).toHaveClass("action-history-field");
    expect(field).toHaveTextContent("OOP bets 5 BB");
    expect(screen.getByText("1")).toHaveClass("action-history-index");
    expect(screen.getByText("1").parentElement).toHaveClass(
      "action-history-row",
      "completed-action-history-row",
    );

    await userEvent.click(screen.getByRole("button", { name: "Add action" }));
    expect(onAdd).toHaveBeenCalledOnce();
  });

  it("renders its empty state and honors disabled add controls", () => {
    render(
      <ActionHistoryField
        addDisabled
        addLabel="Add preflop action"
        emptyMessage="No actions recorded"
        heading="Preflop history (total BB)"
        itemCount={0}
        onAdd={vi.fn()}
      >
        <div>Hidden row</div>
      </ActionHistoryField>,
    );

    expect(screen.getByText("No actions recorded")).toBeInTheDocument();
    expect(screen.queryByText("Hidden row")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Add preflop action" }),
    ).toBeDisabled();
  });

  it("forwards container attributes and custom styling", () => {
    render(
      <ActionHistoryField
        addLabel="Add action"
        className="custom-history"
        data-history="completed"
        emptyMessage="No completed streets recorded"
        heading="Completed streets (total BB)"
        itemCount={0}
        onAdd={vi.fn()}
      >
        {null}
      </ActionHistoryField>,
    );

    const field = screen.getByRole("group", {
      name: "Completed streets (total BB)",
    });
    expect(field).toHaveClass("action-history-field", "custom-history");
    expect(field).toHaveAttribute("data-history", "completed");
  });
});
