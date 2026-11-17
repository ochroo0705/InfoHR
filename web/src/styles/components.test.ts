import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// npm test runs from web/, so process.cwd() is the web/ folder.
const inputCss = readFileSync(resolve(process.cwd(), "../app/static/css/input.css"), "utf8");
const componentsCss = readFileSync(resolve(process.cwd(), "src/styles/components.css"), "utf8");
const appCss = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf8");

// Each ported rule is one line in input.css. Returns its declaration block, whitespace collapsed, or null if absent.
function declarations(source: string, selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const line = new RegExp(`^\\s*${escaped} \\{(.*)\\}\\s*$`, "m");
  const match = line.exec(source);
  return match ? match[1].replace(/\s+/g, " ").trim() : null;
}

const ported = [
  ".sec-title",
  ".card-hover",
  ".card-hover:hover",
  ".card-soft",
  "a.card-soft:hover",
  ".ptable.card-soft",
  ".tile-icon",
  ':root[data-theme="dark"] a.card-soft:hover',
];

describe("components.css", () => {
  it("finds every ported rule in input.css (sanity check on the parser)", () => {
    for (const selector of ported) {
      expect(declarations(inputCss, selector), selector).not.toBeNull();
    }
  });

  it("has every ported rule with the same declaration block as input.css", () => {
    for (const selector of ported) {
      expect(declarations(componentsCss, selector), selector).toBe(declarations(inputCss, selector));
    }
  });

  it("keeps the component rules in @layer components and the dark hover in @media screen", () => {
    const layerStart = componentsCss.indexOf("@layer components {");
    const screenStart = componentsCss.indexOf("@media screen {");
    expect(layerStart).toBeGreaterThanOrEqual(0);
    expect(screenStart).toBeGreaterThan(layerStart);
    expect(componentsCss.slice(layerStart, screenStart)).toContain(".card-soft {");
    expect(componentsCss.slice(screenStart)).toContain(':root[data-theme="dark"] a.card-soft:hover {');
  });

  it("is imported by app.css", () => {
    expect(appCss).toContain('@import "./components.css";');
  });
});
