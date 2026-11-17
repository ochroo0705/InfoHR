import type { Meta, StoryObj } from "@storybook/react";
import { Modal } from "./Modal";

// Template for every component story (button.stories.tsx): default, error, long Mongolian text, dark. A pop-up has no
// loading state of its own (its buttons belong to the form inside it), so «Dirty» (typed input, asks before closing)
// stands in for it.
const meta: Meta<typeof Modal> = {
  title: "UI/Modal",
  component: Modal,
  args: {
    open: true,
    onClose: () => {},
    title: "Ажилтны мэдээлэл",
    children: <p className="text-sm text-slate-600">Талбарууд энд орно.</p>,
  },
};

export default meta;

type Story = StoryObj<typeof meta>;

export const Default: Story = {};

export const Dirty: Story = {
  args: {
    dirty: true,
  },
};

export const ServerError: Story = {
  args: {
    serverErrors: { field_errors: { last_name: ["Заавал бөглөнө"] } },
  },
};

export const LongMongolian: Story = {
  args: {
    title: "Ажилтны гэр бүлийн гишүүний мэдээллийг шинээр бүртгэх, засварлах хэсэг",
    children: (
      <p className="text-sm text-slate-600">
        Ажилтны гэр бүлийн гишүүдийн нэр, төрсөн огноо, хамаарал зэрэг мэдээллийг энд оруулж хадгалах боломжтой.
      </p>
    ),
  },
};

export const Dark: Story = {
  parameters: {
    theme: "dark",
  },
};
