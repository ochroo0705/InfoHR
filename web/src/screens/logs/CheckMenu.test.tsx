import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CheckMenu } from "./CheckMenu";

const OPTIONS = [
  { value: "hire", label: "Томилгоо" },
  { value: "leave", label: "Чөлөө" },
  { value: "salary", label: "Цалин" },
];

describe("CheckMenu", () => {
  afterEach(() => {
    cleanup();
  });

  it("CheckMenu shows the count in the summary", () => {
    const { container, rerender } = render(
      <CheckMenu label="Төрөл" options={OPTIONS} selected={[]} onChange={() => {}} />,
    );
    const summary = container.querySelector("summary") as HTMLElement;
    expect(summary.textContent).toBe("Төрөл ▾");

    rerender(<CheckMenu label="Төрөл" options={OPTIONS} selected={["hire", "leave"]} onChange={() => {}} />);
    expect((container.querySelector("summary") as HTMLElement).textContent).toBe("Төрөл · 2 ▾");
  });

  it("CheckMenu calls onChange with the ticked values", () => {
    const onChange = vi.fn();
    const { container } = render(
      <CheckMenu label="Ангилал" options={OPTIONS} selected={["hire"]} onChange={onChange} />,
    );
    const boxes = container.querySelectorAll<HTMLInputElement>("input[type=checkbox]");
    expect(boxes.length).toBe(3);
    expect(boxes[0].checked).toBe(true);
    expect(boxes[1].checked).toBe(false);

    fireEvent.click(boxes[2]);
    expect(onChange).toHaveBeenLastCalledWith(["hire", "salary"]);

    fireEvent.click(boxes[0]);
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it("CheckMenu closes on an outside click", () => {
    const { container } = render(
      <div>
        <button type="button">outside</button>
        <CheckMenu label="Төрөл" options={OPTIONS} selected={[]} onChange={() => {}} />
      </div>,
    );
    const details = container.querySelector("details") as HTMLDetailsElement;
    fireEvent.click(container.querySelector("summary") as HTMLElement);
    expect(details.open).toBe(true);

    fireEvent.click(screen.getByText("outside"));
    expect(details.open).toBe(false);
  });
});
