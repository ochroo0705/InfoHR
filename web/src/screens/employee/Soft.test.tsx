import { useState } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Soft, SOFT } from "./Soft";

afterEach(() => {
  cleanup();
});

const CHOICES = [
  { value: "5", label: "Санхүү" },
  { value: "7", label: "Худалдаа" },
  { value: "9", label: "Маркетинг" },
];

// A select and a date with their own state, as a form holds them: each change updates the box and is also recorded.
function ComboHost({ onValue, search = true }: { onValue: (name: string, v: string) => void; search?: boolean }) {
  const [value, setValue] = useState("");
  return (
    <Soft
      label="Хэлтэс"
      kind="select"
      value={value}
      combo={search}
      choices={CHOICES}
      name="dept"
      onChange={(n, v) => {
        setValue(v);
        onValue(n, v);
      }}
    />
  );
}

function DateHost({ onValue }: { onValue: (name: string, v: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <Soft
      label="Анх ажилд орсон огноо"
      kind="date"
      value={value}
      name="joined"
      onChange={(n, v) => {
        setValue(v);
        onValue(n, v);
      }}
    />
  );
}

describe("Soft", () => {
  it("a select draws its one current option, keeps the soft look, and does not open on mousedown or keydown", () => {
    render(<Soft label="Алба" kind="select" value="4" choice="Удирдлагын алба" />);
    const select = screen.getByLabelText("Алба") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    expect(select.options).toHaveLength(1);
    expect(select.options[0].textContent).toBe("Удирдлагын алба");
    expect(select.value).toBe("4");
    expect(select.className).toBe(`w-full ${SOFT}`);
    expect(select.disabled).toBe(false);
    expect(fireEvent.mouseDown(select)).toBe(false);
    expect(fireEvent.keyDown(select, { key: "ArrowDown" })).toBe(false);
  });

  it("a combo select is a read-only combo text box showing its current text, with the select's classes and sel-combo", () => {
    render(<Soft label="Салбар" kind="select" value="78" choice="Төв салбар" combo />);
    const box = screen.getByLabelText("Салбар") as HTMLInputElement;
    expect(box.tagName).toBe("INPUT");
    expect(box.type).toBe("text");
    expect(box.value).toBe("Төв салбар");
    expect(box.readOnly).toBe(true);
    expect(box.getAttribute("role")).toBe("combobox");
    expect(box.getAttribute("aria-autocomplete")).toBe("list");
    expect(box.className).toBe(`w-full ${SOFT} sel-combo`);
  });

  it("an empty combo select shows an empty text box", () => {
    render(<Soft label="Алба" kind="select" value="" choice="" combo />);
    expect((screen.getByLabelText("Алба") as HTMLInputElement).value).toBe("");
  });

  it("an empty select keeps Django's empty option", () => {
    render(<Soft label="Ажлын төрөл" kind="select" value="" choice="" />);
    const select = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(select.options[0].textContent).toBe("");
  });

  it("a text, date or number box is a read-only input of its type with the placeholder", () => {
    render(<Soft label="НДД-ийн дугаар" kind="text" value="" />);
    const input = screen.getByLabelText("НДД-ийн дугаар") as HTMLInputElement;
    expect(input.type).toBe("text");
    expect(input.readOnly).toBe(true);
    expect(input.placeholder).toBe("—");
    expect(input.autocomplete).toBe("off");
    expect(input.className).toBe(`w-full ${SOFT}`);
  });

  it("a textarea is a read-only one-line box that grows with its text, with the placeholder", () => {
    render(<Soft label="Дүгнэлт" kind="textarea" value="Сайн" placeholder="Тодруулга" />);
    const box = screen.getByLabelText("Дүгнэлт") as HTMLTextAreaElement;
    expect(box.tagName).toBe("TEXTAREA");
    expect(box.readOnly).toBe(true);
    expect(box.rows).toBe(1);
    expect(box.value).toBe("Сайн");
    expect(box.placeholder).toBe("Тодруулга");
    expect(box.className).toBe(`w-full ${SOFT} resize-none [field-sizing:content]`);
  });

  it("date and number boxes take their type and the width given", () => {
    render(<Soft label="Салбарт ажилласан жил" kind="number" value="3" width="w-20" />);
    const years = screen.getByLabelText("Салбарт ажилласан жил") as HTMLInputElement;
    expect(years.type).toBe("number");
    expect(years.value).toBe("3");
    expect(years.className).toBe(`w-20 ${SOFT}`);
    cleanup();
    cleanup();
    render(<Soft label="Анх ажилд орсон огноо" kind="date" value="2026-01-05" />);
    const date = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    expect(date.type).toBe("text");
    expect(date.getAttribute("data-dp")).toBe("1");
    expect(date.maxLength).toBe(10);
    expect(date.parentElement?.className).toBe("dp-wrap");
    expect(date.parentElement?.querySelector("button.dp-icon")?.getAttribute("aria-label")).toBe("Хуанли нээх");
  });

  it("a checkbox is a read-only checkbox with the flag's class and no width", () => {
    render(<Soft label="Хөгжлийн бэрхшээлтэй" kind="checkbox" value="" checked />);
    const box = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    expect(box.type).toBe("checkbox");
    expect(box.checked).toBe(true);
    expect(box.readOnly).toBe(true);
    expect(box.className).toBe("h-4 w-4 accent-violet-600");
  });

  it("with onChange a text box is controlled by its value and reports each typed value with its name", () => {
    const onChange = vi.fn();
    render(<Soft label="Ажлын утас" kind="text" value="12" name="work_phone" onChange={onChange} />);
    const input = screen.getByLabelText("Ажлын утас") as HTMLInputElement;
    expect(input.readOnly).toBe(false);
    expect(input.name).toBe("work_phone");
    fireEvent.change(input, { target: { value: "99" } });
    expect(onChange).toHaveBeenCalledWith("work_phone", "99");
  });

  it("with onChange a number box reports its typed value", () => {
    const onChange = vi.fn();
    render(<Soft label="Жил" kind="number" value="3" name="years" onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("Жил"), { target: { value: "7" } });
    expect(onChange).toHaveBeenCalledWith("years", "7");
  });

  it("with onChange a textarea reports its typed value and keeps its classes", () => {
    const onChange = vi.fn();
    render(<Soft label="Дүгнэлт" kind="textarea" value="Сайн" name="note" onChange={onChange} />);
    const box = screen.getByLabelText("Дүгнэлт") as HTMLTextAreaElement;
    expect(box.readOnly).toBe(false);
    expect(box.rows).toBe(1);
    expect(box.className).toBe(`w-full ${SOFT} resize-none [field-sizing:content]`);
    fireEvent.change(box, { target: { value: "Маш сайн" } });
    expect(onChange).toHaveBeenCalledWith("note", "Маш сайн");
  });

  it("with onChange a checkbox reports on when checked and empty when unchecked, as the browser posts it", () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <Soft label="Хөгжлийн бэрхшээлтэй" kind="checkbox" value="" checked={false} name="disabled" onChange={onChange} />,
    );
    const box = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    expect(box.name).toBe("disabled");
    fireEvent.click(box);
    expect(onChange).toHaveBeenLastCalledWith("disabled", "on");
    rerender(
      <Soft label="Хөгжлийн бэрхшээлтэй" kind="checkbox" value="" checked name="disabled" onChange={onChange} />,
    );
    expect(box.checked).toBe(true);
    fireEvent.click(box);
    expect(onChange).toHaveBeenLastCalledWith("disabled", "");
  });

  it("without onChange typing changes nothing", () => {
    render(<Soft label="Ажлын утас" kind="text" value="12" />);
    const input = screen.getByLabelText("Ажлын утас") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "99" } });
    expect(input.value).toBe("12");
  });

  it("without onChange a checkbox click leaves it unchecked", () => {
    render(<Soft label="Хөгжлийн бэрхшээлтэй" kind="checkbox" value="" checked={false} />);
    const box = screen.getByLabelText("Хөгжлийн бэрхшээлтэй") as HTMLInputElement;
    fireEvent.click(box);
    expect(box.checked).toBe(false);
  });

  it("error draws each message in Django's error classes after the box and sets aria-invalid", () => {
    render(<Soft label="НДД-ийн дугаар" kind="text" value="" onChange={() => {}} error={["Заавал бөглөнө"]} />);
    const input = screen.getByLabelText("НДД-ийн дугаар") as HTMLInputElement;
    expect(input.getAttribute("aria-invalid")).toBe("true");
    const message = screen.getByText("Заавал бөглөнө");
    expect(message.tagName).toBe("P");
    expect(message.className).toBe("mt-1 text-xs text-red-600");
    expect(input.compareDocumentPosition(message) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("no error means no aria-invalid and no message", () => {
    const { container } = render(<Soft label="НДД-ийн дугаар" kind="text" value="" onChange={() => {}} />);
    expect(screen.getByLabelText("НДД-ийн дугаар").getAttribute("aria-invalid")).toBeNull();
    expect(container.querySelector("p")).toBeNull();
  });

  it("changed wraps the box in an f-changed span so the violet edge shows, and no wrapper otherwise", () => {
    const { container, rerender } = render(<Soft label="Ажлын утас" kind="text" value="1" onChange={() => {}} changed />);
    const wrap = container.querySelector("span.f-changed");
    expect(wrap?.className).toBe("f-changed contents");
    expect(wrap?.querySelector("input")).not.toBeNull();
    rerender(<Soft label="Ажлын утас" kind="text" value="1" onChange={() => {}} />);
    expect(container.querySelector(".f-changed")).toBeNull();
  });
});

describe("Soft: an editable select and date (with onChange)", () => {
  it("a combo select shows the chosen option's text after a pick and reports the value with its name", () => {
    const onValue = vi.fn();
    render(<ComboHost onValue={onValue} />);
    const box = screen.getByLabelText("Хэлтэс") as HTMLInputElement;
    expect(box.readOnly).toBe(false);
    expect(box.getAttribute("role")).toBe("combobox");
    expect(box.className).toContain("sel-combo");
    fireEvent.click(box);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Худалдаа" }));
    expect(onValue).toHaveBeenCalledWith("dept", "7");
    expect(box.value).toBe("Худалдаа");
  });

  it("a combo select posts its value in a hidden field named as the form field", () => {
    const { container } = render(<ComboHost onValue={() => {}} />);
    fireEvent.click(screen.getByLabelText("Хэлтэс"));
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Санхүү" }));
    expect((container.querySelector('input[type="hidden"][name="dept"]') as HTMLInputElement).value).toBe("5");
  });

  it("a click-list select (no combo) reports a pick with its name and shows the chosen option", () => {
    const onChange = vi.fn();
    render(
      <Soft label="Ажлын төрөл" kind="select" value="5" name="work_type" choices={CHOICES} combo={false} onChange={onChange} />,
    );
    const select = screen.getByLabelText("Ажлын төрөл") as HTMLSelectElement;
    expect(select.tagName).toBe("SELECT");
    fireEvent.mouseDown(select);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Маркетинг" }));
    expect(onChange).toHaveBeenCalledWith("work_type", "9");
  });

  it("a date typed as 2024-01-05 reports it, and the box shows it", () => {
    const onValue = vi.fn();
    render(<DateHost onValue={onValue} />);
    const box = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    expect(box.readOnly).toBe(false);
    fireEvent.change(box, { target: { value: "2024-01-05" } });
    expect(onValue).toHaveBeenCalledWith("joined", "2024-01-05");
    expect(box.value).toBe("2024-01-05");
  });

  it("clearing a date reports an empty string", () => {
    const onValue = vi.fn();
    render(<DateHost onValue={onValue} />);
    const box = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "2024-01-05" } });
    fireEvent.change(box, { target: { value: "" } });
    expect(onValue).toHaveBeenLastCalledWith("joined", "");
    expect(box.value).toBe("");
  });

  it("a date box keeps the calendar button of the date widget", () => {
    render(<DateHost onValue={() => {}} />);
    const box = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    expect(box.parentElement?.className).toBe("dp-wrap");
    expect(box.parentElement?.querySelector("button.dp-icon")?.getAttribute("aria-label")).toBe("Хуанли нээх");
  });

  it("a select with an error shows its messages after the box and sets aria-invalid on the box", () => {
    render(
      <Soft
        label="Хэлтэс"
        kind="select"
        value=""
        combo
        choices={CHOICES}
        name="dept"
        onChange={() => {}}
        error={["Заавал сонгоно"]}
      />,
    );
    const box = screen.getByLabelText("Хэлтэс") as HTMLInputElement;
    expect(box.getAttribute("aria-invalid")).toBe("true");
    const message = screen.getByText("Заавал сонгоно");
    expect(message.className).toBe("mt-1 text-xs text-red-600");
    expect(box.compareDocumentPosition(message) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("a date with an error shows its messages and sets aria-invalid on the box", () => {
    render(
      <Soft
        label="Анх ажилд орсон огноо"
        kind="date"
        value=""
        name="joined"
        onChange={() => {}}
        error={["Буруу огноо"]}
      />,
    );
    expect(screen.getByLabelText("Анх ажилд орсон огноо").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Буруу огноо").tagName).toBe("P");
  });

  it("no error means no aria-invalid on a select or date", () => {
    const { container } = render(
      <>
        <Soft label="Хэлтэс" kind="select" value="" combo choices={CHOICES} name="dept" onChange={() => {}} />
        <Soft label="Анх ажилд орсон огноо" kind="date" value="" name="joined" onChange={() => {}} />
      </>,
    );
    expect(screen.getByLabelText("Хэлтэс").getAttribute("aria-invalid")).toBeNull();
    expect(screen.getByLabelText("Анх ажилд орсон огноо").getAttribute("aria-invalid")).toBeNull();
    expect(container.querySelector("p")).toBeNull();
  });

  it("changed wraps a select and a date in an f-changed span, and no wrapper otherwise", () => {
    const { container, rerender } = render(
      <Soft label="Хэлтэс" kind="select" value="5" combo choices={CHOICES} name="dept" onChange={() => {}} changed />,
    );
    expect(container.querySelector("span.f-changed")?.querySelector("input")).not.toBeNull();
    rerender(
      <Soft label="Анх ажилд орсон огноо" kind="date" value="2024-01-05" name="joined" onChange={() => {}} changed />,
    );
    expect(container.querySelector("span.f-changed")?.querySelector("input")).not.toBeNull();
    rerender(<Soft label="Анх ажилд орсон огноо" kind="date" value="2024-01-05" name="joined" onChange={() => {}} />);
    expect(container.querySelector(".f-changed")).toBeNull();
  });

  it("the editable combo, click-list and date boxes carry the soft box classes of the read-only ones", () => {
    const { rerender } = render(<ComboHost onValue={() => {}} />);
    expect(screen.getByLabelText("Хэлтэс").className).toBe(`w-full ${SOFT} sel-combo`);
    rerender(
      <Soft label="Ажлын төрөл" kind="select" value="5" name="work_type" choices={CHOICES} combo={false} onChange={() => {}} />,
    );
    expect(screen.getByLabelText("Ажлын төрөл").className).toBe(`w-full ${SOFT}`);
    rerender(<DateHost onValue={() => {}} />);
    expect(screen.getByLabelText("Анх ажилд орсон огноо").className).toBe(`w-full ${SOFT}`);
  });

  it("an editable click-list select with an error is aria-invalid and shows the message", () => {
    render(
      <Soft
        label="Ажлын төрөл"
        kind="select"
        value="5"
        choices={CHOICES}
        combo={false}
        name="work_type"
        onChange={() => {}}
        error={["Заавал сонгоно"]}
      />,
    );
    expect(screen.getByLabelText("Ажлын төрөл").getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText("Заавал сонгоно").tagName).toBe("P");
  });

  it("an editable date box with an error carries the soft classes and aria-invalid", () => {
    render(
      <Soft
        label="Анх ажилд орсон огноо"
        kind="date"
        value=""
        name="joined"
        onChange={() => {}}
        error={["Буруу огноо"]}
      />,
    );
    const box = screen.getByLabelText("Анх ажилд орсон огноо");
    expect(box.className).toContain("f-soft");
    expect(box.getAttribute("aria-invalid")).toBe("true");
  });

  it("an editable date shows the placeholder passed to it", () => {
    render(
      <Soft
        label="Анх ажилд орсон огноо"
        kind="date"
        value=""
        name="joined"
        placeholder="Огноо оруулна уу"
        onChange={() => {}}
      />,
    );
    expect((screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement).placeholder).toBe("Огноо оруулна уу");
  });

  it("an editable date keeps the default placeholder \"—\" when none is passed", () => {
    render(<Soft label="Анх ажилд орсон огноо" kind="date" value="" name="joined" onChange={() => {}} />);
    expect((screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement).placeholder).toBe("—");
  });

  it("a partial date typed reports the raw text, and the full date reports YYYY-MM-DD", () => {
    const onValue = vi.fn();
    render(<DateHost onValue={onValue} />);
    const box = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "2024-01" } });
    fireEvent.change(box, { target: { value: "2024-01-05" } });
    expect(onValue.mock.calls).toEqual([
      ["joined", "2024-01"],
      ["joined", "2024-01-05"],
    ]);
    expect(box.value).toBe("2024-01-05");
  });

  it("a select whose choices include the blank entry clears to \"\" when the blank is picked", () => {
    const onValue = vi.fn();
    function ClearHost() {
      const [value, setValue] = useState("7");
      return (
        <Soft
          label="Хэлтэс"
          kind="select"
          value={value}
          combo
          choices={[{ value: "", label: "" }, ...CHOICES]}
          name="dept"
          onChange={(n, v) => {
            setValue(v);
            onValue(n, v);
          }}
        />
      );
    }
    render(<ClearHost />);
    const box = screen.getByLabelText("Хэлтэс") as HTMLInputElement;
    expect(box.value).toBe("Худалдаа");
    fireEvent.click(box);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "—" }));
    expect(onValue).toHaveBeenLastCalledWith("dept", "");
    expect(box.value).toBe("");
  });

  it("a select whose choices include the blank entry clears to \"\" when its text is emptied and left", () => {
    const onValue = vi.fn();
    function ClearHost() {
      const [value, setValue] = useState("7");
      return (
        <Soft
          label="Хэлтэс"
          kind="select"
          value={value}
          combo
          choices={[{ value: "", label: "" }, ...CHOICES]}
          name="dept"
          onChange={(n, v) => {
            setValue(v);
            onValue(n, v);
          }}
        />
      );
    }
    render(<ClearHost />);
    const box = screen.getByLabelText("Хэлтэс") as HTMLInputElement;
    fireEvent.change(box, { target: { value: "" } });
    fireEvent.blur(box);
    expect(onValue).toHaveBeenLastCalledWith("dept", "");
    expect(box.value).toBe("");
  });
});

describe("Soft: an editable box keeps its node and focus when changed toggles", () => {
  // The parent holds the value and marks the box changed once it differs from the saved one, as the tabs do.
  function TextHost() {
    const [value, setValue] = useState("12");
    return (
      <Soft
        label="Ажлын утас"
        kind="text"
        value={value}
        name="work_phone"
        changed={value !== "12"}
        onChange={(_, v) => setValue(v)}
      />
    );
  }

  function ComboChanged() {
    const [value, setValue] = useState("");
    return (
      <Soft
        label="Хэлтэс"
        kind="select"
        value={value}
        combo
        choices={CHOICES}
        name="dept"
        changed={value !== ""}
        onChange={(_, v) => setValue(v)}
      />
    );
  }

  function DateChanged() {
    const [value, setValue] = useState("");
    return (
      <Soft
        label="Анх ажилд орсон огноо"
        kind="date"
        value={value}
        name="joined"
        changed={value !== ""}
        onChange={(_, v) => setValue(v)}
      />
    );
  }

  it("a text box keeps its node and focus after the first keystroke, and its wrapper gets f-changed", () => {
    const { container } = render(<TextHost />);
    const input = screen.getByLabelText("Ажлын утас") as HTMLInputElement;
    expect(input.parentElement?.className).toBe("contents");
    input.focus();
    fireEvent.change(input, { target: { value: "129" } });
    expect(screen.getByLabelText("Ажлын утас")).toBe(input);
    expect(document.activeElement).toBe(input);
    expect(input.parentElement?.className).toBe("f-changed contents");
    expect(container.querySelectorAll("span.f-changed")).toHaveLength(1);
  });

  it("a combo select keeps its node and focus after a pick, and its wrapper gets f-changed", () => {
    render(<ComboChanged />);
    const box = screen.getByLabelText("Хэлтэс") as HTMLInputElement;
    box.focus();
    fireEvent.click(box);
    fireEvent.click(within(screen.getByRole("listbox")).getByRole("option", { name: "Худалдаа" }));
    expect(screen.getByLabelText("Хэлтэс")).toBe(box);
    expect(document.activeElement).toBe(box);
    expect(box.value).toBe("Худалдаа");
    expect(box.parentElement?.className).toBe("f-changed contents");
  });

  it("a date box keeps its node and focus after the first typed character, and its wrapper gets f-changed", () => {
    render(<DateChanged />);
    const box = screen.getByLabelText("Анх ажилд орсон огноо") as HTMLInputElement;
    box.focus();
    fireEvent.change(box, { target: { value: "2" } });
    expect(screen.getByLabelText("Анх ажилд орсон огноо")).toBe(box);
    expect(document.activeElement).toBe(box);
    expect(box.parentElement?.parentElement?.className).toBe("f-changed contents");
  });

  it("the wrapper's class follows changed without replacing the box", () => {
    const { rerender } = render(<Soft label="Ажлын утас" kind="text" value="1" name="work_phone" onChange={() => {}} />);
    const input = screen.getByLabelText("Ажлын утас");
    expect(input.parentElement?.className).toBe("contents");
    rerender(<Soft label="Ажлын утас" kind="text" value="1" name="work_phone" onChange={() => {}} changed />);
    expect(screen.getByLabelText("Ажлын утас")).toBe(input);
    expect(input.parentElement?.className).toBe("f-changed contents");
    rerender(<Soft label="Ажлын утас" kind="text" value="1" name="work_phone" onChange={() => {}} />);
    expect(screen.getByLabelText("Ажлын утас")).toBe(input);
    expect(input.parentElement?.className).toBe("contents");
  });

  it("a read-only box has no wrapper unless changed, as before", () => {
    const { rerender } = render(<Soft label="Ажлын утас" kind="text" value="1" />);
    expect(screen.getByLabelText("Ажлын утас").parentElement?.tagName).not.toBe("SPAN");
    rerender(<Soft label="Ажлын утас" kind="text" value="1" changed />);
    expect(screen.getByLabelText("Ажлын утас").parentElement?.className).toBe("f-changed contents");
  });
});

describe("Soft: the form attribute of an editable box", () => {
  it("an editable text box, a number and a checkbox carry the given form id, and a box without one has none", () => {
    const { container } = render(
      <>
        <Soft label="Утас" kind="text" value="1" name="phone" form="emp-form" onChange={() => {}} />
        <Soft label="Цалин" kind="number" value="2" name="salary" form="emp-form" onChange={() => {}} />
        <Soft label="Идэвхтэй" kind="checkbox" value="" checked={false} name="active" form="emp-form" onChange={() => {}} />
        <Soft label="Тэмдэглэл" kind="textarea" value="" name="note" onChange={() => {}} />
      </>,
    );
    expect(screen.getByLabelText("Утас").getAttribute("form")).toBe("emp-form");
    expect(screen.getByLabelText("Цалин").getAttribute("form")).toBe("emp-form");
    expect(screen.getByLabelText("Идэвхтэй").getAttribute("form")).toBe("emp-form");
    expect(screen.getByLabelText("Тэмдэглэл").getAttribute("form")).toBeNull();
    expect(container.querySelectorAll("[form]")).toHaveLength(3);
  });
});
