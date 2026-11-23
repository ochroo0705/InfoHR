import type { TodayOut } from "../../api/today";
import { AppLink, openLegacyPopup } from "../../lib/AppLink";
import { usePalettePanel } from "../../shell/palette/PalettePanelContext";

// The top of `employees/today.html`: the title row and the shortcut buttons. Classes and Mongolian text are verbatim.
const SHORTCUT_CLASS = "rounded-lg border border-slate-300 px-4 py-2 text-sm";

export function TodayHeader({ data }: { data: TodayOut }) {
  const palette = usePalettePanel();
  return (
    <>
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-xl font-semibold">Өнөөдөр</h1>
        <span className="ml-auto flex items-baseline gap-3">
          {data.has_own_page && (
            <AppLink to="/me/" className="text-xs text-violet-700 hover:underline">
              Миний хуудас →
            </AppLink>
          )}
          <span className="text-sm text-slate-500">{data.today}</span>
        </span>
      </div>

      <div data-shortcuts className="mb-4 flex flex-wrap items-center gap-2">
        {data.shortcuts.add_employee && (
          <AppLink to="/employees/new/" className={SHORTCUT_CLASS}>
            Ажилтан нэмэх
          </AppLink>
        )}
        {data.shortcuts.record_leave && (
          <button
            type="button"
            className={SHORTCUT_CLASS}
            onClick={() => openLegacyPopup("leave_add", "/employees/today/")}
          >
            Чөлөө бүртгэх
          </button>
        )}
        {data.shortcuts.orders && (
          <AppLink to="/employees/orders/" className={`inline-flex items-center gap-2 ${SHORTCUT_CLASS}`}>
            Тушаал
          </AppLink>
        )}
        <button
          type="button"
          data-palette-open
          className={SHORTCUT_CLASS}
          onClick={palette.toggle}
        >
          Хайх <kbd className="rounded border border-slate-300 px-1.5 text-xs text-slate-500">Ctrl K</kbd>
        </button>
      </div>
    </>
  );
}
