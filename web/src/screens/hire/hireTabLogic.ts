// The pure tab logic of the hire page (`add.html`'s inline script: badges(), the first-error tab). No React here.
// The server sends the layout (which field is in which tab and section); this file only reads it.

// A tab as the hire form describes it: only the section names matter here.
export type TabLike = { key: string; sections: { names: string[] }[] };

// The fields this file reads: the name, the kind the server sends, and the required flag.
export type FieldLike = { name: string; kind: string; required: boolean };

export type TabBadge = { text: "" | "✓" | string; tone: "error" | "done" | "none" };

// Every field name of a tab, in layout order.
export function tabNames(tab: TabLike): string[] {
  return tab.sections.flatMap((section) => section.names);
}

// The names of a tab's required inputs. A checkbox never counts (add.html queries `[required]`, and a checkbox has no
// `required` attribute unless it is required; the rule here is that it never counts), and neither does the photo box
// (kind "file"), which has no value to test.
export function requiredNames(fields: FieldLike[], names: string[]): string[] {
  return names.filter((name) => {
    const field = fields.find((f) => f.name === name);
    return field !== undefined && field.required && field.kind !== "checkbox" && field.kind !== "file";
  });
}

// The badge of one tab. The error count when any field of the tab has an error (the number of messages, not of fields),
// «✓» when the tab has required inputs and none is empty, else blank. A value is empty when its trimmed text is empty.
export function tabBadge(
  section: { required: string[]; names: string[] },
  values: Record<string, string>,
  errors: Record<string, string[]>,
): TabBadge {
  const errorCount = section.names.reduce((sum, name) => sum + (errors[name]?.length ?? 0), 0);
  if (errorCount > 0) return { text: String(errorCount), tone: "error" };
  const done =
    section.required.length > 0 && section.required.every((name) => (values[name] ?? "").trim() !== "");
  if (done) return { text: "✓", tone: "done" };
  return { text: "", tone: "none" };
}

// The first tab (in tab order) that holds a field with an error, or null. It decides which tab opens after a refused
// save.
export function firstErrorTab(tabs: TabLike[], errors: Record<string, string[]>): string | null {
  const hit = tabs.find((tab) => tabNames(tab).some((name) => (errors[name]?.length ?? 0) > 0));
  return hit ? hit.key : null;
}

// The key of the tab that holds a field name, or null for a name no tab shows.
export function tabOfField(tabs: TabLike[], name: string): string | null {
  const hit = tabs.find((tab) => tabNames(tab).includes(name));
  return hit ? hit.key : null;
}
