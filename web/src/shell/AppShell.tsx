import { useEffect } from "react";
import { Outlet } from "react-router";
import { PageScrollbar } from "../widgets/Scrollbar";
import { TopBar } from "./TopBar";
import { watchSystem } from "./theme";

// The signed-in frame: the top bar, then the page. Every signed-in route renders its page through <Outlet/>.
// Mounted under RequireAuth in App.tsx. The main wrapper is base.html line 85.
export function AppShell() {
  // Follows the computer's light or dark setting while the theme choice is Автомат. Mounted once for the frame.
  useEffect(() => watchSystem(), []);

  return (
    <>
      <TopBar />
      <PageScrollbar />
      <div id="page">
        <main className="mx-auto max-w-6xl px-4 py-6">
          <Outlet />
        </main>
      </div>
    </>
  );
}
