import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { ChangeList } from "./ChangeList";

afterEach(() => {
  cleanup();
});

describe("ChangeList", () => {
  it("ChangeList strikes the old value and shows «(хоосон)» for an empty new one", () => {
    const { container } = render(
      <ChangeList
        changes={[
          { field: "Цалин", old: "100", new: "120" },
          { field: "Утас", old: "99112233", new: "" },
        ]}
      />,
    );
    const dl = container.querySelector("dl") as HTMLElement;
    expect(dl.className).toContain("grid-cols-[auto_1fr]");
    const terms = Array.from(container.querySelectorAll("dt")).map((dt) => dt.textContent);
    expect(terms).toEqual(["Цалин", "Утас"]);

    const strikes = container.querySelectorAll("s");
    expect(strikes.length).toBe(2);
    expect(strikes[0].className).toBe("text-slate-400");
    expect(strikes[0].textContent).toBe("100");

    const values = Array.from(container.querySelectorAll("dd")).map((dd) => dd.textContent);
    expect(values).toEqual(["100 → 120", "99112233 → (хоосон)"]);
  });

  it("shows no old value when there was none", () => {
    const { container } = render(<ChangeList changes={[{ field: "Хаяг", old: "", new: "Улаанбаатар" }]} />);
    expect(container.querySelector("s")).toBeNull();
    expect(container.querySelector("dd")?.textContent).toBe("Улаанбаатар");
  });

  it("draws nothing for an empty list", () => {
    const { container } = render(<ChangeList changes={[]} />);
    expect(container.innerHTML).toBe("");
  });
});
