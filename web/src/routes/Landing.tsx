import { useEffect } from "react";
import { Navigate } from "react-router";
import { isPorted } from "../lib/ported";
import { legacyOrigin } from "../lib/AppLink";
import { useMeta } from "../shell/useMeta";

// The `/` route. A signed-in user lands on the page their account says (meta.user.landing). A ported landing is a
// client-side redirect; any other one is a full page load into Django.
export function Landing() {
  const { data } = useMeta();
  const landing = data?.user?.landing;
  const ported = landing !== undefined && isPorted(landing);

  useEffect(() => {
    if (landing === undefined || ported) return;
    window.location.replace(legacyOrigin() + landing);
  }, [landing, ported]);

  if (landing === undefined) return null;
  if (ported) return <Navigate to={landing} replace />;
  return null;
}
