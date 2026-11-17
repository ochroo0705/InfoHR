import { useEffect } from "react";
import { useToday } from "../../api/today";
import { AppLink } from "../../lib/AppLink";
import { Forbidden, NotFound } from "../../routes/ErrorPage";
import { AttentionBox } from "./AttentionBox";
import { Tiles } from "./Tiles";
import { TodayHeader } from "./TodayHeader";
import { TodayStrip } from "./TodayStrip";
import { ViewsBlock } from "./ViewsBlock";

// The Today page («Өнөөдөр», employees/today.html), at /employees/today/. Sections in the template's order: header
// (title and shortcuts), tiles, the Анхаарах box (forced open), the views block, the strip, the company line.
// The page keeps the default <main> width, so it does not call useMainWidth.
const PAGE_TITLE = "Өнөөдөр";

export function TodayPage() {
  const today = useToday();

  // base.html builds the title as "<block> · MACS Human Capital"; the previous title comes back on leave.
  useEffect(() => {
    const previous = document.title;
    document.title = `${PAGE_TITLE} · MACS Human Capital`;
    return () => {
      document.title = previous;
    };
  }, []);

  // The data check comes first: a failed background refetch keeps the page on screen (see the alert below).
  if (!today.data) {
    if (today.error) {
      const status = (today.error as { status?: number }).status;
      if (status === 403) return <Forbidden />;
      if (status === 404) return <NotFound />;
      return <p className="text-sm text-red-600">Мэдээлэл ачаалж чадсангүй.</p>;
    }
    // Loading shows nothing here: the shell's loading bar is the only feedback, as on the Django page.
    return null;
  }

  const data = today.data;
  return (
    <>
      {today.error ? (
        <p role="alert" className="mb-3 text-sm text-red-600">
          Мэдээлэл ачаалж чадсангүй.
        </p>
      ) : null}
      <TodayHeader data={data} />
      <Tiles data={data} />
      <AttentionBox box={data.box} forceOpen />
      {/* The views are requested only when the user may see reports (show_views); the block mounts then. */}
      {data.show_views ? <ViewsBlock /> : null}
      <TodayStrip data={data} />
      {data.company ? (
        <p className="mb-5 text-sm text-slate-700" data-today-company>
          Энэ сард орсон {data.company.hires_month} · Гарсан {data.company.leavers_month} ·{" "}
          <AppLink to="/employees/company/" className="font-medium text-violet-700 hover:underline">
            Компанийн байдал →
          </AppLink>
        </p>
      ) : null}
    </>
  );
}
