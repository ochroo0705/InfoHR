// The harness is imported first: it stubs fetch before ./client (and so ./recruitment) load.
import {
  fetchMock,
  invalidatedKeys,
  jsonResponse,
  newClient,
  rejectionOf,
  resetFetch,
  resetObservers,
  urlOf,
  wrapperFor,
} from "./testSupport";
import type { QueryClient } from "@tanstack/react-query";
import { act, cleanup, renderHook } from "@testing-library/react";
import { focusManager, onlineManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setCsrf } from "./client";
import {
  candidateFileUrl,
  useAddCandidate,
  useCandidate,
  useCommentCandidate,
  useConvertCandidate,
  useMoveCandidate,
  usePurge,
  usePurgePage,
  useRejectCandidate,
  useReopenCandidate,
  useSaveVacancy,
  useSlotLine,
  useUploadCandidateFile,
  useVacancies,
  useVacancy,
  useVacancyForm,
  useVacancyOptions,
  type RecruitCandidateOut,
  type RecruitVacancyListOut,
  type RecruitVacancyOut,
} from "./recruitment";
import type { ApiFailure } from "./mutate";

const LIST_PAGE_1 = {
  can_manage: true,
  empty_text: "",
  next_offset: 50,
  q: "",
  rows: [],
  status: "open",
} as unknown as RecruitVacancyListOut;

const LIST_PAGE_2 = { ...LIST_PAGE_1, next_offset: null } as unknown as RecruitVacancyListOut;

const VACANCY_PAGE_1 = {
  id: 4,
  can_manage: false,
  candidates: [],
  next_offset: 50,
  stage_bar: [],
  slot_line: null,
} as unknown as RecruitVacancyOut;

const VACANCY_PAGE_2 = { ...VACANCY_PAGE_1, next_offset: null } as unknown as RecruitVacancyOut;

const CANDIDATE = {
  id: 12,
  can_manage: false,
  comments: [],
  files: [],
  stage: "new",
  vacancy_id: 4,
} as unknown as RecruitCandidateOut;

const VACANCY_FORM = { title: "Үйлчлэгч", deadline: "", description: "", desired_start: "" };
const CANDIDATE_FORM = { surname: "Бат", given_name: "Болд", email: "", phone: "", source: "", notes: "" };
const OK = { ok: true, error: "", field_errors: {}, form_errors: [] };
const REFUSED = { ok: false, error: "Өөрчлөгдсөн", field_errors: {}, form_errors: ["Өөрчлөгдсөн"] };

// The keys a successful vacancy or candidate write must refresh: the whole recruitment prefix, attention and nav.
const WRITE_KEYS = [{ queryKey: ["recruitment"] }, { queryKey: ["attention"] }, { queryKey: ["nav"] }];

describe("recruitment API", () => {
  let client: QueryClient;

  beforeEach(() => {
    resetFetch();
    setCsrf("");
    client = newClient();
  });

  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    resetObservers();
    focusManager.setFocused(true);
    onlineManager.setOnline(true);
  });

  it("useVacancies sends only the filters that have a value, plus offset 0", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useVacancies({ status: "", q: "Үйлчлэгч" }), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = urlOf(0);
    expect(url.pathname).toBe("/api/v1/recruitment/vacancies");
    expect(url.searchParams.has("status")).toBe(false);
    expect(url.searchParams.get("q")).toBe("Үйлчлэгч");
    expect(url.searchParams.get("offset")).toBe("0");
  });

  it("useVacancies loads the next batch at next_offset and stops when next_offset is null", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, LIST_PAGE_2));

    const { result } = renderHook(() => useVacancies({ status: "open" }), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("50");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useVacancy asks for the vacancy at its path with the stage, and pages the candidates by next_offset", async () => {
    fetchMock
      .mockResolvedValueOnce(jsonResponse(200, VACANCY_PAGE_1))
      .mockResolvedValueOnce(jsonResponse(200, VACANCY_PAGE_2));

    const { result } = renderHook(() => useVacancy(4, "all"), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies/4");
    expect(urlOf(0).searchParams.get("stage")).toBe("all");
    expect(urlOf(0).searchParams.get("offset")).toBe("0");
    // Reading hasNextPage first keeps the observer tracking it, as the list test does (react-query renders only tracked fields).
    expect(result.current.hasNextPage).toBe(true);

    await act(async () => {
      await result.current.fetchNextPage();
    });

    expect(urlOf(1).searchParams.get("offset")).toBe("50");
    expect(urlOf(1).searchParams.get("stage")).toBe("all");
    await vi.waitFor(() => expect(result.current.data?.pages.length).toBe(2));
    expect(result.current.hasNextPage).toBe(false);
  });

  it("useVacancyForm asks for the saved values of vacancy 4 at its form path, and stays idle without an id", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { id: 4, title: "Нягтлан", position: 2, status: "open" }));

    const idle = renderHook(() => useVacancyForm(null), { wrapper: wrapperFor(client) });
    expect(idle.result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();

    const { result } = renderHook(() => useVacancyForm(4), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies/4/form");
    expect(result.current.data?.position).toBe(2);
  });

  it("useVacancyOptions asks for the form choices, with the vacancy only when one is given", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(200, { branches: [], departments: [], managers: [], positions: [], statuses: [] }),
    );

    const { result } = renderHook(() => useVacancyOptions(4, true), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies/options");
    expect(urlOf(0).searchParams.get("vacancy")).toBe("4");
  });

  it("useVacancyOptions stays idle while disabled", async () => {
    const { result } = renderHook(() => useVacancyOptions(null, false), { wrapper: wrapperFor(client) });

    expect(result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("useSlotLine stays idle without a position and asks the budget line once one is given", async () => {
    const idle = renderHook(() => useSlotLine({ branch: "1" }), { wrapper: wrapperFor(client) });
    expect(idle.result.current.fetchStatus).toBe("idle");
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValue(jsonResponse(200, { numbers: "2 / 1", warning: "" }));
    const { result } = renderHook(() => useSlotLine({ position: "3", headcount: "x" }), {
      wrapper: wrapperFor(client),
    });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies/slot-line");
    expect(urlOf(0).searchParams.get("position")).toBe("3");
    expect(urlOf(0).searchParams.get("headcount")).toBe("x");
  });

  it("useCandidate asks for candidate 12 at its path", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, CANDIDATE));

    const { result } = renderHook(() => useCandidate(12), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12");
  });

  it("useCandidate fails with 404 when the candidate is not visible (the not-found state)", async () => {
    fetchMock.mockResolvedValue(jsonResponse(404, { field_errors: {}, form_errors: ["no"] }));

    const { result } = renderHook(() => useCandidate(12), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isError).toBe(true));

    expect((result.current.error as ApiFailure).status).toBe(404);
  });

  it("usePurgePage asks for the purge list at /api/v1/recruitment/purge", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { is_admin: true, months: 12, rows: [] }));

    const { result } = renderHook(() => usePurgePage(), { wrapper: wrapperFor(client) });
    await vi.waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/purge");
  });

  it("candidateFileUrl gives the plain download link of a file", () => {
    expect(candidateFileUrl(7)).toBe("/api/v1/recruitment/files/7");
  });

  it("useSaveVacancy with no id creates a vacancy at /vacancies and refreshes recruitment, attention and nav on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...OK, id: 4 }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveVacancy(null), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(VACANCY_FORM));

    expect(saved).toMatchObject({ ok: true, id: 4 });
    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies");
    expect((fetchMock.mock.calls[0][0] as Request).method).toBe("POST");
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useSaveVacancy with an id posts the edit to /vacancies/{pk} and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveVacancy(4), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ ...VACANCY_FORM, status: "open" }));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies/4");
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("a vacancy write that answers ok false invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useSaveVacancy(4), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ ...VACANCY_FORM, status: "open" }));

    expect(saved.ok).toBe(false);
    expect(spy).not.toHaveBeenCalled();
  });

  it("useAddCandidate posts the candidate to /vacancies/{pk}/candidates and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useAddCandidate(4), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync(CANDIDATE_FORM));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/vacancies/4/candidates");
    const sent = await (fetchMock.mock.calls[0][0] as Request).json();
    expect(sent.surname).toBe("Бат");
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useMoveCandidate posts the target stage to /candidates/{pk}/move", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));

    const { result } = renderHook(() => useMoveCandidate(12), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ to: "interview", note: "" }));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12/move");
    const sent = await (fetchMock.mock.calls[0][0] as Request).json();
    expect(sent).toEqual({ to: "interview", note: "" });
  });

  it("useRejectCandidate posts to /candidates/{pk}/reject and a refusal invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, REFUSED));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useRejectCandidate(12), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync({ reason: "Буруу", withdrawn: false }));

    expect(saved.ok).toBe(false);
    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12/reject");
    expect(spy).not.toHaveBeenCalled();
  });

  it("useReopenCandidate posts to /candidates/{pk}/reopen and refreshes on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useReopenCandidate(12), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync());

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12/reopen");
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useCommentCandidate posts the text to /candidates/{pk}/comment", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, OK));

    const { result } = renderHook(() => useCommentCandidate(12), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync({ text: "Сайн" }));

    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12/comment");
    const sent = await (fetchMock.mock.calls[0][0] as Request).json();
    expect(sent).toEqual({ text: "Сайн" });
  });

  it("useUploadCandidateFile posts multipart/form-data with the file part and no Content-Type set by hand", async () => {
    setCsrf("tok");
    fetchMock.mockResolvedValue(jsonResponse(200, OK));
    // The file is checked where it is appended to the FormData (see hire.test.tsx for the reason).
    const append = vi.spyOn(FormData.prototype, "append");
    const file = new File(["cv"], "cv.pdf", { type: "application/pdf" });

    const { result } = renderHook(() => useUploadCandidateFile(12), { wrapper: wrapperFor(client) });
    await act(() => result.current.mutateAsync(file));

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.method).toBe("POST");
    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12/files");
    expect(request.headers.get("X-CSRFToken")).toBe("tok");
    expect(request.headers.get("content-type")).toMatch(/^multipart\/form-data/);
    expect(append).toHaveBeenCalledWith("file", file);
  });

  it("useUploadCandidateFile with no file sends no file part and returns the refusal", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ...REFUSED, form_errors: ["Файл сонгоно уу"] }));
    const append = vi.spyOn(FormData.prototype, "append");

    const { result } = renderHook(() => useUploadCandidateFile(12), { wrapper: wrapperFor(client) });
    const saved = await act(() => result.current.mutateAsync(null));

    expect(saved.ok).toBe(false);
    expect(append).not.toHaveBeenCalledWith("file", expect.anything());
  });

  it("useConvertCandidate returns the path to the hire form on ok true and refreshes on it", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, error: "", path: "/employees/new/?candidate=12" }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useConvertCandidate(12), { wrapper: wrapperFor(client) });
    const converted = await act(() => result.current.mutateAsync());

    expect(converted.path).toBe("/employees/new/?candidate=12");
    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/candidates/12/convert");
    for (const key of WRITE_KEYS) expect(invalidatedKeys(spy)).toContainEqual(key);
  });

  it("useConvertCandidate with ok false returns the refusal text and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: false, error: "Татгалзсан", path: "" }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useConvertCandidate(12), { wrapper: wrapperFor(client) });
    const converted = await act(() => result.current.mutateAsync());

    expect(converted.error).toBe("Татгалзсан");
    expect(spy).not.toHaveBeenCalled();
  });

  it("usePurge posts to /api/v1/recruitment/purge and refreshes recruitment on ok true", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true, deleted: 3 }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => usePurge(), { wrapper: wrapperFor(client) });
    const purged = await act(() => result.current.mutateAsync());

    expect(purged.deleted).toBe(3);
    expect(urlOf(0).pathname).toBe("/api/v1/recruitment/purge");
    expect(invalidatedKeys(spy)).toContainEqual({ queryKey: ["recruitment"] });
  });

  it("a write refused with 403 rejects with the status and invalidates nothing", async () => {
    fetchMock.mockResolvedValue(jsonResponse(403, { field_errors: {}, form_errors: ["no"] }));
    const spy = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => useMoveCandidate(12), { wrapper: wrapperFor(client) });
    const caught = await rejectionOf(() => result.current.mutateAsync({ to: "interview", note: "" }));

    expect((caught as ApiFailure).status).toBe(403);
    expect(spy).not.toHaveBeenCalled();
  });
});
