import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { OneTimeLogin } from "./OneTimeLogin";

afterEach(() => {
  cleanup();
});

describe("OneTimeLogin", () => {
  it("shows the username and the temporary password", () => {
    const { container } = render(<OneTimeLogin login={{ username: "bat.bold", password: "Tr7-kx92" }} />);
    expect(container.querySelector("#one-time-login")).not.toBeNull();
    expect(screen.getByText("bat.bold").className).toContain("font-mono");
    expect(screen.getByText("Tr7-kx92").className).toContain("select-all");
  });

  it("«Ойлголоо, хаах» removes the card", () => {
    const { container } = render(<OneTimeLogin login={{ username: "bat.bold", password: "Tr7-kx92" }} />);
    fireEvent.click(screen.getByRole("button", { name: "Ойлголоо, хаах" }));
    expect(container.querySelector("#one-time-login")).toBeNull();
  });
});
