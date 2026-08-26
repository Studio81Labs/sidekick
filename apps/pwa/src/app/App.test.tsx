import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import App from "./App";

vi.mock("./routes", () => ({
  AppRoutes: () => <div>Application routes</div>,
}));

describe("App", () => {
  it("provides the browser router shell for application routes", () => {
    render(<App />);

    expect(screen.getByText("Application routes")).toBeInTheDocument();
  });
});
