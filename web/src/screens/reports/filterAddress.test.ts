import { describe, expect, it } from "vitest";
import { clearOffset, set } from "./filterAddress";

describe("filterAddress", () => {
  it("filterAddress_set_drops_offset_and_keeps_add", () => {
    expect(set("add=a&offset=40&add=b&q=x", "branch", "3")).toBe("add=a&add=b&q=x&branch=3");
  });

  it("set replaces an existing value in place", () => {
    expect(set("branch=1&q=x", "branch", "2")).toBe("branch=2&q=x");
    expect(set("q=x&branch=1&sort=name", "branch", "2")).toBe("q=x&branch=2&sort=name");
  });

  it("set keeps a repeated key as it is", () => {
    expect(set("add=a&add=b", "q", "y")).toBe("add=a&add=b&q=y");
    expect(set("cols=name&cols=code&q=x", "state", "all")).toBe("cols=name&cols=code&q=x&state=all");
  });

  it("set with an empty value removes the parameter", () => {
    expect(set("branch=1&q=x", "branch", "")).toBe("q=x");
    expect(set("branch=1", "branch", "")).toBe("");
    expect(set("q=x", "branch", "")).toBe("q=x");
  });

  it("set leaves the encoding of the other parts untouched", () => {
    expect(set("q=a%20b+c&sort=-name", "state", "all")).toBe("q=a%20b+c&sort=-name&state=all");
  });

  it("set encodes the value it writes", () => {
    expect(set("", "q", "Бат & co")).toBe("q=" + encodeURIComponent("Бат & co"));
  });

  it("set keeps a leading question mark only when the input had one", () => {
    expect(set("?q=x", "branch", "2")).toBe("?q=x&branch=2");
    expect(set("", "branch", "2")).toBe("branch=2");
    expect(set("?", "branch", "2")).toBe("?branch=2");
  });

  it("set drops a second occurrence of the name, so it holds one value", () => {
    expect(set("branch=1&q=x&branch=4", "branch", "2")).toBe("branch=2&q=x");
  });

  it("set keeps percent-encoded parts of other names untouched", () => {
    expect(set("q=%D0%91%2C1&branch=2", "branch", "3")).toBe("q=%D0%91%2C1&branch=3");
  });

  it("clearOffset removes only offset", () => {
    expect(clearOffset("add=a&offset=40&q=x")).toBe("add=a&q=x");
    expect(clearOffset("?offset=40")).toBe("");
    expect(clearOffset("q=x&sort=name")).toBe("q=x&sort=name");
  });
});
