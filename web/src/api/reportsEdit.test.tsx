// The harness is imported first: it stubs fetch before ./client (and so ./reportsEdit) load.
import { csrfFailure, fetchMock, jsonResponse, metaBody, rejectionOf, resetFetch, resetObservers, urlOf } from "./testSupport";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup } from "@testing-library/react";
import { getCsrf, nav, setCsrf } from "./client";
import {
  EditFailed,
  SessionLost,
  bulkCells,
  fetchEditor,
  saveEdit,
  type BulkCellIn,
  type ReportEditTarget,
} from "./reportsEdit";

const NET_TEXT = "Холбогдож чадсангүй. Дахин оролдоно уу.";
// The grid_nav.js texts: SAVE_FAIL for a refused save, NO_FORM_MSG for an editor that did not open.
const SAVE_TEXT = "Хадгалж чадсангүй. Дахин оролдоно уу.";
const NO_FORM_TEXT = "Засварлагч нээгдсэнгүй. Хуудсаа шинэчилнэ үү.";
const SESSION_TEXT = "Нэвтрэх хугацаа дууссан. Хуудсаа шинэчилж дахин нэвтэрнэ үү.";

const CELL: ReportEditTarget = { route: "cell", person: 3, field: "phone", kind: "", key: 0, record: 0, salary: false };
const ROW: ReportEditTarget = { route: "row", person: 3, field: "birth_date", kind: "children", key: 9, record: 0, salary: false };
const JOB: ReportEditTarget = { route: "correct", person: 3, field: "position", kind: "", key: 0, record: 12, salary: false };
const SALARY: ReportEditTarget = { route: "correct", person: 3, field: "salary", kind: "", key: 0, record: 0, salary: true };

const EDITOR = {
  kind: "text",
  name: "phone",
  value: "99112233",
  label: "",
  choices: [],
  required: false,
  maxlength: 20,
  loaded: "tok-1",
  hidden: {},
  reason: false,
  old: "",
  note: "",
  reason_text: "",
  blocked: "",
  error: "",
};

const SAVED = { ok: true, text: "99998888", error: "", editor: null };

function bodyOf(index: number): Promise<unknown> {
  return (fetchMock.mock.calls[index][0] as Request).text().then((text) => JSON.parse(text));
}

describe("report edit API", () => {
  beforeEach(() => {
    resetFetch();
    setCsrf("");
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetObservers();
  });

  it("fetchEditor of a cell sends person and field to the cell editor route", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, EDITOR));

    const editor = await fetchEditor(CELL);

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("GET");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/cell/editor");
    expect(urlOf(0).searchParams.get("person")).toBe("3");
    expect(urlOf(0).searchParams.get("field")).toBe("phone");
    expect(editor).toMatchObject({ kind: "text", value: "99112233", loaded: "tok-1" });
  });

  it("fetchEditor of a row sends person, kind, key and field to the row editor route", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ...EDITOR, name: "birth_date", kind: "date" }));

    await fetchEditor(ROW);

    expect(urlOf(0).pathname).toBe("/api/v1/reports/row-cell/editor");
    expect(urlOf(0).searchParams.get("person")).toBe("3");
    expect(urlOf(0).searchParams.get("kind")).toBe("children");
    expect(urlOf(0).searchParams.get("key")).toBe("9");
    expect(urlOf(0).searchParams.get("field")).toBe("birth_date");
  });

  it("fetchEditor of a correction sends the field as key and the record id", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, EDITOR));

    await fetchEditor(JOB);

    expect(urlOf(0).pathname).toBe("/api/v1/reports/correct/editor");
    expect(urlOf(0).searchParams.get("key")).toBe("position");
    expect(urlOf(0).searchParams.get("record")).toBe("12");
  });

  it("fetchEditor of the base salary sends an empty record, as the view's default", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, EDITOR));

    await fetchEditor(SALARY);

    expect(urlOf(0).pathname).toBe("/api/v1/reports/correct/editor");
    expect(urlOf(0).searchParams.get("key")).toBe("salary");
    expect(urlOf(0).searchParams.get("record")).toBe("");
  });

  it("saveEdit of a cell posts person, field, value and the loaded token", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, SAVED));

    const result = await saveEdit(CELL, { value: "99998888", loaded: "tok-1", old: "", reason: "", hidden: {} });

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/cell");
    expect(await bodyOf(0)).toEqual({ person: 3, field: "phone", value: "99998888", loaded: "tok-1" });
    expect(result).toEqual(SAVED);
  });

  it("saveEdit of a row posts the hidden values with the visible field", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ...SAVED, text: "2001-02-03" }));
    const hidden = { loaded_name: "tok-a", name: "Бат" };

    await saveEdit(ROW, { value: "2001-02-03", loaded: "", old: "", reason: "", hidden });

    expect(urlOf(0).pathname).toBe("/api/v1/reports/row-cell");
    expect(await bodyOf(0)).toEqual({
      person: 3,
      kind: "children",
      key: 9,
      field: "birth_date",
      values: { loaded_name: "tok-a", name: "Бат", birth_date: "2001-02-03" },
    });
  });

  it("saveEdit of a correction posts the record, and null for the base salary", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, SAVED)).mockResolvedValueOnce(jsonResponse(200, SAVED));

    await saveEdit(JOB, { value: "7", loaded: "", old: "5", reason: "Алдаа", hidden: {} });
    await saveEdit(SALARY, { value: "900000", loaded: "", old: "800000", reason: "Тушаал", hidden: {} });

    expect(urlOf(0).pathname).toBe("/api/v1/reports/correct");
    expect(await bodyOf(0)).toEqual({ person: 3, key: "position", record: 12, value: "7", old: "5", reason: "Алдаа" });
    expect(await bodyOf(1)).toEqual({ person: 3, key: "salary", record: null, value: "900000", old: "800000", reason: "Тушаал" });
  });

  it("a refused save answers ok false with its editor as data, without a throw", async () => {
    const refused = { ok: false, text: "", error: "Өөрчлөгдсөн байна.", editor: { ...EDITOR, value: "55", loaded: "tok-2" } };
    fetchMock.mockResolvedValueOnce(jsonResponse(200, refused));

    const result = await saveEdit(CELL, { value: "1", loaded: "tok-1", old: "", reason: "", hidden: {} });

    expect(result).toMatchObject({ ok: false, error: "Өөрчлөгдсөн байна.", editor: { value: "55", loaded: "tok-2" } });
  });

  it("bulkCells posts apply and the cells to the bulk route and returns each outcome", async () => {
    const cells: BulkCellIn[] = [{ person: 3, field: "phone", text: "99", old: "98" }];
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { cells: [{ person: 3, field: "phone", ok: false, text: "", error: "Эрх байхгүй" }], saved: 0 }),
    );

    const result = await bulkCells(cells, false);

    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/reports/cells");
    expect(await bodyOf(0)).toEqual({ apply: false, cells });
    expect(result).toEqual({ cells: [{ person: 3, field: "phone", ok: false, text: "", error: "Эрх байхгүй" }], saved: 0 });
  });

  it("a 401 on a read or a save throws SessionLost with the verbatim text", async () => {
    // The shared client middleware (client.ts) also sends a 401 to the login page; the navigation is stubbed here.
    vi.spyOn(nav, "assign").mockImplementation(() => undefined);
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { field_errors: {}, form_errors: [], code: "not_authenticated" }));
    const read = await rejectionOf(() => fetchEditor(CELL));
    expect(read).toBeInstanceOf(SessionLost);
    expect((read as Error).message).toBe(SESSION_TEXT);

    fetchMock.mockResolvedValueOnce(jsonResponse(401, { field_errors: {}, form_errors: [], code: "not_authenticated" }));
    const save = await rejectionOf(() => saveEdit(CELL, { value: "1", loaded: "", old: "", reason: "", hidden: {} }));
    expect(save).toBeInstanceOf(SessionLost);
    expect((save as Error).message).toBe(SESSION_TEXT);
  });

  it("a 404 or 403 is an ApiFailure with its status and first form error for the editor to show", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(404, { field_errors: {}, form_errors: ["Олдсонгүй"] }));
    const missing = await rejectionOf(() => fetchEditor(CELL));
    expect(missing).toMatchObject({ status: 404, message: "Олдсонгүй", formErrors: ["Олдсонгүй"] });

    fetchMock.mockResolvedValueOnce(jsonResponse(403, { field_errors: {}, form_errors: [], code: "forbidden" }));
    const refused = await rejectionOf(() => saveEdit(CELL, { value: "1", loaded: "", old: "", reason: "", hidden: {} }));
    expect(refused).toMatchObject({ status: 403, message: SAVE_TEXT, code: "forbidden" });
    expect(refused).not.toBeInstanceOf(EditFailed);
    expect(refused).not.toBeInstanceOf(SessionLost);
  });

  it("an editor that fails to open with no form error says it did not open; a refused save says the save failed", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(500, {}));
    const open = await rejectionOf(() => fetchEditor(CELL));
    expect(open).toMatchObject({ status: 500, message: NO_FORM_TEXT });
    expect(open).not.toBeInstanceOf(EditFailed);

    fetchMock.mockResolvedValueOnce(jsonResponse(500, {}));
    const save = await rejectionOf(() => saveEdit(CELL, { value: "1", loaded: "", old: "", reason: "", hidden: {} }));
    expect(save).toMatchObject({ status: 500, message: SAVE_TEXT });
    expect(save).not.toBeInstanceOf(EditFailed);
  });

  it("a network failure throws EditFailed with the network text", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const read = await rejectionOf(() => fetchEditor(CELL));
    expect(read).toBeInstanceOf(EditFailed);
    expect((read as Error).message).toBe(NET_TEXT);

    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const save = await rejectionOf(() => bulkCells([], true));
    expect(save).toBeInstanceOf(EditFailed);
    expect((save as Error).message).toBe(NET_TEXT);
  });

  it("a bulk 400 is an ApiFailure whose message is the body's error text", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(400, { error: "Мөрийн тоо 500-аас хэтэрлээ." }));

    const caught = await rejectionOf(() => bulkCells([], true));

    expect(caught).not.toBeInstanceOf(EditFailed);
    expect(caught).toMatchObject({ status: 400, message: "Мөрийн тоо 500-аас хэтэрлээ." });
  });

  it("a bulk 401 throws SessionLost with the verbatim text", async () => {
    vi.spyOn(nav, "assign").mockImplementation(() => undefined);
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { field_errors: {}, form_errors: [], code: "not_authenticated" }));

    const caught = await rejectionOf(() => bulkCells([{ person: 3, field: "phone", text: "1", old: "" }], true));

    expect(caught).toBeInstanceOf(SessionLost);
    expect((caught as Error).message).toBe(SESSION_TEXT);
  });

  it("a bulk 500 with no body is an ApiFailure with the save text", async () => {
    fetchMock.mockResolvedValueOnce(new Response("oops", { status: 500 }));

    const caught = await rejectionOf(() => bulkCells([], false));

    expect(caught).not.toBeInstanceOf(EditFailed);
    expect(caught).toMatchObject({ status: 500, message: SAVE_TEXT });
  });

  it("a save refused for a stale CSRF token is sent once more with the fresh token", async () => {
    setCsrf("old-token");
    fetchMock
      .mockResolvedValueOnce(csrfFailure())
      .mockResolvedValueOnce(jsonResponse(200, metaBody("fresh-token")))
      .mockResolvedValueOnce(jsonResponse(200, SAVED));

    const result = await saveEdit(CELL, { value: "99998888", loaded: "tok-1", old: "", reason: "", hidden: {} });

    expect(result).toEqual(SAVED);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect((fetchMock.mock.calls[0][0] as Request).headers.get("X-CSRFToken")).toBe("old-token");
    expect((fetchMock.mock.calls[2][0] as Request).headers.get("X-CSRFToken")).toBe("fresh-token");
    expect(getCsrf()).toBe("fresh-token");
  });
});
