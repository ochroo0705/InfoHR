import { useState } from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ClashChoice } from "./ClashChoice";

afterEach(() => {
  cleanup();
});

describe("ClashChoice", () => {
  it("shows the two radios: the typed value first, then the saved one, with Django's texts", () => {
    render(<ClashChoice name="work_phone" theirs="99112233" value="mine" onPick={() => {}} />);
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios).toHaveLength(2);
    expect(radios[0].name).toBe("resolve-work_phone");
    expect(radios[0].value).toBe("mine");
    expect(radios[0].checked).toBe(true);
    expect(radios[1].name).toBe("resolve-work_phone");
    expect(radios[1].value).toBe("theirs");
    expect(radios[1].checked).toBe(false);
    expect(screen.getByLabelText("Миний утгыг хадгалах")).toBe(radios[0]);
    expect(screen.getByLabelText("«99112233» хэвээр үлдээх")).toBe(radios[1]);
  });

  it("the group uses Django's clash classes", () => {
    const { container } = render(<ClashChoice name="work_phone" theirs="99" value="mine" onPick={() => {}} />);
    expect(container.firstElementChild?.className).toBe("mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-700");
    expect(container.querySelectorAll("label.inline-flex")).toHaveLength(2);
  });

  it("picking the saved value calls onPick(\"theirs\") and picking the typed one calls onPick(\"mine\")", () => {
    const onPick = vi.fn();
    const { rerender } = render(<ClashChoice name="work_phone" theirs="99" value="mine" onPick={onPick} />);
    fireEvent.click(screen.getByLabelText("«99» хэвээр үлдээх"));
    expect(onPick).toHaveBeenLastCalledWith("theirs");
    rerender(<ClashChoice name="work_phone" theirs="99" value="theirs" onPick={onPick} />);
    fireEvent.click(screen.getByLabelText("Миний утгыг хадгалах"));
    expect(onPick).toHaveBeenLastCalledWith("mine");
  });

  it("a small stateful pick: the checked radio follows each click", () => {
    function Host() {
      const [value, setValue] = useState<"mine" | "theirs">("mine");
      return <ClashChoice name="work_phone" theirs="99" value={value} onPick={setValue} />;
    }
    render(<Host />);
    const mine = screen.getByLabelText("Миний утгыг хадгалах") as HTMLInputElement;
    const theirs = screen.getByLabelText("«99» хэвээр үлдээх") as HTMLInputElement;
    fireEvent.click(theirs);
    expect(theirs.checked).toBe(true);
    expect(mine.checked).toBe(false);
    fireEvent.click(mine);
    expect(mine.checked).toBe(true);
    expect(theirs.checked).toBe(false);
  });
});
