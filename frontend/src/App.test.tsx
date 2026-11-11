import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "./App";

describe("login shell", () => {
  it("renders V3 brand and login form", () => {
    render(<App />);
    expect(screen.getByText("ETERNAL PRODUCTION V3")).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});
