import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

// npm test runs from web/, so process.cwd() is the web/ folder.
const inputCss = readFileSync(resolve(process.cwd(), "../app/static/css/input.css"), "utf8");
const tokensCss = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf8");

const PROP = /(--[\w-]+)\s*:\s*([^;]+);/g;

type Pair = { name: string; value: string };

function block(source: string, start: string): string {
  const from = source.indexOf(start);
  if (from < 0) throw new Error(`block not found: ${start}`);
  const to = source.indexOf("\n}", from);
  return source.slice(from, to + 2);
}

function pairs(text: string): Pair[] {
  return [...text.matchAll(PROP)].map((m) => ({ name: m[1], value: m[2].trim() }));
}

const sourceProps = pairs(block(inputCss, "@theme {") + block(inputCss, "\n:root {"));
const tokenProps = pairs(tokensCss);

describe("tokens.css", () => {
  it("has every custom property of input.css @theme and the first :root block, with identical values", () => {
    expect(sourceProps.length).toBeGreaterThan(0);
    const missing = sourceProps.filter(
      (s) => !tokenProps.some((t) => t.name === s.name && t.value === s.value),
    );
    expect(missing).toEqual([]);
  });

  it("has the dark solid-fill overrides of input.css (415-421) at the top level of the @media screen block that holds the dark :root block", () => {
    // Returns the text inside the braces that open at index `open`.
    function bodyAt(source: string, open: number): string {
      let depth = 0;
      for (let i = open; i < source.length; i += 1) {
        if (source[i] === "{") depth += 1;
        else if (source[i] === "}") {
          depth -= 1;
          if (depth === 0) return source.slice(open + 1, i);
        }
      }
      throw new Error("unclosed block");
    }
    // Every rule that sits directly in `body` (not inside a nested block), as "selector { declarations }".
    function topRules(body: string): string[] {
      const css = body.replace(/\/\*[\s\S]*?\*\//g, "");
      const out: string[] = [];
      let buf = "";
      for (let i = 0; i < css.length; i += 1) {
        if (css[i] === "{") {
          const inner = bodyAt(css, i);
          out.push(`${buf.trim().replace(/\s+/g, " ")} { ${inner.trim().replace(/\s+/g, " ")} }`);
          buf = "";
          i += inner.length + 1;
        } else {
          buf += css[i];
        }
      }
      return out;
    }

    const screenBody = bodyAt(tokensCss, tokensCss.indexOf("@media screen {") + "@media screen ".length);
    const darkRoot = ':root[data-theme="dark"] {';
    const rootAt = screenBody.indexOf(darkRoot);
    expect(rootAt).toBeGreaterThanOrEqual(0);
    const darkRootBody = bodyAt(screenBody, rootAt + darkRoot.length - 1);
    expect(darkRootBody).toContain("--color-pick-edge");

    const rules = topRules(screenBody);
    for (const rule of [
      ':root[data-theme="dark"] .hover\\:bg-violet-700:hover { background-color: #b0301f; }',
      ':root[data-theme="dark"] .hover\\:bg-red-700:hover { background-color: #c13237; }',
      ':root[data-theme="dark"] :is(.bg-amber-400, .bg-amber-500) { color: #1d1606; }',
      ':root[data-theme="dark"] .bg-slate-800 { background-color: #17222d; }',
      ':root[data-theme="dark"] .bg-slate-900\\/40, :root[data-theme="dark"] .bg-black\\/40 { background-color: rgb(0 0 0 / .6); }',
    ]) {
      expect(rules).toContain(rule);
    }
  });

  it("sets the motion durations", () => {
    const value = (name: string) => tokenProps.find((t) => t.name === name)?.value;
    expect(value("--dur-in")).toBe("180ms");
    expect(value("--dur-hover")).toBe("120ms");
    expect(value("--dur-out")).toBe("140ms");
  });
});
