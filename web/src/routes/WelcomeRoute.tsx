import { useQuery } from "@tanstack/react-query";
import { lazy, Suspense } from "react";
import { Navigate } from "react-router";
import { metaQueryOptions } from "../api/meta";

// The page is a lazy chunk, so GSAP is loaded only when someone opens /welcome.
const WelcomePage = lazy(() => import("../screens/welcome/WelcomePage"));

// The /welcome route. It shows the page only while the server's welcome_enabled flag is on. When the flag is off, or the
// meta request fails, it sends the visitor to / instead of leaving a blank page. While meta loads it renders nothing.
// retry is off here because a failed meta must redirect at once, not after React Query's default three retries (~7 s).
export function WelcomeRoute() {
  const { data, isError } = useQuery({ ...metaQueryOptions, retry: false });

  if (isError) return <Navigate to="/" replace />;
  if (!data) return null;
  if (data.welcome_enabled !== true) return <Navigate to="/" replace />;

  return (
    <Suspense fallback={null}>
      <WelcomePage />
    </Suspense>
  );
}
