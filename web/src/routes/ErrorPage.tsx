import { TLink } from "../lib/viewTransition";

// The error pages (app/templates/404.html and 403.html): a code, a Mongolian heading, one line and a way back to the
// home page. They render inside the shell (AppShell), so there is no assistant button (inventory X-07). They never
// show the exception text.

function ErrorView({ code, title, text }: { code: string; title: string; text: string }) {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <p className="text-sm font-semibold text-violet-700">{code}</p>
      <h1 className="mt-2 text-xl font-semibold">{title}</h1>
      <p className="mt-3 text-sm text-slate-600">{text}</p>
      <TLink to="/" className="mt-6 inline-block rounded-lg bg-violet-600 px-4 py-2 text-sm text-white hover:bg-violet-700">
        Нүүр хуудас руу буцах
      </TLink>
    </div>
  );
}

// The catch-all route (App.tsx, path "*").
export function NotFound() {
  return (
    <ErrorView
      code="404"
      title="Хуудас олдсонгүй"
      text="Хаяг буруу байна эсвэл хуудас өөр газар шилжсэн байж магадгүй."
    />
  );
}

// The 403 view. No route renders it yet; the screens that refuse a user can use it.
export function Forbidden() {
  return (
    <ErrorView
      code="403"
      title="Хандах эрх байхгүй"
      text="Энэ хуудсыг үзэх эрх танд олгогдоогүй байна. Хэрэв хэрэгтэй бол системийн админд хандана уу."
    />
  );
}
