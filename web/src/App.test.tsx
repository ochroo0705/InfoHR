import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import App from "./App";

// npm test runs from web/, so process.cwd() is the web/ folder.
const basePath = resolve(process.cwd(), "../app/templates/base.html");
const indexPath = resolve(process.cwd(), "index.html");

describe("App", () => {
  it("sets the document language to mn", () => {
    render(
      <MemoryRouter>
        <App />
      </MemoryRouter>,
    );
    expect(document.documentElement.lang).toBe("mn");
  });
});

describe("index.html", () => {
  it("contains the pre-paint theme snippet from base.html line 7 verbatim", () => {
    const snippet = readFileSync(basePath, "utf8").split("\n")[6];
    expect(snippet).toContain("<script>(function(){var t;");
    const index = readFileSync(indexPath, "utf8");
    expect(index).toContain(snippet);
  });
});
