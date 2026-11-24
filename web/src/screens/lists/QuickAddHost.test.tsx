import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QuickAddProvider, useAddedOptions, useQuickAdd } from "./QuickAddHost";

// The API client answers by path (the real hooks run), and the signed-in user's perms come from a stub of useMeta.
const h = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), perms: [] as string[] }));

vi.mock("../../api/client", () => ({
  api: { GET: (...args: unknown[]) => h.get(...args), POST: (...args: unknown[]) => h.post(...args) },
  setCsrf: vi.fn(),
  getCsrf: vi.fn(() => "tok"),
  redirectToLogin: vi.fn(),
  nav: { assign: vi.fn() },
}));

vi.mock("../../shell/useMeta", () => ({
  useMeta: () => ({ data: { user: { perms: h.perms } } }),
}));

vi.mock("../../widgets/confirm", () => ({ confirm: vi.fn() }));

const INDEX = {
  items: [{ slug: "district", label: "Сум, дүүрэг", count: 0, hits: 0 }],
};

// A district-like list: a name box and a required parent (city) select.
const FORM = {
  title: "Сум, дүүрэг",
  can_delete: false,
  fields: [
    { name: "name", label: "Нэр", kind: "text", required: true, value: "", errors: [], choices: [], max_length: 100 },
    {
      name: "city",
      label: "Аймаг, хот",
      kind: "select",
      required: true,
      value: "",
      errors: [],
      max_length: null,
      choices: [
        { value: "", label: "— сонгоогүй —" },
        { value: "1", label: "Улаанбаатар" },
        { value: "2", label: "Дархан" },
      ],
    },
  ],
};

function ok(data: unknown) {
  return { data, error: undefined, response: { ok: true, status: 200 } };
}

function wrapperWith(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <QuickAddProvider>{children}</QuickAddProvider>
      </QueryClientProvider>
    );
  };
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

describe("QuickAddHost", () => {
  beforeEach(() => {
    h.get.mockReset();
    h.post.mockReset();
    h.perms = ["lists.manage_lists"];
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/lists") return ok(INDEX);
      if (path === "/api/v1/lists/{slug}/form") return ok(FORM);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
  });

  afterEach(() => {
    cleanup();
    document.body.innerHTML = "";
  });

  it("selectProps returns nothing for a field that is not addable (null or undefined)", () => {
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const onPicked = vi.fn();

    expect(result.current.selectProps(null, onPicked)).toEqual({});
    expect(result.current.selectProps(undefined, onPicked)).toEqual({});
  });

  it("a plain add (modal false) gives the quick URL and canAdd, with no modal", () => {
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });

    const props = result.current.selectProps({ slug: "branch", modal: false, parent: null }, vi.fn());

    expect(props).toEqual({ addUrl: "/api/v1/lists/branch/quick", canAdd: true });
    expect(props).not.toHaveProperty("addModal");
    expect(props).not.toHaveProperty("onAddModal");
  });

  it("canAdd is false without lists.manage_lists, so the add line stays hidden", () => {
    h.perms = [];
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });

    expect(result.current.canAdd).toBe(false);
    expect(result.current.selectProps({ slug: "branch", modal: false, parent: null }, vi.fn())).toEqual({
      addUrl: "/api/v1/lists/branch/quick",
      canAdd: false,
    });
  });

  it("a modal add opens the pop-up with the typed text and the parent value read from the DOM", async () => {
    const parent = document.createElement("select");
    parent.setAttribute("name", "city");
    parent.innerHTML = '<option value="">—</option><option value="2" selected>Дархан</option>';
    document.body.appendChild(parent);

    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: "city" }, vi.fn());

    expect(props.addModal).toBe(true);
    expect(props.addUrl).toBe("/api/v1/lists/district/quick");
    expect(props.canAdd).toBe(true);

    act(() => props.onAddModal?.("Баянзүрх"));

    await screen.findByRole("button", { name: "Хадгалах" });
    expect(screen.getByRole("heading", { name: "Сум, дүүрэг: шинэ бичлэг" })).toBeTruthy();
    // The modal's own city box is the last [name="city"] in the document (the portal comes after the page).
    const boxes = document.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[name="city"]');
    expect(boxes[boxes.length - 1].value).toBe("2");
    const names = document.querySelectorAll<HTMLInputElement>('input[name="name"]');
    expect(names[names.length - 1].value).toBe("Баянзүрх");
  });

  it("a modal add with no parent control on the page sends an empty parent value", async () => {
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: "city" }, vi.fn());

    act(() => props.onAddModal?.("Хан-Уул"));

    await screen.findByRole("button", { name: "Хадгалах" });
    const boxes = document.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[name="city"]');
    expect(boxes[boxes.length - 1].value).toBe("");
  });

  it("a saved modal calls onPicked with the new entry and closes the pop-up", async () => {
    h.post.mockResolvedValue(ok({ value: 7, label: "Баянзүрх", existed: false }));
    const onPicked = vi.fn();
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: null }, onPicked);

    act(() => props.onAddModal?.("Баянзүрх"));
    await screen.findByRole("button", { name: "Хадгалах" });
    fireEvent.click(screen.getByRole("button", { name: "Хадгалах" }));

    await waitFor(() => expect(onPicked).toHaveBeenCalledWith("7", "Баянзүрх"));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull());
  });

  it("opening a second modal while one is open does nothing (at most one pop-up)", async () => {
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: null }, vi.fn());

    act(() => props.onAddModal?.("Эхний"));
    await screen.findByRole("button", { name: "Хадгалах" });
    act(() => props.onAddModal?.("Хоёр"));

    const names = document.querySelectorAll<HTMLInputElement>('input[name="name"]');
    expect(names.length).toBe(1);
    expect(names[0].value).toBe("Эхний");
  });

  it("a parentName option finds the parent by its prefixed name, not the server's own name", async () => {
    const page = document.createElement("div");
    page.innerHTML =
      '<select name="city"><option value="1" selected>Улаанбаатар</option></select>' +
      '<select name="addr-city"><option value="">—</option><option value="2" selected>Дархан</option></select>';
    document.body.appendChild(page);

    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: "city" }, vi.fn(), {
      parentName: "addr-city",
    });

    act(() => props.onAddModal?.("Баянзүрх"));

    await screen.findByRole("button", { name: "Хадгалах" });
    const boxes = document.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[name="city"]');
    expect(boxes[boxes.length - 1].value).toBe("2");
  });

  it("the parent is looked for in the dialog of the focused control when two controls share the name", async () => {
    const outer = document.createElement("select");
    outer.setAttribute("name", "city");
    outer.innerHTML = '<option value="1" selected>Улаанбаатар</option><option value="2">Дархан</option>';
    document.body.appendChild(outer);

    const dialog = document.createElement("div");
    dialog.setAttribute("role", "dialog");
    dialog.innerHTML =
      '<select name="city"><option value="1">Улаанбаатар</option><option value="2" selected>Дархан</option></select>' +
      '<input type="text" id="combo" />';
    document.body.appendChild(dialog);
    const combo = dialog.querySelector<HTMLInputElement>("#combo");
    combo?.focus();
    expect(document.activeElement).toBe(combo);

    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: "city" }, vi.fn());

    act(() => props.onAddModal?.("Баянзүрх"));

    await screen.findByRole("button", { name: "Хадгалах" });
    const boxes = document.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[name="city"]');
    expect(boxes[boxes.length - 1].value).toBe("2");
  });

  it("the pop-up opens with the slug as its title when the index has no row for the list", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/lists") return ok({ items: [] });
      if (path === "/api/v1/lists/{slug}/form") return ok(FORM);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: null }, vi.fn());

    act(() => props.onAddModal?.("Эхний"));

    await screen.findByRole("button", { name: "Хадгалах" });
    expect(screen.getByRole("heading", { name: "district: шинэ бичлэг" })).toBeTruthy();
  });

  it("a second add works after the first pop-up is closed, even with no index row", async () => {
    h.get.mockImplementation(async (path: string) => {
      if (path === "/api/v1/lists") return ok({ items: [] });
      if (path === "/api/v1/lists/{slug}/form") return ok(FORM);
      return { data: undefined, error: {}, response: { ok: false, status: 404 } };
    });
    const { result } = renderHook(() => useQuickAdd(), { wrapper: wrapperWith(newClient()) });
    const props = result.current.selectProps({ slug: "district", modal: true, parent: null }, vi.fn());

    act(() => props.onAddModal?.("Эхний"));
    await screen.findByRole("button", { name: "Хадгалах" });
    fireEvent.click(screen.getByRole("button", { name: "Болих" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Хадгалах" })).toBeNull());

    act(() => props.onAddModal?.("Хоёр"));
    await screen.findByRole("button", { name: "Хадгалах" });
    const names = document.querySelectorAll<HTMLInputElement>('input[name="name"]');
    expect(names[names.length - 1].value).toBe("Хоёр");
  });

  it("outside a provider the hook gives canAdd false and no props, so nothing breaks", () => {
    const { result } = renderHook(() => useQuickAdd());

    expect(result.current.canAdd).toBe(false);
    expect(result.current.selectProps({ slug: "branch", modal: false, parent: null }, vi.fn())).toEqual({});
    expect(result.current.selectProps({ slug: "district", modal: true, parent: "city" }, vi.fn())).toEqual({});
  });
});

describe("useAddedOptions", () => {
  const CHOICES = [
    { value: "1", label: "Улаанбаатар" },
    { value: "2", label: "Дархан" },
  ];

  it("an entry added through add shows in options after the server's choices", () => {
    const { result } = renderHook(() => useAddedOptions(CHOICES));

    act(() => result.current.add("9", "Баянзүрх"));

    expect(result.current.options).toEqual([...CHOICES, { value: "9", label: "Баянзүрх" }]);
  });

  it("a new array with the same choices keeps the added entries", () => {
    const { result, rerender } = renderHook(({ choices }) => useAddedOptions(choices), {
      initialProps: { choices: CHOICES },
    });
    act(() => result.current.add("9", "Баянзүрх"));

    rerender({ choices: CHOICES.map((choice) => ({ ...choice })) });

    expect(result.current.options).toEqual([...CHOICES, { value: "9", label: "Баянзүрх" }]);
  });

  it("changed choices clear the added entries (a deleted or other-parent entry is not a ghost option)", () => {
    const { result, rerender } = renderHook(({ choices }) => useAddedOptions(choices), {
      initialProps: { choices: CHOICES },
    });
    act(() => result.current.add("9", "Баянзүрх"));

    rerender({ choices: [{ value: "3", label: "Өмнөговь" }] });

    expect(result.current.options).toEqual([{ value: "3", label: "Өмнөговь" }]);
  });

  it("an entry already in the choices is not duplicated", () => {
    const { result } = renderHook(() => useAddedOptions(CHOICES));

    act(() => result.current.add("1", "Улаанбаатар"));

    expect(result.current.options).toEqual(CHOICES);
  });
});
