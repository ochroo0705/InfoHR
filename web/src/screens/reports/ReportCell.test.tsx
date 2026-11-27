import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router";
import type { ReportCellOut } from "../../api/reports";
import { ReportCell, inlineStyle, moneyText } from "./ReportCell";

const TEXT: ReportCellOut = { value: "Бат", text: "Бат", money: false, href: "", css: "", style: "", person: 0, edit: null };

function renderCell(cell: Partial<ReportCellOut>) {
  return render(
    <MemoryRouter>
      <table>
        <tbody>
          <tr>
            <ReportCell cell={{ ...TEXT, ...cell }} />
          </tr>
        </tbody>
      </table>
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllEnvs();
});

describe("ReportCell", () => {
  it("cell_html_is_drawn_as_text", () => {
    const { container } = renderCell({
      value: "<b>Бат</b>",
      text: '<b>Бат</b> <img src="x" onerror="alert(1)">',
    });

    const td = container.querySelector("td")!;
    expect(td.textContent).toBe('<b>Бат</b> <img src="x" onerror="alert(1)">');
    expect(container.querySelector("b")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("pinned_cell_keeps_mark_background", () => {
    const css = "sticky z-10 bg-red-50 text-red-700 w-[12rem] min-w-[12rem] max-w-[12rem] truncate";
    const { container } = renderCell({ text: "Бат", css, style: "left: 12rem" });

    const td = container.querySelector("td")!;
    expect(td.className).toBe(css);
    expect(td.style.left).toBe("12rem");
  });

  it("money_cell_has_no_dot_zero_zero", () => {
    const first = renderCell({ text: "2500000.00", value: "2500000.00", money: true });
    expect(first.container.querySelector("td")!.textContent).toBe("2,500,000₮");
    first.unmount();

    const second = renderCell({ text: "800000", value: "800000", money: true });
    expect(second.container.querySelector("td")!.textContent).toBe("800,000₮");
    second.unmount();

    const third = renderCell({ text: "1234.5", value: "1234.5", money: true });
    expect(third.container.querySelector("td")!.textContent).toBe("1,234.50₮");
  });

  it("a blank value prints nothing, and a blank money value is a dash as mnt gives", () => {
    const blank = renderCell({ text: "", value: null, money: false });
    expect(blank.container.querySelector("td")!.textContent).toBe("");
    blank.unmount();

    const emptyMoney = renderCell({ text: "", value: null, money: true });
    expect(emptyMoney.container.querySelector("td")!.textContent).toBe("");
    emptyMoney.unmount();

    expect(moneyText("")).toBe("—");
  });

  it("cell_href_unported_goes_to_legacy_origin", () => {
    vi.stubEnv("VITE_LEGACY_ORIGIN", "https://legacy.test");

    const unported = renderCell({ text: "Бат", href: "/hire/5/" });
    const link = unported.container.querySelector("a")!;
    expect(link.getAttribute("href")).toBe("https://legacy.test/hire/5/");
    expect(link.className).toBe("text-violet-700 hover:underline");
    expect(link.textContent).toBe("Бат");
    unported.unmount();

    const ported = renderCell({ text: "Бат", href: "/employees/7/" });
    expect(ported.container.querySelector("a")!.getAttribute("href")).toBe("/employees/7/");
  });

  it("inline style accepts only a pinned left offset in rem", () => {
    expect(inlineStyle("left: 12rem")).toEqual({ left: "12rem" });
    expect(inlineStyle("left: 2.5rem")).toEqual({ left: "2.5rem" });
    expect(inlineStyle("left: 0.0rem")).toEqual({ left: "0.0rem" });
    expect(inlineStyle("")).toBeUndefined();
    expect(inlineStyle("nonsense")).toBeUndefined();
  });

  it("a second declaration or another property yields no style", () => {
    expect(inlineStyle("left: 1rem; position:fixed")).toBeUndefined();
    expect(inlineStyle("background-color: red; left: 1rem")).toBeUndefined();
    expect(inlineStyle("left: 1px")).toBeUndefined();
  });
});

describe("ReportCell editor", () => {
  it("panel_editor_keeps_the_old_text_faded_under_it", () => {
    const { container } = render(
      <table>
        <tbody>
          <tr>
            <ReportCell cell={{ ...TEXT, text: "Бат", css: "w-[9rem]" }} editor={<form data-cell-form>x</form>} panel />
          </tr>
        </tbody>
      </table>,
    );
    const td = container.querySelector("td")!;
    expect(td.classList.contains("is-popped")).toBe(true);
    expect(td.classList.contains("w-[9rem]")).toBe(true);
    expect(td.querySelector("[data-cell-ghost]")?.textContent).toBe("Бат");
    expect(td.querySelector("form[data-cell-form]")).not.toBeNull();
  });

  it("plain_editor_replaces_the_text", () => {
    const { container } = render(
      <table>
        <tbody>
          <tr>
            <ReportCell cell={{ ...TEXT, text: "Бат" }} editor={<input aria-label="x" />} />
          </tr>
        </tbody>
      </table>,
    );
    const td = container.querySelector("td")!;
    expect(td.textContent).toBe("");
    expect(td.querySelector("[data-cell-ghost]")).toBeNull();
    expect(td.querySelector("input")).not.toBeNull();
  });
});
