import type { Meta, StoryObj } from "@storybook/react";
import { Button } from "./button";

// Template for every component story: default, loading, disabled, long Mongolian text, dark.
const meta: Meta<typeof Button> = {
  title: "UI/Button",
  component: Button,
  args: {
    children: "Хадгалах",
  },
};

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Loading: Story = {
  args: {
    children: "Хадгалж байна…",
    disabled: true,
    "aria-busy": true,
  },
};

export const Disabled: Story = {
  args: {
    disabled: true,
  },
};

export const LongMongolian: Story = {
  args: {
    children: "Ажилтны мэдээллийг хадгалаад дараагийн алхам руу шилжих",
  },
  decorators: [
    (Story) => (
      <div style={{ width: 200 }}>
        <Story />
      </div>
    ),
  ],
};

export const Dark: Story = {
  parameters: {
    theme: "dark",
  },
};
