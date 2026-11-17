import { useState } from "react";
import { useLocation } from "react-router";
import { api, nav } from "../api/client";
import { cn } from "../lib/utils";
import { AppLink } from "../lib/AppLink";
import { DropMenu } from "./NavMenu";
import { NavIcon } from "./NavIcon";
import { useMeta } from "./useMeta";

// The account menu at the far right of the top bar (base.html lines 49-56). It opens on hover and on click, like the
// nav menus (nav.js). The avatar shows the first letter of the first name, else the username, in upper case (the
// template's rule: user.first_name|default:user.username|slice:":1"|upper).

const LOGOUT_ERROR = "Сервертэй холбогдож чадсангүй. Дахин оролдоно уу.";

export function UserMenu() {
  const { data: meta } = useMeta();
  const { pathname } = useLocation();
  const [logoutFailed, setLogoutFailed] = useState(false);
  const user = meta?.user;
  if (!user) return null;

  const name = user.full_name || user.username;
  const initial = (user.first_name || user.username).slice(0, 1).toUpperCase();
  const onMe = pathname === "/me/" || pathname === "/me";
  const userId = user.id;

  // Ends the session, drops this user's assistant thread (thread_store.js, key "assistant-thread-<id>"), then leaves.
  // openapi-fetch does not throw on an HTTP error, so the answer is checked. When the logout did not happen, the
  // thread is kept and the page stays, with a message in the menu.
  async function logout() {
    setLogoutFailed(false);
    try {
      const { error, response } = await api.POST("/api/v1/auth/logout");
      if (error || !response.ok) {
        setLogoutFailed(true);
        return;
      }
    } catch {
      setLogoutFailed(true);
      return;
    }
    try {
      sessionStorage.removeItem(`assistant-thread-${userId}`);
    } catch {
      // Storage blocked: nothing to clear.
    }
    nav.assign("/login");
  }

  return (
    <DropMenu
      id="ui:user"
      placement="corner"
      hover={true}
      panelWidth="w-64"
      ariaLabel={name}
      triggerClassName="gap-2 px-3 text-white/70"
      trigger={
        <>
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-white/15 text-xs font-semibold text-white">
            {initial}
          </span>
          <span className="hidden xl:inline">{name}</span>
        </>
      }
    >
      <div className="mb-1 border-b border-slate-100 px-2.5 pb-2.5 pt-1.5">
        <p className="truncate font-semibold text-slate-800">{name}</p>
        <p className="truncate text-xs text-slate-500">{user.username}</p>
      </div>
      {user.own_record ? (
        <AppLink
          to="/me/"
          aria-current={onMe ? "page" : undefined}
          className={cn(
            "flex items-center gap-3 rounded-lg px-2.5 py-2 hover:bg-slate-50",
            onMe ? "bg-violet-50 font-medium text-violet-700 hover:bg-violet-50" : "text-slate-800",
          )}
        >
          <NavIcon kind="user" />
          Миний хуудас
        </AppLink>
      ) : null}
      <AppLink
        to="/password/change"
        className="flex items-center gap-3 rounded-lg px-2.5 py-2 text-slate-800 hover:bg-slate-50"
      >
        <NavIcon kind="key" />
        Нууц үг солих
      </AppLink>
      <div className="mt-1 border-t border-slate-100 pt-1">
        <button
          type="button"
          onClick={() => void logout()}
          className="flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-left text-slate-800 hover:bg-slate-50"
        >
          <NavIcon kind="logout" />
          Гарах
        </button>
        {logoutFailed ? <p className="px-2.5 py-1.5 text-xs text-red-600">{LOGOUT_ERROR}</p> : null}
      </div>
    </DropMenu>
  );
}
