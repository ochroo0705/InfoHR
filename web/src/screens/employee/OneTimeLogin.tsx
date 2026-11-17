import { useState } from "react";

// Port of `_one_time_login.html`: the card that shows a new login's username and temporary password once, after a hire.
// The API sends the password once (OneTimeLoginOut); the page keeps it in its own state, never in the query cache.
// «Ойлголоо, хаах» removes the card for this page view, as the template removes its element.
export function OneTimeLogin({ login }: { login: { username: string; password: string } }) {
  const [hidden, setHidden] = useState(false);
  if (hidden) return null;

  return (
    <div id="one-time-login" className="mb-4 rounded-xl border-2 border-violet-500 bg-violet-50 p-4 text-sm">
      <p className="font-medium text-violet-900">Нэвтрэх эрх үүсгэгдлээ. Түр нууц үг нэг удаа харагдана.</p>
      <p className="mt-2">
        Нэвтрэх нэр: <span className="font-mono">{login.username}</span>
      </p>
      <p className="mt-1">
        Түр нууц үг:{" "}
        <span className="rounded bg-surface px-2 py-1 font-mono text-base tracking-wider select-all">{login.password}</span>
      </p>
      <p className="mt-2 text-xs text-slate-600">
        Ажилтанд өгөөд хадгалахгүй байгаарай. Ажилтан анх нэвтрэхдээ нууц үгээ солино.
      </p>
      <button type="button" onClick={() => setHidden(true)} className="mt-2 text-violet-700 hover:underline">
        Ойлголоо, хаах
      </button>
    </div>
  );
}
