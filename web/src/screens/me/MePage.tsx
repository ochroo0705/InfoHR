import { useEffect } from "react";
import { useMe, type MeOut } from "../../api/me";
import { NotFound } from "../../routes/ErrorPage";
import { useMainWidth } from "../../shell/mainWidth";
import { Balance } from "./Balance";
import { Holidays } from "./Holidays";
import { MeHeader } from "./MeHeader";
import { MyRequests } from "./MyRequests";
import { MyTasks } from "./MyTasks";
import { Notices } from "./Notices";
import { ReportingLine } from "../employee/ReportingLine";
import { Queue } from "./Queue";
import { Recorded } from "./Recorded";
import { TeamAway } from "./TeamAway";

// The My page («Миний хуудас», Django me.html), at /me/. Sections top to bottom: notices, header card, reporting line
// (the manager chain, not in me.html), then me.html's order: queue, tasks, team, holidays, leave balance, requests,
// recorded.
const PAGE_TITLE = "Миний хуудас";
// me.html: {% block main_width %}max-w-2xl px-4{% endblock %}
const MAIN_WIDTH = "max-w-2xl px-4";

export function MePage() {
  const me = useMe();

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = `${PAGE_TITLE} · MACS Human Capital`;
    return () => {
      document.title = previous;
    };
  }, []);

  // The data check comes first: a failed background refetch keeps the page on screen (see MeBody).
  if (!me.data) {
    if (me.error) {
      if ((me.error as { status?: number }).status === 404) return <NotFound />;
      return <p className="text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p>;
    }
    return null;
  }

  return <MeBody data={me.data} failed={!!me.error} />;
}

// The page body. It sets the narrow main width only when it renders, so NotFound and the error line keep the default.
function MeBody({ data, failed }: { data: MeOut; failed: boolean }) {
  useMainWidth(MAIN_WIDTH);
  return (
    <>
      {failed ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          Мэдээлэл ачаалж чадсангүй.
        </p>
      ) : null}
      <Notices notices={data.notices} />
      <MeHeader employee={data.employee} job={data.job} canRequest={data.can_request} />
      {/* The signed-in user's own chain of managers (the API allows reading one's own record). It draws its own heading. */}
      <div className="mt-6">
        <ReportingLine key={data.employee.id} pk={data.employee.id} />
      </div>
      <Queue queue={data.queue} />
      <MyTasks tasks={data.tasks} />
      <TeamAway hasTeam={data.has_team} teamAway={data.team_away} />
      <Holidays holidays={data.holidays} />
      <Balance balance={data.balance} />
      <MyRequests requests={data.requests} />
      <Recorded recorded={data.recorded} />
    </>
  );
}
