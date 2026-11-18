import { useEffect, useState } from "react";
import { fetchDistricts, type HireChoiceOut } from "../../api/hire";

// One shared empty list, so `choices` keeps its identity while there are no districts (a caller can use
// [choices, loading] as effect dependencies without looping).
const NO_CHOICES: HireChoiceOut[] = [];

// The district options of the chosen city (the district select follows the city, `_district_field.html`). An empty city
// gives an empty list and makes no request. While the list of a new city loads, `choices` is the empty list and
// `loading` is true; an answer for a city the user has left is dropped. A failed request gives an empty list and
// `failed` true (the caller keeps the saved district then). Callers clear or keep the district only when `loading` is
// false (never while it is true, or a stale district could be posted), and key that effect on [choices, loading].
export function useDistricts(city: string): { choices: HireChoiceOut[]; loading: boolean; failed: boolean } {
  const [result, setResult] = useState<{ city: string; choices: HireChoiceOut[]; failed: boolean } | null>(null);

  useEffect(() => {
    if (city === "") return;
    let stale = false;
    fetchDistricts(city)
      .then((choices) => {
        if (!stale) setResult({ city, choices, failed: false });
      })
      .catch(() => {
        if (!stale) setResult({ city, choices: NO_CHOICES, failed: true });
      });
    return () => {
      stale = true;
    };
  }, [city]);

  if (city === "") return { choices: NO_CHOICES, loading: false, failed: false };
  if (result === null || result.city !== city) return { choices: NO_CHOICES, loading: true, failed: false };
  return { choices: result.choices, loading: false, failed: result.failed };
}

// The district value to keep after the city changed: the current one when the new city offers it, else "". The caller
// clears the district with this rule so a district of another city is never posted.
export function keepDistrict(current: string, choices: { value: string }[]): string {
  return choices.some((choice) => choice.value === current) ? current : "";
}
