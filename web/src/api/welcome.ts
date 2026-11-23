import { api } from "./client";
import { apiFailure } from "./mutate";

// The demo-request form's values. The API's body declares every key as required (a generator quirk), so all seven
// are always sent. `contact_ref` is the honeypot: it stays empty for a person and is sent as "" then.
export type DemoRequestInput = {
  name: string;
  email: string;
  organisation: string;
  phone: string;
  size_band: string;
  note: string;
  contact_ref: string;
};

// Public: no sign-in and no CSRF token. Resolves when the request is stored; a refusal throws an ApiFailure
// (status, fieldErrors, formErrors, code), so the form can show the server's own messages.
export async function submitDemoRequest(input: DemoRequestInput): Promise<void> {
  const { error, response } = await api.POST("/api/v1/welcome/demo-requests", { body: input });
  if (!response.ok) {
    throw apiFailure(response, error, "demo request failed");
  }
}
