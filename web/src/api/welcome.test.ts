// The test support module stubs fetch and Request; it must load before any api module (./client captures fetch).
import { describe, expect, it, beforeEach } from "vitest";
import { fetchMock, jsonResponse, rejectionOf, resetFetch } from "./testSupport";
import { submitDemoRequest, type DemoRequestInput } from "./welcome";
import type { ApiFailure } from "./mutate";

const INPUT: DemoRequestInput = {
  name: "Бат",
  email: "bat@example.mn",
  organisation: "Жишээ ХХК",
  phone: "",
  size_band: "11-50",
  note: "",
  contact_ref: "",
};

describe("welcome API", () => {
  beforeEach(() => {
    resetFetch();
  });

  it("posts all seven keys, including an empty contact_ref, and resolves on success", async () => {
    fetchMock.mockResolvedValue(jsonResponse(200, { ok: true }));

    await expect(submitDemoRequest(INPUT)).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(new URL(request.url).pathname).toBe("/api/v1/welcome/demo-requests");
    expect(request.method).toBe("POST");
    expect(await request.json()).toEqual({
      name: "Бат",
      email: "bat@example.mn",
      organisation: "Жишээ ХХК",
      phone: "",
      size_band: "11-50",
      note: "",
      contact_ref: "",
    });
  });

  it("rejects a 400 with the status and the field errors from the body", async () => {
    fetchMock.mockResolvedValue(jsonResponse(400, { field_errors: { email: ["x"] }, form_errors: [] }));

    const caught = (await rejectionOf(() => submitDemoRequest(INPUT))) as ApiFailure;

    expect(caught).toBeInstanceOf(Error);
    expect(caught.message).toBe("demo request failed");
    expect(caught.status).toBe(400);
    expect(caught.fieldErrors.email).toEqual(["x"]);
  });

  it("rejects a 429 with the rate_limited code and its form errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(429, { form_errors: ["Хэт олон удаа оролдлоо."], code: "rate_limited" }),
    );

    const caught = (await rejectionOf(() => submitDemoRequest(INPUT))) as ApiFailure;

    expect(caught.status).toBe(429);
    expect(caught.code).toBe("rate_limited");
    expect(caught.formErrors).toEqual(["Хэт олон удаа оролдлоо."]);
  });
});
