import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { Select, type SelectOption, type SelectProps } from "./Select";

// Template for every component story (Modal.stories.tsx): default, a long list, required, add on the spot, dark.
// The story keeps the value in state, so a pick shows as it would in a form.
const DEPARTMENTS: SelectOption[] = [
  "Хүний нөөц",
  "Санхүү",
  "Худалдаа",
  "Үйлдвэрлэл",
  "Маркетинг",
].map((label, i) => ({ value: String(i + 1), label }));

const MONTHS: SelectOption[] = Array.from({ length: 12 }, (_, i) => ({ value: String(i + 1), label: `${i + 1}-р сар` }));

type DemoProps = Omit<SelectProps, "onChange" | "value"> & { value?: string; label?: string };

function Demo({ label = "Хэлтэс", value: initial = "", ...rest }: DemoProps) {
  const [value, setValue] = useState(initial);
  return (
    <div className="max-w-xs space-y-1">
      <label htmlFor={rest.id} className="block text-sm">
        {label}
      </label>
      <Select {...rest} value={value} onChange={setValue} />
    </div>
  );
}

const meta: Meta<typeof Demo> = {
  title: "UI/Select",
  component: Demo,
  args: {
    id: "dept-story",
    name: "dept",
    options: DEPARTMENTS,
    value: "",
    onAddModal: () => {},
  },
};

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Many: Story = {
  args: {
    label: "Сар",
    options: MONTHS,
  },
};

export const Required: Story = {
  args: {
    label: "Хэлтэс (заавал)",
    required: true,
  },
};

export const AddBox: Story = {
  args: {
    label: "Албан тушаал",
    addUrl: "/api/test/add",
    canAdd: true,
    addModal: true,
  },
};

export const Dark: Story = {
  parameters: {
    theme: "dark",
  },
};
