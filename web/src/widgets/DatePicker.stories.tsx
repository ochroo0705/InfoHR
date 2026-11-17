import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { DatePicker, type DatePickerProps } from "./DatePicker";

// Template for every component story (Select.stories.tsx): default, filled, month, limits, dark.
// The story keeps the value in state, so a pick shows as it would in a form.
type DemoProps = Omit<DatePickerProps, "onChange" | "value"> & { value?: string; label?: string };

function Demo({ label = "Төрсөн өдөр", value: initial = "", ...rest }: DemoProps) {
  const [value, setValue] = useState(initial);
  return (
    <div className="max-w-xs space-y-1">
      <label htmlFor={rest.id} className="block text-sm">
        {label}
      </label>
      <DatePicker {...rest} value={value} onChange={setValue} />
    </div>
  );
}

const meta: Meta<typeof Demo> = {
  title: "UI/DatePicker",
  component: Demo,
  args: {
    id: "dob-story",
    name: "dob",
    value: "",
  },
};

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Filled: Story = {
  args: {
    value: "2026-11-14",
  },
};

export const Month: Story = {
  args: {
    label: "Тайлант сар",
    mode: "month",
    value: "2026-11",
  },
};

export const Limits: Story = {
  args: {
    label: "Ажилд орсон огноо",
    min: "2026-01-01",
    max: "2026-12-31",
  },
};

export const Dark: Story = {
  parameters: {
    theme: "dark",
  },
  args: {
    value: "2026-11-14",
  },
};
