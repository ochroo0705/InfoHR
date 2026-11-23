// isRelativePath: the same-site path rule the palette uses for hrefs and for the paths a row opens.
import { describe, expect, it } from "vitest";
import { isRelativePath } from "./relativePath";

describe("isRelativePath", () => {
  it("accepts a same-site path", () => {
    expect(isRelativePath("/employees/1/")).toBe(true);
  });

  it("rejects protocol-relative, backslash, scheme and absolute URLs", () => {
    expect(isRelativePath("//evil.example/x")).toBe(false);
    expect(isRelativePath("/\\evil.example")).toBe(false);
    expect(isRelativePath("javascript:alert(1)")).toBe(false);
    expect(isRelativePath("https://example.com/")).toBe(false);
  });

  it("rejects a missing path and a path with control characters", () => {
    expect(isRelativePath(null)).toBe(false);
    expect(isRelativePath(undefined)).toBe(false);
    expect(isRelativePath("/a\nb")).toBe(false);
  });
});
