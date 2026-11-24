import { useEffect, useState } from "react";
import { Outlet } from "react-router";
import { PageScrollbar } from "../widgets/Scrollbar";
import { AssistantPanel } from "./palette/AssistantPanel";
import { PalettePanelProvider } from "./palette/PalettePanelContext";
import { PalettePopups } from "./palette/PalettePopups";
import { QuickAddProvider } from "../screens/lists/QuickAddHost";
import { DEFAULT_MAIN_WIDTH, MainWidthContext } from "./mainWidth";
import { TopBar } from "./TopBar";
import { watchSystem } from "./theme";

// The signed-in frame: the top bar, then the page. Every signed-in route renders its page through <Outlet/>.
// Mounted under RequireAuth in App.tsx. The main wrapper is base.html line 85.
export function AppShell() {
  // Follows the computer's light or dark setting while the theme choice is Автомат. Mounted once for the frame.
  useEffect(() => watchSystem(), []);
  // A page may narrow the main column (useMainWidth in mainWidth.ts); null keeps the default.
  const [width, setWidth] = useState<string | null>(null);

  return (
    <MainWidthContext.Provider value={setWidth}>
      <PalettePanelProvider>
        <PalettePopups>
          <TopBar />
          <PageScrollbar />
          <div id="page">
            <main className={`mx-auto ${width ?? DEFAULT_MAIN_WIDTH} py-6`}>
              <QuickAddProvider>
                <Outlet />
              </QuickAddProvider>
            </main>
          </div>
          <AssistantPanel />
        </PalettePopups>
      </PalettePanelProvider>
    </MainWidthContext.Provider>
  );
}
