import type { Meta, StoryObj } from "@storybook/react";
import { useEffect } from "react";
import { ConfirmProvider, confirm, type ConfirmOptions } from "./confirm";

// Shows the in-app confirm as soon as the story renders. Template: button.stories.tsx (default, long Mongolian text,
// dark, plus the custom-label variant). A confirm has no loading or error state of its own.
function AskOnMount({ message, opts }: { message: string; opts?: ConfirmOptions }) {
  useEffect(() => {
    void confirm(message, opts);
  }, [message, opts]);
  return null;
}

const meta: Meta<typeof AskOnMount> = {
  title: "UI/Confirm",
  component: AskOnMount,
  args: {
    message: "Хадгалах уу?",
  },
  decorators: [
    (Story) => (
      <ConfirmProvider>
        <Story />
      </ConfirmProvider>
    ),
  ],
};

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const CustomLabels: Story = {
  args: {
    message: "Хаах уу?",
    opts: { ok: "Хаах", cancel: "Үргэлжлүүлэх" },
  },
};

export const LongMongolian: Story = {
  args: {
    message: "Оруулсан мэдээлэл хадгалагдахгүй. Ажилтны гэр бүлийн мэдээллийг хаах уу?",
  },
};

export const Dark: Story = {
  args: {
    message: "Хадгалах уу?",
  },
  parameters: {
    theme: "dark",
  },
};
