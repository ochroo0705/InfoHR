import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nav } from "../../api/client";
import type { EmployeeFormFieldOut } from "../../api/employeeWrites";
import {
  fetchDistricts,
  suggestOrderNumber,
  useHireForm,
  useHireSubmit,
  type HireChoiceOut,
  type HireFormOut,
  type HireResultOut,
} from "../../api/hire";
import { isUnsaved } from "../../lib/unsaved";
import { HirePage } from "./HirePage";

vi.mock("../../api/hire", () => ({
  useHireForm: vi.fn(),
  useHireSubmit: vi.fn(),
  suggestOrderNumber: vi.fn(),
  checkRegister: vi.fn(async () => null),
  fetchDistricts: vi.fn(async () => []),
  sendBack: vi.fn(),
  rejectSubmission: vi.fn(),
}));

// The review panel is replaced by a stub with one button that reports a finished send-back (its onDone with a redirect).
vi.mock("./ReviewPanel", async () => {
  const { createElement } = await vi.importActual<typeof import("react")>("react");
  return {
    ReviewPanel: ({ onDone }: { onDone: (redirect: string) => void }) =>
      createElement("button", { type: "button", onClick: () => onDone("/employees/self-forms/") }, "review-done"),
  };
});

const useFormMock = vi.mocked(useHireForm);
const useSubmitMock = vi.mocked(useHireSubmit);
const suggestMock = vi.mocked(suggestOrderNumber);
const districtsMock = vi.mocked(fetchDistricts);
const submitMock = vi.fn();
// The hint Django shows after a refused post that carried a photo (add.html).
const PHOTO_HINT = "Зургаа дахин сонгоно уу";

// The project has no jest-dom matchers, so text and classes are read from the DOM.
function field(over: Partial<EmployeeFormFieldOut> & Pick<EmployeeFormFieldOut, "name" | "label" | "kind">): EmployeeFormFieldOut {
  return {
    checked: false,
    choice: "",
    choices: [],
    combo: false,
    errors: [],
    help: "",
    max_length: null,
    placeholder: "",
    required: false,
    value: "",
    ...over,
  };
}

const FIELDS: EmployeeFormFieldOut[] = [
  field({ name: "family_name", label: "Овог", kind: "text", required: true }),
  field({ name: "register_no", label: "Регистрийн дугаар", kind: "text" }),
  field({ name: "photo", label: "Зураг", kind: "file" }),
  field({ name: "start", label: "Ажилд орсон огноо", kind: "text" }),
  field({ name: "order-number", label: "Тушаалын дугаар", kind: "text", required: true }),
  field({ name: "order-date", label: "Тушаалын огноо", kind: "date" }),
  field({ name: "order-summary", label: "Агуулга", kind: "text" }),
  field({ name: "email", label: "Имэйл", kind: "text" }),
  field({ name: "create_login", label: "Нэвтрэх эрх үүсгэх", kind: "checkbox" }),
  field({ name: "username", label: "Нэвтрэх нэр", kind: "text" }),
];

// The layout the server sends: three tabs (no salary tab), the order block in the basic tab.
const FORM: HireFormOut = {
  title: "Ажилтан нэмэх",
  candidate: null,
  submission: null,
  review: null,
  duplicate: null,
  fields: FIELDS,
  tabs: [
    {
      key: "basic",
      label: "Үндсэн",
      sections: [
        { heading: "Үндсэн мэдээлэл", kind: "fields", names: ["family_name", "register_no", "photo"], note: "" },
        { heading: "Ажил, гэрээ", kind: "fields", names: ["start"], note: "" },
        {
          heading: "Тушаал",
          kind: "order",
          names: ["order-number", "order-date", "order-summary"],
          note: "дугаар заавал",
        },
      ],
    },
    {
      key: "personal",
      label: "Хувийн",
      sections: [{ heading: "Хувийн мэдээлэл", kind: "fields", names: ["email"], note: "" }],
    },
    {
      key: "login",
      label: "Нэвтрэх эрх",
      sections: [{ heading: "Нэвтрэх эрх", kind: "fields", names: ["create_login", "username"], note: "" }],
    },
  ],
};

function result(over: Partial<HireResultOut> = {}): HireResultOut {
  return {
    ok: false,
    pk: null,
    redirect: "",
    candidate: null,
    submission: null,
    field_errors: {},
    form_errors: [],
    order_errors: [],
    ...over,
  };
}

function formWith(over: Partial<HireFormOut>) {
  useFormMock.mockReturnValue({ data: { ...FORM, ...over }, error: null } as unknown as ReturnType<typeof useHireForm>);
}

function inputOf(name: string) {
  return document.querySelector<HTMLInputElement>(`[name="${name}"]`) as HTMLInputElement;
}

function typeInto(name: string, value: string) {
  fireEvent.change(inputOf(name), { target: { value } });
}

// Submits the form element itself: a click on the button goes through the browser's own required-field check, which
// blocks the submit while a required box is empty (the test fills only some of them).
function clickSubmit() {
  fireEvent.submit(document.getElementById("add-form") as HTMLFormElement);
}

function badge(key: string): string {
  return document.querySelector(`[data-badge="${key}"]`)?.textContent ?? "";
}

function tab(label: RegExp) {
  return screen.getByRole("tab", { name: label });
}

let navSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  submitMock.mockReset();
  suggestMock.mockReset();
  useSubmitMock.mockReturnValue({ mutateAsync: submitMock } as unknown as ReturnType<typeof useHireSubmit>);
  formWith({});
  navSpy = vi.spyOn(nav, "assign").mockImplementation(() => undefined);
});

afterEach(() => {
  cleanup();
  navSpy.mockRestore();
});

function renderPage(path = "/employees/new/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/employees/new/" element={<HirePage />} />
          <Route path="/employees/:pk/" element={<p>employee page</p>} />
          <Route path="*" element={<p>other route</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("HirePage", () => {
  it("renders the tabs from the server and no salary tab when the server sends none", () => {
    renderPage();
    const labels = screen.getAllByRole("tab").map((t) => t.textContent?.trim());
    expect(labels).toEqual(["Үндсэн", "Хувийн", "Нэвтрэх эрх"]);
    expect(screen.queryByRole("tab", { name: /Цалин/ })).toBeNull();
  });

  it("renders sections in server order with the Django headings", () => {
    renderPage();
    const headings = Array.from(document.querySelectorAll('section[data-tab="basic"] h2'));
    expect(headings.map((h) => h.textContent)).toEqual(["Үндсэн мэдээлэл", "Ажил, гэрээ"]);
    expect(headings[0].classList.contains("mt-8")).toBe(false);
    expect(headings[1].classList.contains("mt-8")).toBe(true);
    expect(screen.getByRole("heading", { level: 3, name: /Тушаал/ })).toBeTruthy();
  });

  it("submit sends every value with its HTML name, the candidate and submission ids, and no photo when none chosen", async () => {
    formWith({ candidate: 5 });
    submitMock.mockResolvedValueOnce(result({ ok: true, pk: 7, redirect: "/employees/" }));
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    expect(submitMock).toHaveBeenCalledWith({
      values: {
        family_name: "Бат",
        register_no: "",
        start: "",
        "order-number": "",
        "order-date": "",
        "order-summary": "",
        email: "",
        username: "",
      },
      candidate: "5",
      submission: "",
      photo: null,
    });
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith("/employees/"));
  });

  it("a checkbox is sent as \"on\" only when checked", async () => {
    submitMock.mockResolvedValue(result());
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    expect(submitMock.mock.calls[0][0].values).not.toHaveProperty("create_login");
    // The refusal (result()) ends the request; the button is enabled again before the next click.
    await waitFor(() => expect((screen.getByRole("button", { name: "Ажилтан үүсгэх" }) as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(inputOf("create_login"));
    clickSubmit();
    expect(submitMock.mock.calls[1][0].values.create_login).toBe("on");
  });

  it("a refused result keeps the typed values, shows form_errors and order_errors, and keeps the returned submission id for the next submit", async () => {
    submitMock
      .mockResolvedValueOnce(result({ form_errors: ["Бүртгэл алдаатай"], order_errors: ["Тушаал алдаатай"], submission: 9 }))
      .mockResolvedValueOnce(result());
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    expect(await screen.findByText("Бүртгэл алдаатай")).toBeTruthy();
    expect(screen.getByText("Тушаал алдаатай")).toBeTruthy();
    expect(inputOf("family_name").value).toBe("Бат");
    expect(submitMock.mock.calls[0][0].submission).toBe("");
    clickSubmit();
    await waitFor(() => expect(submitMock).toHaveBeenCalledTimes(2));
    expect(submitMock.mock.calls[1][0].submission).toBe("9");
  });

  it("a field error opens its tab, focuses its box, and the tab badge shows the error count; order-field errors are not counted in the badge", async () => {
    submitMock
      .mockResolvedValueOnce(result({ field_errors: { email: ["Имэйл буруу", "Дахин оролдоно уу"] } }))
      .mockResolvedValueOnce(result({ field_errors: { "order-number": ["Дугаар давхцсан"] } }));
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    await waitFor(() => expect(tab(/Хувийн/).getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(document.activeElement).toBe(inputOf("email")));
    expect(badge("personal")).toBe("2");
    expect(screen.getByText("Имэйл буруу")).toBeTruthy();

    // An order-number error opens the basic tab and is not counted in its badge.
    clickSubmit();
    await waitFor(() => expect(tab(/Үндсэн/).getAttribute("aria-selected")).toBe("true"));
    await waitFor(() => expect(document.activeElement).toBe(inputOf("order-number")));
    expect(badge("basic")).toBe("");
    expect(screen.getByText("Дугаар давхцсан")).toBeTruthy();
  });

  it("the basic badge needs the order number filled", () => {
    renderPage();
    expect(badge("basic")).toBe("");
    typeInto("family_name", "Бат");
    expect(badge("basic")).toBe("");
    typeInto("order-number", "5");
    expect(badge("basic")).toBe("✓");
  });

  it("a second click while the request is pending sends one request", async () => {
    let release!: (value: HireResultOut) => void;
    submitMock.mockReturnValueOnce(new Promise<HireResultOut>((resolve) => (release = resolve)));
    renderPage();
    const form = document.getElementById("add-form") as HTMLFormElement;
    fireEvent.submit(form);
    fireEvent.submit(form);
    expect(submitMock).toHaveBeenCalledTimes(1);
    await act(async () => release(result()));
  });

  it("success navigates to a ported redirect in-app without a page load", async () => {
    submitMock.mockResolvedValueOnce(result({ ok: true, pk: 12, redirect: "/employees/12/" }));
    renderPage();
    clickSubmit();
    expect(await screen.findByText("employee page")).toBeTruthy();
    expect(navSpy).not.toHaveBeenCalled();
  });

  it("a legacy redirect after a hire goes through the full-page-load helper nav.assign", async () => {
    submitMock.mockResolvedValueOnce(result({ ok: true, pk: 8, redirect: "/employees/" }));
    renderPage();
    clickSubmit();
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith("/employees/"));
    expect(screen.queryByText("employee page")).toBeNull();
  });

  it("the submit button is type=submit and sits inside form#add-form, with no nested form", () => {
    renderPage();
    const button = screen.getByRole("button", { name: "Ажилтан үүсгэх" }) as HTMLButtonElement;
    expect(button.getAttribute("type")).toBe("submit");
    expect(button.closest("form")?.id).toBe("add-form");
    expect(document.querySelector('#add-form button[type="submit"]')).toBe(button);
    expect(document.querySelectorAll("form form").length).toBe(0);
  });

  it("a 403 form load renders the Forbidden screen", () => {
    useFormMock.mockReturnValue({
      data: undefined,
      error: Object.assign(new Error("forbidden"), { status: 403 }),
    } as unknown as ReturnType<typeof useHireForm>);
    renderPage();
    expect(screen.getByText("Хандах эрх байхгүй")).toBeTruthy();
  });

  it("editing a field clears its error", async () => {
    submitMock.mockResolvedValueOnce(result({ field_errors: { family_name: ["Овог заавал"] } }));
    renderPage();
    clickSubmit();
    expect(await screen.findByText("Овог заавал")).toBeTruthy();
    typeInto("family_name", "Бат");
    expect(screen.queryByText("Овог заавал")).toBeNull();
  });

  it("two onChange calls in a row (number then date) both land", async () => {
    suggestMock.mockResolvedValue({ number: "А-12", date: "2026-11-18" });
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "Санал болгох" }));
    await waitFor(() => expect(inputOf("order-number").value).toBe("А-12"));
    expect(inputOf("order-date").value).toBe("2026-11-18");
  });

  it("all tab panels stay mounted (a value typed in the basic tab survives switching tabs)", () => {
    renderPage();
    typeInto("family_name", "Бат");
    fireEvent.click(tab(/Хувийн/));
    expect(document.querySelector('[data-tab="personal"]')?.classList.contains("hidden")).toBe(false);
    expect(document.querySelector('[data-tab="basic"]')?.classList.contains("hidden")).toBe(true);
    fireEvent.click(tab(/Үндсэн/));
    expect(inputOf("family_name").value).toBe("Бат");
    expect(document.querySelectorAll('[role="tabpanel"]').length).toBe(3);
  });

  it("typing marks the page unsaved and a clean page is not unsaved", () => {
    renderPage();
    expect(isUnsaved("hire")).toBe(false);
    typeInto("family_name", "Бат");
    expect(isUnsaved("hire")).toBe(true);
  });

  it("a successful hire clears the unsaved mark before navigating", async () => {
    submitMock.mockResolvedValueOnce(result({ ok: true, pk: 8, redirect: "/employees/" }));
    let unsavedAtNav: boolean | null = null;
    navSpy.mockImplementation(() => {
      unsavedAtNav = isUnsaved("hire");
    });
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    await waitFor(() => expect(navSpy).toHaveBeenCalledWith("/employees/"));
    expect(unsavedAtNav).toBe(false);
  });

  it("beforeunload while the form is dirty is prevented", () => {
    renderPage();
    typeInto("family_name", "Бат");
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("beforeunload on a clean form is not prevented", () => {
    renderPage();
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });

  it("the review panel onDone clears the unsaved mark before the page load", () => {
    formWith({ review: { contact: [], education: [], family: [], has_photo: false, hr_note: "", submitted_at: "" }, submission: 3 });
    let unsavedAtLoad: boolean | null = null;
    navSpy.mockImplementation(() => {
      unsavedAtLoad = isUnsaved("hire");
    });
    renderPage();
    typeInto("family_name", "Бат");
    fireEvent.click(screen.getByRole("button", { name: "review-done" }));
    expect(navSpy).toHaveBeenCalledWith("/employees/self-forms/");
    expect(unsavedAtLoad).toBe(false);
  });

  it("a refused hire keeps the page unsaved", async () => {
    submitMock.mockResolvedValueOnce(result({ form_errors: ["Бүртгэл алдаатай"] }));
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    expect(await screen.findByText("Бүртгэл алдаатай")).toBeTruthy();
    expect(isUnsaved("hire")).toBe(true);
  });

  it("a refused post that carried a photo shows the choose-again hint and clears the photo; choosing a file hides it", async () => {
    const file = new File(["x"], "photo.jpg", { type: "image/jpeg" });
    const next = new File(["y"], "new.jpg", { type: "image/jpeg" });
    submitMock
      .mockResolvedValueOnce(result({ form_errors: ["Бүртгэл алдаатай"] }))
      .mockResolvedValueOnce(result({ form_errors: ["Бүртгэл алдаатай"] }))
      .mockResolvedValueOnce(result());
    renderPage();
    const boxBefore = inputOf("photo");
    fireEvent.change(boxBefore, { target: { files: [file] } });
    clickSubmit();
    expect(submitMock.mock.calls[0][0].photo).toBe(file);
    expect(await screen.findByText(PHOTO_HINT)).toBeTruthy();
    // The file box is remounted (a new element, key changed) and holds no file.
    expect(inputOf("photo")).not.toBe(boxBefore);
    expect(inputOf("photo").files?.length ?? 0).toBe(0);
    // The next post sends no photo, and that refusal has no photo, so the hint goes.
    clickSubmit();
    await waitFor(() => expect(submitMock).toHaveBeenCalledTimes(2));
    expect(submitMock.mock.calls[1][0].photo).toBeNull();
    expect(screen.queryByText(PHOTO_HINT)).toBeNull();
    // Choosing a file: no hint, and the next submit sends that file.
    fireEvent.change(inputOf("photo"), { target: { files: [next] } });
    expect(screen.queryByText(PHOTO_HINT)).toBeNull();
    clickSubmit();
    await waitFor(() => expect(submitMock).toHaveBeenCalledTimes(3));
    expect(submitMock.mock.calls[2][0].photo).toBe(next);
  });

  it("a failed districts request keeps the saved district and does not mark the page unsaved", async () => {
    districtsMock.mockReset();
    districtsMock.mockRejectedValue(new Error("down"));
    formWith({
      ...FORM,
      fields: [
        ...FIELDS,
        field({ name: "addr-city", label: "Хот", kind: "text", value: "11" }),
        field({
          name: "addr-district",
          label: "Сум, дүүрэг",
          kind: "select",
          value: "1",
          choices: [{ value: "1", label: "Баянзүрх" }],
        }),
      ],
      tabs: FORM.tabs.map((tab) =>
        tab.key === "personal"
          ? { ...tab, sections: [...tab.sections, { heading: "Хаяг", kind: "fields", names: ["addr-city", "addr-district"], note: "" }] }
          : tab,
      ),
    });
    renderPage();
    await act(async () => {});
    expect(inputOf("addr-district").value).toBe("1");
    expect(isUnsaved("hire")).toBe(false);
  });

  it("a file chosen while the request runs survives a refusal of the earlier post", async () => {
    const sent = new File(["x"], "old.jpg", { type: "image/jpeg" });
    const chosenLater = new File(["y"], "new.jpg", { type: "image/jpeg" });
    let release!: (value: HireResultOut) => void;
    submitMock
      .mockReturnValueOnce(new Promise<HireResultOut>((resolve) => (release = resolve)))
      .mockResolvedValueOnce(result());
    renderPage();
    fireEvent.change(inputOf("photo"), { target: { files: [sent] } });
    clickSubmit();
    // The user picks another file while the post is still pending.
    fireEvent.change(inputOf("photo"), { target: { files: [chosenLater] } });
    await act(async () => release(result({ form_errors: ["Бүртгэл алдаатай"] })));
    expect(await screen.findByText("Бүртгэл алдаатай")).toBeTruthy();
    expect(screen.queryByText(PHOTO_HINT)).toBeNull();
    clickSubmit();
    await waitFor(() => expect(submitMock).toHaveBeenCalledTimes(2));
    expect(submitMock.mock.calls[1][0].photo).toBe(chosenLater);
  });

  it("a field error in no tab shows at the top, and a field error in a tab stays under its box", async () => {
    submitMock.mockResolvedValueOnce(
      result({ field_errors: { nationality: ["x"], family_name: ["y"] } }),
    );
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    const top = await screen.findByText("x");
    expect(top.tagName).toBe("P");
    expect(inputOf("family_name").closest("label")?.textContent).toContain("y");
  });

  it("a refused post without a photo shows no hint", async () => {
    submitMock.mockResolvedValueOnce(result({ form_errors: ["Бүртгэл алдаатай"] }));
    renderPage();
    typeInto("family_name", "Бат");
    clickSubmit();
    expect(await screen.findByText("Бүртгэл алдаатай")).toBeTruthy();
    expect(screen.queryByText(PHOTO_HINT)).toBeNull();
  });

  it("an empty required box in a hidden tab opens that tab and focuses the box", () => {
    renderPage();
    fireEvent.click(tab(/Хувийн/));
    expect(document.querySelector('[data-tab="basic"]')?.classList.contains("hidden")).toBe(true);
    const order = inputOf("order-number");
    // Two invalid controls in one submit attempt: the first (the basic tab's order number) decides.
    fireEvent(order, new Event("invalid"));
    fireEvent(inputOf("email"), new Event("invalid"));
    expect(tab(/Үндсэн/).getAttribute("aria-selected")).toBe("true");
    expect(tab(/Хувийн/).getAttribute("aria-selected")).toBe("false");
    expect(document.querySelector('[data-tab="basic"]')?.classList.contains("hidden")).toBe(false);
    expect(document.activeElement).toBe(order);
  });

  describe("the district follows the city", () => {
    // The address boxes sit in the personal tab. The city is a plain box here, so a test can type a new city.
    function addressForm(city: string, district: string): HireFormOut {
      const address: EmployeeFormFieldOut[] = [
        field({ name: "addr-city", label: "Хот", kind: "text", value: city }),
        field({
          name: "addr-district",
          label: "Сум, дүүрэг",
          kind: "select",
          value: district,
          choices: [{ value: "1", label: "Баянзүрх" }],
        }),
      ];
      return {
        ...FORM,
        fields: [...FIELDS, ...address],
        tabs: FORM.tabs.map((tab) =>
          tab.key === "personal"
            ? {
                ...tab,
                sections: [
                  ...tab.sections,
                  { heading: "Хаяг", kind: "fields", names: ["addr-city", "addr-district"], note: "" },
                ],
              }
            : tab,
        ),
      };
    }

    beforeEach(() => {
      districtsMock.mockReset();
    });

    it("a city change loads that city's districts into the district box", async () => {
      districtsMock.mockImplementation(async (city) =>
        city === "21" ? [{ value: "5", label: "Дархан-1" }] : [{ value: "1", label: "Баянзүрх" }],
      );
      formWith(addressForm("11", "1"));
      renderPage();
      await act(async () => {});
      typeInto("addr-city", "21");
      await waitFor(() => expect(districtsMock).toHaveBeenCalledWith("21"));
      await act(async () => {});
      fireEvent.click(screen.getByRole("combobox"));
      expect(screen.getByRole("option", { name: "Дархан-1" })).toBeTruthy();
    });

    it("a district no longer offered is cleared once loading is done, never while loading", async () => {
      let release!: (choices: HireChoiceOut[]) => void;
      districtsMock.mockImplementation((city) =>
        city === "21"
          ? new Promise<HireChoiceOut[]>((resolve) => (release = resolve))
          : Promise.resolve([{ value: "1", label: "Баянзүрх" }]),
      );
      submitMock.mockResolvedValue(result());
      formWith(addressForm("11", "1"));
      renderPage();
      await act(async () => {});
      typeInto("addr-city", "21");
      await waitFor(() => expect(districtsMock).toHaveBeenCalledWith("21"));
      // Still loading: the district is kept, so the post carries it.
      clickSubmit();
      expect(submitMock.mock.calls[0][0].values["addr-district"]).toBe("1");
      await act(async () => release([{ value: "5", label: "Дархан-1" }]));
      await waitFor(() => expect(inputOf("addr-district").value).toBe(""));
    });

    it("clearing the city clears the district", async () => {
      districtsMock.mockResolvedValue([{ value: "1", label: "Баянзүрх" }]);
      formWith(addressForm("11", "1"));
      renderPage();
      await act(async () => {});
      expect(inputOf("addr-district").value).toBe("1");
      typeInto("addr-city", "");
      await waitFor(() => expect(inputOf("addr-district").value).toBe(""));
    });

    it("the first render keeps the server's district when both are set", async () => {
      districtsMock.mockResolvedValue([{ value: "1", label: "Баянзүрх" }]);
      formWith(addressForm("11", "1"));
      renderPage();
      expect(inputOf("addr-district").value).toBe("1");
      await act(async () => {});
      expect(inputOf("addr-district").value).toBe("1");
    });

    it("the district box sits in the div#addr-district-wrap wrapper", async () => {
      districtsMock.mockResolvedValue([{ value: "1", label: "Баянзүрх" }]);
      formWith(addressForm("11", "1"));
      renderPage();
      await act(async () => {});
      const wrap = document.getElementById("addr-district-wrap");
      expect(wrap).not.toBeNull();
      expect(wrap?.contains(inputOf("addr-district"))).toBe(true);
    });

    it("a district that is still offered is kept", async () => {
      let release!: (choices: HireChoiceOut[]) => void;
      districtsMock.mockImplementation((city) =>
        city === "21"
          ? new Promise<HireChoiceOut[]>((resolve) => (release = resolve))
          : Promise.resolve([{ value: "1", label: "Баянзүрх" }]),
      );
      submitMock.mockResolvedValue(result());
      formWith(addressForm("11", "1"));
      renderPage();
      await act(async () => {});
      typeInto("addr-city", "21");
      await waitFor(() => expect(districtsMock).toHaveBeenCalledWith("21"));
      await act(async () => release([{ value: "1", label: "Баянзүрх" }]));
      clickSubmit();
      expect(submitMock.mock.calls[0][0].values["addr-district"]).toBe("1");
    });
  });
});
