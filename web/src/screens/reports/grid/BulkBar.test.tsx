import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BulkBar } from "./BulkBar";

afterEach(cleanup);

describe("BulkBar", () => {
  it("shows the message and its buttons, and the first button takes the focus", () => {
    const save = vi.fn();
    const discard = vi.fn();
    const { getByText, getByRole } = render(
      <BulkBar
        message="2 нүд өөрчлөгдөнө · 0 алдаатай · 1 засах боломжгүй"
        actions={[
          { label: "Хадгалах", main: true, run: save },
          { label: "Болих", run: discard },
        ]}
        onEscape={vi.fn()}
      />,
    );

    expect(getByText("2 нүд өөрчлөгдөнө · 0 алдаатай · 1 засах боломжгүй")).toBeTruthy();
    expect(getByRole("status").getAttribute("data-bulk-bar")).not.toBeNull();
    expect(document.activeElement).toBe(getByText("Хадгалах"));
    fireEvent.click(getByText("Хадгалах"));
    expect(save).toHaveBeenCalledTimes(1);
    fireEvent.click(getByText("Болих"));
    expect(discard).toHaveBeenCalledTimes(1);
  });

  it("Escape calls onEscape", () => {
    const onEscape = vi.fn();
    const { getByRole } = render(
      <BulkBar message="Шалгаж байна…" actions={[]} onEscape={onEscape} />,
    );
    fireEvent.keyDown(getByRole("status"), { key: "Escape" });
    expect(onEscape).toHaveBeenCalledTimes(1);
  });

  it("other keys do not close it", () => {
    const onEscape = vi.fn();
    const { getByRole } = render(
      <BulkBar message="Шалгаж байна…" actions={[]} onEscape={onEscape} />,
    );
    fireEvent.keyDown(getByRole("status"), { key: "a" });
    expect(onEscape).not.toHaveBeenCalled();
  });

  it("session-lost text is shown as given", () => {
    const { getByText } = render(
      <BulkBar
        message="Нэвтрэх хугацаа дууссан. Хуудсаа шинэчилж дахин нэвтэрнэ үү."
        actions={[{ label: "Хаах", main: true, run: vi.fn() }]}
        onEscape={vi.fn()}
      />,
    );
    expect(getByText("Нэвтрэх хугацаа дууссан. Хуудсаа шинэчилж дахин нэвтэрнэ үү.")).toBeTruthy();
  });
});
