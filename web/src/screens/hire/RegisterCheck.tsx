import { useEffect, useState } from "react";
import { checkRegister, type HireRegisterMatchOut } from "../../api/hire";
import { AppLink } from "../../lib/AppLink";

// The live register check under the register box (`employees/_register_check.html`). 400 ms after the last change of
// `value` it asks the server whether an employee already has this register number, and shows the match as a link.
// Nothing shows for no match, an empty value or a failed request. An answer that arrives after the value changed again
// is dropped (the effect's cleanup marks it stale). The span with id `register-check` stays in place, as in Django.

export const REGISTER_CHECK_DELAY_MS = 400;

export function RegisterCheck({ value }: { value: string }) {
  const [match, setMatch] = useState<HireRegisterMatchOut | null>(null);

  useEffect(() => {
    if (value.trim() === "") {
      setMatch(null);
      return;
    }
    let stale = false;
    const timer = setTimeout(() => {
      checkRegister(value)
        .then((found) => {
          if (!stale) setMatch(found);
        })
        .catch(() => {
          if (!stale) setMatch(null);
        });
    }, REGISTER_CHECK_DELAY_MS);
    return () => {
      stale = true;
      clearTimeout(timer);
    };
  }, [value]);

  return (
    <span id="register-check">
      {match ? (
        <span className="text-xs text-red-600">
          Энэ регистрийн дугаартай ажилтан аль хэдийн бүртгэлтэй:{" "}
          <AppLink className="underline" to={`/employees/${match.pk}/`}>
            {match.code} {match.full_name}
          </AppLink>
        </span>
      ) : null}
    </span>
  );
}
