import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Meta, StoryObj } from "@storybook/react";
import type { ReportingLineOut, ReportingPersonOut } from "../../api/employee";
import { ReportingLine } from "./ReportingLine";

// Template for the reporting line: default, empty, loading, error, long chain, long Mongolian text, dark.
// The hook reads the cache under ["employee", pk, "reporting-line", ""]. The story seeds that entry, so no request is
// made. The client's `enabled: false` default also stops the hook from fetching (the hook does not set `enabled`):
// the loading story stays pending, the error story is written into the cache as a failed query.
const STORY_PK = 7;

type DemoProps = {
  data?: ReportingLineOut;
  state?: "ready" | "loading" | "error";
};

function makeClient(data: ReportingLineOut | undefined, state: NonNullable<DemoProps["state"]>): QueryClient {
  const client = new QueryClient({
    defaultOptions: { queries: { enabled: false, staleTime: Infinity, retry: false } },
  });
  const key = ["employee", STORY_PK, "reporting-line", ""];
  if (state === "ready" && data) {
    client.setQueryData(key, data);
  }
  if (state === "error") {
    const query = client.getQueryCache().build(client, { queryKey: key });
    query.setState({
      ...query.state,
      status: "error",
      fetchStatus: "idle",
      error: new globalThis.Error("500"),
      errorUpdateCount: 1,
      errorUpdatedAt: Date.now(),
    });
  }
  return client;
}

// Holds the client for this story's mount, so a re-render keeps the same cache.
function Demo({ data, state = "ready" }: DemoProps) {
  const [client] = useState(() => makeClient(data, state));
  return (
    <QueryClientProvider client={client}>
      <ReportingLine pk={STORY_PK} />
    </QueryClientProvider>
  );
}

// One person as the API sends it, with the fields the tree reads and the rest filled in.
function person(
  pk: number,
  fullName: string,
  givenInitial: string,
  position: string,
  extra: Partial<ReportingPersonOut> = {},
): ReportingPersonOut {
  return {
    pk,
    full_name: fullName,
    given_initial: givenInitial,
    photo_url: "",
    photo_srcset: "",
    position,
    department: "Үйлдвэрлэл",
    work_phone: "",
    email: "",
    until: "",
    ...extra,
  };
}

const EMPLOYEE = person(STORY_PK, "Баяр С.", "БС", "Шинжээч", { department: "Санхүү" });
const DIRECT = person(2, "О. Мөнх", "ОМ", "Баг ахлагч", {
  department: "Борлуулалт",
  work_phone: "77001122",
  email: "munkh@example.mn",
  until: "2027-06-30",
});
const HEAD = person(3, "Б. Ганзориг", "БГ", "Үйл ажиллагааны захирал", {
  department: "Үйл ажиллагаа",
  work_phone: "77003344",
  email: "ganzorig@example.mn",
});
const CEO = person(4, "Д. Туяа", "ДТ", "Гүйцэтгэх захирал", {
  department: "Удирдлага",
  work_phone: "77005566",
  email: "tuya@example.mn",
});

const DEFAULT_LINE: ReportingLineOut = { day: "", employee: EMPLOYEE, levels: [DIRECT, HEAD, CEO] };

const CHAIN_OF_TWELVE: ReportingPersonOut[] = Array.from({ length: 12 }, (_, i) =>
  person(20 + i, `Удирдагч ${i + 1}`, "УД", `Түвшин ${i + 1}`),
);
const LONG_CHAIN_LINE: ReportingLineOut = { day: "", employee: EMPLOYEE, levels: CHAIN_OF_TWELVE };

// A 120-character name and a 120-character job title on the direct manager's box.
const LONG_NAME = "Сүхбаатарын Нарантуяа Дашдоржийн Оюунчимэг ".repeat(3).slice(0, 120);
const LONG_TITLE = "Ахлах мэргэжилтэн, хүний нөөцийн бодлогын хэлтсийн тэргүүлэх ажилтан, ".repeat(3).slice(0, 120);
const LONG_MONGOLIAN_LINE: ReportingLineOut = {
  day: "",
  employee: EMPLOYEE,
  levels: [person(2, LONG_NAME, "СН", LONG_TITLE, { department: "Хүний нөөц" }), HEAD, CEO],
};

const meta: Meta<typeof Demo> = {
  title: "Employee/ReportingLine",
  component: Demo,
  args: {
    data: DEFAULT_LINE,
    state: "ready",
  },
  decorators: [
    (Story) => (
      <div className="max-w-xl">
        <Story />
      </div>
    ),
  ],
};

export default meta;

type Story = StoryObj<typeof meta>;

// Collapsed to the direct manager: the two levels above sit hidden behind «Бүх шатыг харуулах · 2».
export const Default: Story = {};

// No managers above the employee: the line «Удирдлага байхгүй» and no toggle.
export const Empty: Story = {
  args: {
    data: { day: "", employee: EMPLOYEE, levels: [] },
  },
};

// The request has not answered yet: the pulse bar shows.
export const Loading: Story = {
  args: {
    state: "loading",
  },
};

// The request failed: the load error shows.
export const Error: Story = {
  args: {
    state: "error",
  },
};

// Twelve levels above the employee: the stack opens with a stagger for each level.
export const LongChain: Story = {
  args: {
    data: LONG_CHAIN_LINE,
  },
};

// A 120-character name and job title: the lines truncate and the box keeps its height.
export const LongMongolian: Story = {
  args: {
    data: LONG_MONGOLIAN_LINE,
  },
};

// The default state in dark colours.
export const Dark: Story = {
  parameters: {
    theme: "dark",
  },
};
