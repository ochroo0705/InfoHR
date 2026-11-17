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

  it("sets the motion durations", () => {
    const value = (name: string) => tokenProps.find((t) => t.name === name)?.value;
    expect(value("--dur-in")).toBe("180ms");
    expect(value("--dur-hover")).toBe("120ms");
    expect(value("--dur-out")).toBe("140ms");
  });
});
