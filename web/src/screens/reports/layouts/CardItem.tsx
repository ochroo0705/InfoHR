import type { components } from "../../../api/schema";
import { AppLink } from "../../../lib/AppLink";

// One card of the cards layout (app/reports/templates/reports/layouts/_cards_batch.html): a photo or its first-letter
// tile, the title (a link that stretches over the whole card), the subtitle and the extra lines. The API sends every
// piece of text; React only lays it out, and all text is drawn as text, never as HTML.

type CardOut = components["schemas"]["ReportLayoutCardOut"];
type ExtraOut = CardOut["extras"][number];

const STRETCHED_LINK = "text-violet-700 hover:underline after:absolute after:inset-0 after:content-['']";

// The label: value lines of a card (layouts/_extras.html). A value with an href is a contact link (mailto, tel) that sits
// above the card's stretched link, so a click on it does not open the card.
export function CardExtras({ extras, className }: { extras: ExtraOut[]; className: string }) {
  return (
    <>
      {extras.map((extra, index) => (
        <p key={index} className={className}>
          <span className="text-slate-500">{extra.label}:</span>{" "}
          {extra.href ? (
            <AppLink to={extra.href} className="relative z-10 text-violet-700 hover:underline">
              {extra.text}
            </AppLink>
          ) : (
            extra.text
          )}
        </p>
      ))}
    </>
  );
}

export function CardItem({ item }: { item: CardOut }) {
  const classes = [
    "relative flex gap-3 rounded-xl border border-slate-200 bg-surface p-4 text-sm",
    item.href ? "hover:border-violet-300 hover:bg-slate-50" : "",
    item.mark,
  ];
  return (
    <article className={classes.filter(Boolean).join(" ")}>
      {item.photo_url ? (
        <img
          src={item.photo_url}
          srcSet={item.photo_srcset || undefined}
          width={72}
          height={72}
          loading="lazy"
          decoding="async"
          alt=""
          className="h-18 w-18 shrink-0 rounded-xl object-cover"
        />
      ) : item.photo_initial ? (
        <div className="flex h-18 w-18 shrink-0 items-center justify-center rounded-xl bg-violet-100 text-2xl text-violet-700">
          {item.photo_initial}
        </div>
      ) : null}
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <h2 className="line-clamp-2 font-semibold text-slate-900">
          {item.href ? (
            <AppLink to={item.href} className={STRETCHED_LINK}>
              {item.title}
            </AppLink>
          ) : (
            item.title
          )}
        </h2>
        {item.subtitle ? <p className="line-clamp-2 text-slate-500">{item.subtitle}</p> : null}
        <CardExtras extras={item.extras} className="text-slate-700" />
      </div>
    </article>
  );
}
