import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps, FormEvent } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { rejectSubmission, sendBack, type HireDuplicateOut, type HireReviewOut } from "../../api/hire";
import { ReviewPanel } from "./ReviewPanel";

vi.mock("../../api/hire", () => ({
  sendBack: vi.fn(),
  rejectSubmission: vi.fn(),
}));

const sendBackMock = vi.mocked(sendBack);
const rejectMock = vi.mocked(rejectSubmission);

const NOTE_NEEDED = "Засах шалтгаанаа бичнэ үү.";
const REASON_NEEDED = "Татгалзсан шалтгаанаа бичнэ үү.";

const FULL_REVIEW: HireReviewOut = {
  contact: [
    ["Нэр", "Бат"],
    ["Утас", "99112233"],
  ],
  education: [[["Сургууль", "МУИС"], ["Мэргэжил", "Програмист"]]],
  family: [[["Харьцаа", "Эхнэр"], ["Нэр", "Сара"]]],
  has_photo: true,
  hr_note: "Анкетыг шалгах хэрэгтэй",
  submitted_at: "2026-11-10",
};

const EMPTY_REVIEW: HireReviewOut = {
  contact: [],
  education: [],
  family: [],
  has_photo: false,
  hr_note: "",
  submitted_at: "2026-11-10",
};

const VISIBLE_DUPLICATE: HireDuplicateOut = {
  employee_name: "Доржийн Бат",
  employee_pk: 7,
  visible: true,
};

const HIDDEN_DUPLICATE: HireDuplicateOut = {
  employee_name: "Хэн нэгэн",
  employee_pk: 9,
  visible: false,
};

const SELF_FORMS = "/employees/self-forms/";

// The panel sits inside the hire form on the add-employee page (Task 13). The wrapper is that form; its submit event is
// spied so a click or Enter that reached it would show.
function renderPanel(
  props: Partial<ComponentProps<typeof ReviewPanel>> = {},
) {
  const onDone = vi.fn();
  const onWrapperSubmit = vi.fn((event: FormEvent<HTMLFormElement>) => event.preventDefault());
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <form data-testid="hire-form" onSubmit={onWrapperSubmit}>
          <ReviewPanel
            review={FULL_REVIEW}
            duplicate={null}
            submissionId={31}
            onDone={onDone}
            {...props}
          />
        </form>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, onDone, onWrapperSubmit, wrapper: utils.getByTestId("hire-form") as HTMLFormElement };
}

function noteBox(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[name="note"]') as HTMLInputElement;
}

function reasonBox(container: HTMLElement): HTMLInputElement {
  return container.querySelector('input[name="reason"]') as HTMLInputElement;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  sendBackMock.mockReset();
  rejectMock.mockReset();
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ReviewPanel content", () => {
  it("shows the heading, the submitted date and the fixed explanation", () => {
    renderPanel();
    const section = screen.getByRole("region", { name: "Ажилтны өөрөө бөглөсөн анкет" });
    expect(section.tagName).toBe("SECTION");
    expect(section.textContent).toContain("Илгээсэн: 2026-11-10.");
    expect(section.textContent).toContain("Ажилтны анхны хариулт өөрчлөгдөхгүй хадгалагдана.");
  });

  it("shows бүртгэгдээгүй for each empty list", () => {
    renderPanel({ review: EMPTY_REVIEW });
    expect(screen.getAllByText("бүртгэгдээгүй")).toHaveLength(3);
  });

  it("draws the rows as label and value pairs", () => {
    renderPanel();
    expect(screen.getByText("Сургууль:").parentElement?.textContent).toBe("Сургууль: МУИС");
    expect(screen.getByText("Утас:").parentElement?.textContent).toBe("Утас: 99112233");
  });

  it("shows the photo line only when has_photo is set", () => {
    const { unmount } = renderPanel();
    expect(screen.getByText("Ажилтан зураг илгээсэн: хадгалахад хавсарна")).toBeTruthy();
    unmount();
    renderPanel({ review: { ...FULL_REVIEW, has_photo: false } });
    expect(screen.queryByText("Ажилтан зураг илгээсэн: хадгалахад хавсарна")).toBeNull();
  });

  it("shows the HR note only when present", () => {
    const { unmount } = renderPanel();
    expect(screen.getByText("Анкетыг шалгах хэрэгтэй")).toBeTruthy();
    unmount();
    renderPanel({ review: { ...FULL_REVIEW, hr_note: "" } });
    expect(screen.queryByText("HR тэмдэглэл:")).toBeNull();
  });
});

describe("ReviewPanel duplicate warning", () => {
  it("links a visible duplicate to the employee page", () => {
    renderPanel({ duplicate: VISIBLE_DUPLICATE });
    const link = screen.getByRole("link", { name: "Доржийн Бат" });
    expect(link.getAttribute("href")).toBe("/employees/7/");
    expect(screen.getByText(/аль хэдийн харьяалагдсан байна/)).toBeTruthy();
  });

  it("shows the plain sentence and no link for a hidden duplicate", () => {
    renderPanel({ duplicate: HIDDEN_DUPLICATE });
    expect(screen.queryByRole("link", { name: /Хэн нэгэн/ })).toBeNull();
    expect(screen.getByText(/Энэ регистрийн дугаартай ажилтан бүртгэлтэй байна\./)).toBeTruthy();
  });

  it("shows no warning without a duplicate", () => {
    renderPanel({ duplicate: null });
    expect(screen.queryByText(/Энэ регистрийн дугаар/)).toBeNull();
  });
});

describe("ReviewPanel decisions", () => {
  it("sends the trimmed note and calls onDone once with the redirect", async () => {
    sendBackMock.mockResolvedValue({ ok: true, form_errors: [], redirect: SELF_FORMS });
    const { container, onDone } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "  Нэрээ засна уу  " } });
    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(sendBackMock).toHaveBeenCalledWith(expect.anything(), 31, "Нэрээ засна уу");
    expect(onDone).toHaveBeenCalledWith(SELF_FORMS);
  });

  it("shows the refusal message under the box and does not call onDone", async () => {
    sendBackMock.mockResolvedValue({
      ok: false,
      form_errors: ["Энэ анкетыг аль хэдийн шийдсэн байна."],
      redirect: "",
    });
    const { container, onDone } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Тайлбар" } });
    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));
    expect(await screen.findByText("Энэ анкетыг аль хэдийн шийдсэн байна.")).toBeTruthy();
    expect(onDone).not.toHaveBeenCalled();
  });

  it("shows the generic line when the request fails and re-enables the button", async () => {
    sendBackMock.mockRejectedValue(new Error("network"));
    const { container, onDone } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Тайлбар" } });
    const button = screen.getByRole("button", { name: "Буцаах" }) as HTMLButtonElement;
    fireEvent.click(button);
    expect(await screen.findByText("Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.")).toBeTruthy();
    expect(onDone).not.toHaveBeenCalled();
    expect(button.disabled).toBe(false);
  });

  it("disables the button while the request runs", async () => {
    const pending = deferred<{ ok: boolean; form_errors: string[]; redirect: string }>();
    sendBackMock.mockReturnValue(pending.promise);
    const { container, onDone } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Тайлбар" } });
    const button = screen.getByRole("button", { name: "Буцаах" }) as HTMLButtonElement;
    fireEvent.click(button);
    expect(button.disabled).toBe(true);
    pending.resolve({ ok: true, form_errors: [], redirect: SELF_FORMS });
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
  });

  it("does not call the API for an empty note, focuses the box and shows the server text", () => {
    const { container, onDone } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "   " } });
    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));
    expect(sendBackMock).not.toHaveBeenCalled();
    expect(onDone).not.toHaveBeenCalled();
    expect(document.activeElement).toBe(noteBox(container));
    expect(screen.getByRole("alert").textContent).toBe(NOTE_NEEDED);
  });

  it("clears the empty-box message when the user types", () => {
    const { container } = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));
    expect(screen.getByText(NOTE_NEEDED)).toBeTruthy();
    fireEvent.change(noteBox(container), { target: { value: "а" } });
    expect(screen.queryByText(NOTE_NEEDED)).toBeNull();
  });

  it("does not call the API for an empty reason and shows the reason text", () => {
    const { container } = renderPanel();
    fireEvent.change(reasonBox(container), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Тийм, татгалзах" }));
    expect(rejectMock).not.toHaveBeenCalled();
    expect(screen.getByText(REASON_NEEDED)).toBeTruthy();
  });

  it("sends the trimmed reason through rejectSubmission", async () => {
    rejectMock.mockResolvedValue({ ok: true, form_errors: [], redirect: SELF_FORMS });
    const { container, onDone } = renderPanel();
    fireEvent.change(reasonBox(container), { target: { value: " Давхар анкет " } });
    fireEvent.click(screen.getByRole("button", { name: "Тийм, татгалзах" }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith(SELF_FORMS));
    expect(rejectMock).toHaveBeenCalledWith(expect.anything(), 31, "Давхар анкет");
    expect(sendBackMock).not.toHaveBeenCalled();
  });

  it("a fast double click on Буцаах sends once and calls onDone once", async () => {
    sendBackMock.mockResolvedValue({ ok: true, form_errors: [], redirect: SELF_FORMS });
    const { container, onDone } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Тайлбар" } });
    const button = screen.getByRole("button", { name: "Буцаах" });
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(sendBackMock).toHaveBeenCalledTimes(1);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("unmounting during a pending request does not warn and does not call onDone", async () => {
    const errorSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const pending = deferred<{ ok: boolean; form_errors: string[]; redirect: string }>();
    sendBackMock.mockReturnValue(pending.promise);
    const { container, onDone, unmount } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Тайлбар" } });
    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));
    unmount();
    pending.resolve({ ok: true, form_errors: [], redirect: SELF_FORMS });
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(onDone).not.toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
  });
});

describe("ReviewPanel inside the hire form", () => {
  it("the wrapper form is valid with both decision boxes empty", () => {
    const { wrapper } = renderPanel();
    expect(wrapper.checkValidity()).toBe(true);
  });

  it("a decision button click does not submit the wrapper form", () => {
    const { onWrapperSubmit, container } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Тайлбар" } });
    fireEvent.click(screen.getByRole("button", { name: "Буцаах" }));
    fireEvent.click(screen.getByRole("button", { name: "Тийм, татгалзах" }));
    expect(onWrapperSubmit).not.toHaveBeenCalled();
  });

  it("Enter in the note box sends back only, and stops the form submit", async () => {
    sendBackMock.mockResolvedValue({ ok: true, form_errors: [], redirect: SELF_FORMS });
    const { container, onDone, onWrapperSubmit } = renderPanel();
    fireEvent.change(noteBox(container), { target: { value: "Нэрээ засна уу" } });
    const notPrevented = fireEvent.keyDown(noteBox(container), { key: "Enter" });
    expect(notPrevented).toBe(false);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(sendBackMock).toHaveBeenCalledWith(expect.anything(), 31, "Нэрээ засна уу");
    expect(rejectMock).not.toHaveBeenCalled();
    expect(onWrapperSubmit).not.toHaveBeenCalled();
  });

  it("Enter in the reason box rejects only, and stops the form submit", async () => {
    rejectMock.mockResolvedValue({ ok: true, form_errors: [], redirect: SELF_FORMS });
    const { container, onDone, onWrapperSubmit } = renderPanel();
    fireEvent.change(reasonBox(container), { target: { value: "Давхар" } });
    const notPrevented = fireEvent.keyDown(reasonBox(container), { key: "Enter" });
    expect(notPrevented).toBe(false);
    await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
    expect(rejectMock).toHaveBeenCalledWith(expect.anything(), 31, "Давхар");
    expect(sendBackMock).not.toHaveBeenCalled();
    expect(onWrapperSubmit).not.toHaveBeenCalled();
  });

  it("the reject block lives inside a details element, and the boxes are not required", () => {
    const { container } = renderPanel();
    const details = container.querySelector("details");
    expect(details?.querySelector("summary")?.textContent).toBe("Татгалзах");
    expect(reasonBox(container).closest("details")).toBe(details);
    expect(screen.getByRole("button", { name: "Тийм, татгалзах" }).closest("details")).toBe(details);
    expect(noteBox(container).hasAttribute("required")).toBe(false);
    expect(reasonBox(container).hasAttribute("required")).toBe(false);
    expect(noteBox(container).getAttribute("aria-required")).toBe("true");
  });

  it("the panel renders no form of its own", () => {
    const { container, wrapper } = renderPanel();
    expect(container.querySelectorAll("form")).toHaveLength(1);
    expect(noteBox(container).closest("form")).toBe(wrapper);
  });
});
