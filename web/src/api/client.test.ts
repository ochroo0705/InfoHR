import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type ClientModule = typeof import("./client");

// openapi-fetch captures globalThis.fetch when createClient runs, so each test
// stubs fetch first and then loads a fresh copy of the module.
async function loadClient(): Promise<ClientModule> {
  vi.resetModules();
  return import("./client");
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("api client", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // Browsers resolve the client's relative paths (baseUrl "") against the
    // page; Node's Request does not, so resolve them the same way here.
    const NativeRequest = globalThis.Request;
    vi.stubGlobal(
      "Request",
      class extends NativeRequest {
        constructor(input: RequestInfo | URL, init?: RequestInit) {
          super(
            typeof input === "string" ? new URL(input, window.location.origin) : input,
            init,
          );
        }
      },
    );
    window.history.pushState({}, "", "/");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends X-CSRFToken on POST after setCsrf, but not on GET", async () => {
    const mod = await loadClient();
    fetchMock.mockImplementation(async () => jsonResponse(200, {}));

    mod.setCsrf("abc");
    expect(mod.getCsrf()).toBe("abc");

    await mod.api.POST("/api/v1/auth/logout");
    const postRequest = fetchMock.mock.calls[0][0] as Request;
    expect(postRequest.method).toBe("POST");
    expect(postRequest.headers.get("X-CSRFToken")).toBe("abc");

    await mod.api.GET("/api/v1/meta");
    const getRequest = fetchMock.mock.calls[1][0] as Request;
    expect(getRequest.method).toBe("GET");
    expect(getRequest.headers.get("X-CSRFToken")).toBeNull();
  });

  it("calls location.assign with the login URL only once for two 401 responses", async () => {
    const mod = await loadClient();
    const assignSpy = vi
      .spyOn(mod.nav, "assign")
      .mockImplementation(() => undefined);
    window.history.pushState({}, "", "/reports?q=1");
    fetchMock.mockImplementation(async () =>
      jsonResponse(401, { field_errors: {}, form_errors: [], code: "not_authenticated" }),
    );

    await mod.api.GET("/api/v1/meta");
    await mod.api.GET("/api/v1/nav");

    expect(assignSpy).toHaveBeenCalledTimes(1);
    expect(assignSpy).toHaveBeenCalledWith("/login?next=%2Freports%3Fq%3D1");
  });

  it("does not redirect on 401 when the page is already /login", async () => {
    const mod = await loadClient();
    const assignSpy = vi
      .spyOn(mod.nav, "assign")
      .mockImplementation(() => undefined);
    window.history.pushState({}, "", "/login?next=%2Freports");
    fetchMock.mockImplementation(async () =>
      jsonResponse(401, { field_errors: {}, form_errors: [], code: "not_authenticated" }),
    );

    await mod.api.GET("/api/v1/meta");

    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("omits X-CSRFToken on POST while no token is set", async () => {
    const mod = await loadClient();
    fetchMock.mockImplementation(async () => jsonResponse(200, {}));

    await mod.api.POST("/api/v1/auth/logout");

    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.headers.get("X-CSRFToken")).toBeNull();
  });

  it("assigns /password/change on 403 with code password_change_required", async () => {
    const mod = await loadClient();
    const assignSpy = vi
      .spyOn(mod.nav, "assign")
      .mockImplementation(() => undefined);
    fetchMock.mockResolvedValue(
      jsonResponse(403, {
        field_errors: {},
        form_errors: [],
        code: "password_change_required",
      }),
    );

    await mod.api.GET("/api/v1/meta");

    expect(assignSpy).toHaveBeenCalledTimes(1);
    expect(assignSpy).toHaveBeenCalledWith("/password/change");
  });

  it("does not redirect on a 403 without the password_change_required code", async () => {
    const mod = await loadClient();
    const assignSpy = vi
      .spyOn(mod.nav, "assign")
      .mockImplementation(() => undefined);
    fetchMock.mockResolvedValue(
      jsonResponse(403, { field_errors: {}, form_errors: ["no"] }),
    );

    await mod.api.GET("/api/v1/meta");

    expect(assignSpy).not.toHaveBeenCalled();
  });

  it("does not reload /password/change on a 403 password_change_required (no loop)", async () => {
    const mod = await loadClient();
    const assignSpy = vi
      .spyOn(mod.nav, "assign")
      .mockImplementation(() => undefined);
    window.history.pushState({}, "", "/password/change");
    fetchMock.mockResolvedValue(
      jsonResponse(403, {
        field_errors: {},
        form_errors: [],
        code: "password_change_required",
      }),
    );

    await mod.api.GET("/api/v1/meta");

    expect(assignSpy).not.toHaveBeenCalled();
  });
});
