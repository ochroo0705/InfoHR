import { useRef } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { messageFor, useMnValidation } from "./validationMn";

afterEach(cleanup);

type Flag =
  | "valueMissing"
  | "badInput"
  | "typeMismatch"
  | "stepMismatch"
  | "tooLong"
  | "tooShort"
  | "rangeUnderflow"
  | "rangeOverflow"
  | "patternMismatch"
  | "customError";

// Stubs the ValidityState of an element: only the listed flags are true.
function withFlags<T extends HTMLElement>(el: T, flags: Flag[]): T {
  const state: Record<Flag | "patternMismatch" | "valid", boolean> = {
    valueMissing: false,
    badInput: false,
    typeMismatch: false,
    stepMismatch: false,
    tooLong: false,
    tooShort: false,
    rangeUnderflow: false,
    rangeOverflow: false,
    customError: false,
    patternMismatch: false,
    valid: false,
  };
  for (const f of flags) state[f] = true;
  Object.defineProperty(el, "validity", { value: state, configurable: true });
  return el;
}

function makeInput(type = "text"): HTMLInputElement {
  const el = document.createElement("input");
  el.type = type;
  return el;
}

type Field = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
type Case = [label: string, make: () => Field, flags: Flag[], expected: string];

describe("messageFor (port of validation_mn.js message)", () => {
  // One row per message, in the order of validation_mn.js.
  const cases: Case[] = [
    [
      "empty select (valueMissing)",
      () => document.createElement("select"),
      ["valueMissing"],
      "Жагсаалтаас сонгоно уу.",
    ],
    [
      "empty role=combobox box (valueMissing)",
      () => {
        const el = makeInput();
        el.setAttribute("role", "combobox");
        return el;
      },
      ["valueMissing"],
      "Жагсаалтаас сонгоно уу.",
    ],
    ["empty file box (valueMissing)", () => makeInput("file"), ["valueMissing"], "Файл сонгоно уу."],
    ["empty text box (valueMissing)", () => makeInput("text"), ["valueMissing"], "Энэ талбарыг бөглөнө үү."],
    [
      "empty textarea (valueMissing)",
      () => document.createElement("textarea"),
      ["valueMissing"],
      "Энэ талбарыг бөглөнө үү.",
    ],
    ["number box, bad input", () => makeInput("number"), ["badInput"], "Тоо оруулна уу."],
    ["number box, type mismatch", () => makeInput("number"), ["typeMismatch"], "Тоо оруулна уу."],
    ["date box, bad input", () => makeInput("date"), ["badInput"], "Огноог зөв оруулна уу."],
    ["datetime-local box, bad input", () => makeInput("datetime-local"), ["badInput"], "Огноог зөв оруулна уу."],
    ["month box, bad input", () => makeInput("month"), ["badInput"], "Огноог зөв оруулна уу."],
    ["time box, bad input", () => makeInput("time"), ["badInput"], "Огноог зөв оруулна уу."],
    ["week box, bad input", () => makeInput("week"), ["badInput"], "Огноог зөв оруулна уу."],
    ["text box, bad input", () => makeInput("text"), ["badInput"], "Утгыг зөв оруулна уу."],
    ["step mismatch", () => makeInput("number"), ["stepMismatch"], "Утгыг зөв оруулна уу."],
    ["too long", () => makeInput("text"), ["tooLong"], "Хэт урт байна."],
    ["too short (minlength)", () => makeInput("text"), ["tooShort"], "Хэт богино байна."],
    ["range underflow", () => makeInput("number"), ["rangeUnderflow"], "Утга хязгаараас гадуур байна."],
    ["range overflow", () => makeInput("number"), ["rangeOverflow"], "Утга хязгаараас гадуур байна."],
    ["type mismatch (email)", () => makeInput("email"), ["typeMismatch"], "Буруу формат байна."],
    ["type mismatch (url)", () => makeInput("url"), ["typeMismatch"], "Буруу формат байна."],
    ["pattern mismatch (the JS has no pattern message)", () => makeInput("text"), ["patternMismatch"], ""],
  ];

  it.each(cases)("%s", (_label, make, flags, expected) => {
    expect(messageFor(withFlags(make(), flags))).toBe(expected);
  });

  it("returns an empty string when no flag fails", () => {
    expect(messageFor(withFlags(makeInput("text"), []))).toBe("");
  });

  it("gives the required message before the number message when a number box is also missing", () => {
    expect(messageFor(withFlags(makeInput("number"), ["valueMissing", "badInput"]))).toBe("Энэ талбарыг бөглөнө үү.");
  });
});

// A form with a required text box and a number box, so the hook can be checked end to end.
function Form() {
  const ref = useRef<HTMLFormElement>(null);
  useMnValidation(ref);
  return (
    <form ref={ref} data-testid="form">
      <label htmlFor="name">Нэр</label>
      <input id="name" name="name" required />
      <label htmlFor="age">Нас</label>
      <input id="age" name="age" type="number" />
      <button type="submit">Хадгалах</button>
    </form>
  );
}

describe("useMnValidation", () => {
  it("sets the Mongolian message on invalid and clears it on input", () => {
    render(<Form />);
    const name = screen.getByLabelText("Нэр") as HTMLInputElement;
    withFlags(name, ["valueMissing"]);
    fireEvent.invalid(name);
    expect(name.validationMessage).toBe("Энэ талбарыг бөглөнө үү.");
    fireEvent.input(name, { target: { value: "Бат" } });
    expect(name.validationMessage).toBe("");
  });

  it("sets the number message on a number box that is not a number", () => {
    render(<Form />);
    const age = screen.getByLabelText("Нас") as HTMLInputElement;
    withFlags(age, ["badInput"]);
    fireEvent.invalid(age);
    expect(age.validationMessage).toBe("Тоо оруулна уу.");
  });

  it("clears every message of the form on a new submit attempt", () => {
    render(<Form />);
    const name = screen.getByLabelText("Нэр") as HTMLInputElement;
    // Real jsdom state: the empty required box is valueMissing.
    fireEvent.invalid(name);
    expect(name.validationMessage).toBe("Энэ талбарыг бөглөнө үү.");
    expect(name.hasAttribute("data-mn-validity")).toBe(true);
    fireEvent.submit(screen.getByTestId("form"));
    // Our message and mark are gone (jsdom then reports its own native text, not the Mongolian one).
    expect(name.hasAttribute("data-mn-validity")).toBe(false);
    expect(name.validationMessage).not.toBe("Энэ талбарыг бөглөнө үү.");
  });

  it("clears a message on a control that belongs to the form through form=", () => {
    function WithOutside() {
      const ref = useRef<HTMLFormElement>(null);
      useMnValidation(ref);
      return (
        <>
          <form ref={ref} id="outer-form" data-testid="form">
            <button type="submit">Хадгалах</button>
          </form>
          <label htmlFor="outside">Гадна</label>
          <input id="outside" name="outside" form="outer-form" required />
        </>
      );
    }
    render(<WithOutside />);
    const outside = screen.getByLabelText("Гадна") as HTMLInputElement;
    fireEvent.invalid(outside);
    expect(outside.hasAttribute("data-mn-validity")).toBe(true);
    fireEvent.submit(screen.getByTestId("form"));
    expect(outside.hasAttribute("data-mn-validity")).toBe(false);
  });
});
