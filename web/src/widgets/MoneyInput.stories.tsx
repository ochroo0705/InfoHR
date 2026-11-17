import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react";
import { MoneyInput, type MoneyInputProps } from "./MoneyInput";

// Template for every component story (DatePicker.stories.tsx): default, filled, labelled, dark.
// The story keeps the value in state, so typing shows as it would in a form.
type DemoProps = Omit<MoneyInputProps, "onChange" | "value"> & { value?: string; label?: string };

function Demo({ label = "Цалин (₮)", value: initial = "", ...rest }: DemoProps) {
  const [value, setValue] = useState(initial);
  return (
    <div className="max-w-xs space-y-1">
      <label htmlFor={rest.id} className="block text-sm">
        {label}
      </label>
      <MoneyInput {...rest} value={value} onChange={setValue} />
    </div>
  );
}

const meta: Meta<typeof Demo> = {
  title: "UI/MoneyInput",
  component: Demo,
  args: {
    id: "salary-story",
    name: "salary",
    value: "",
  },
};

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Filled: Story = {
  args: {
    value: "2500000",
  },
};

export const Labelled: Story = {
  args: {
    label: "Урамшуулал (₮)",
    value: "350000",
  },
};

export const Dark: Story = {
  parameters: {
    theme: "dark",
  },
  args: {
    value: "2500000",
  },
};
