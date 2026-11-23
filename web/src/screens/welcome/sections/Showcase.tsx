import { useGSAP } from "@gsap/react";
import type { ComponentType } from "react";
import { useRef } from "react";
import { copy } from "../copy";
import { AssistantMock } from "../mock/AssistantMock";
import { LeaveMock } from "../mock/LeaveMock";
import { OrdersMock } from "../mock/OrdersMock";
import { TodayMock } from "../mock/TodayMock";
import { EASE, ScrollTrigger, canAnimate, gsap, registerGsap } from "../motion";
import "./showcase.css";

type StepKey = "orders" | "leave" | "today" | "assistant";

// Same order as copy.showcase.steps: the caption at index i belongs to the mock at index i.
const STEPS: { key: StepKey; Mock: ComponentType }[] = [
  { key: "orders", Mock: OrdersMock },
  { key: "leave", Mock: LeaveMock },
  { key: "today", Mock: TodayMock },
  { key: "assistant", Mock: AssistantMock },
];

const PINNED_CLASS = "w-showcase--pinned";
// Pinned only when motion can run, the viewport is 768 px and up, and it is at least 640 px tall.
// Anything shorter gets the static stack, so a step never has to fit into less height than it needs.
const PINNED_QUERY =
  "(min-width: 768px) and (min-height: 640px) and (prefers-reduced-motion: no-preference)";
// Below 768px with motion allowed: each step reveals once as it enters the viewport.
const PHONE_QUERY = "(max-width: 767.98px) and (prefers-reduced-motion: no-preference)";

// The pinned timeline is four time units long (its progress is 0..1, so progress = time / 4). Each step holds fully
// visible on a plateau. Only short windows around the boundaries at time 1, 2 and 3 cross over:
//   outgoing: fades out from boundary - 0.28 to boundary - 0.02
//   incoming: fades in from boundary to boundary + 0.26
// The 0.02 gap between the two keeps the articles from overlapping, and the empty sliver stays as short as it can.
const STEP_COUNT = STEPS.length;
const TIMELINE_LENGTH = STEP_COUNT;
const BOUNDARIES = [1, 2, 3];
const FADE = 0.26;
const FADE_OUT_LEAD = 0.28;
const FADE_IN_LAG = 0;

// The animated parts of each mock, found by their data-anim hooks. Each hook sits in one article.
interface Targets {
  orderRows: HTMLElement[];
  orderPreview: HTMLElement[];
  leaveBars: HTMLElement[];
  todayCards: HTMLElement[];
  question: HTMLElement[];
  assistantRows: HTMLElement[];
}

function within(root: HTMLElement, selector: string): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(selector));
}

function collectTargets(root: HTMLElement): Targets {
  return {
    orderRows: within(root, '[data-anim="order-row"]'),
    orderPreview: within(root, '[data-anim="order-preview"]'),
    leaveBars: within(root, '[data-anim="leave-bar"]'),
    todayCards: within(root, '[data-anim="today-card"]'),
    question: within(root, '[data-anim="assistant-question"]'),
    assistantRows: within(root, '[data-anim="assistant-row"]'),
  };
}

function allTargets(articles: HTMLElement[], t: Targets): HTMLElement[] {
  return [
    ...articles,
    ...t.orderRows,
    ...t.orderPreview,
    ...t.leaveBars,
    ...t.todayCards,
    ...t.question,
    ...t.assistantRows,
  ];
}

// Removes the inline styles motion may have written. The static CSS and the markup are untouched.
function clearInline(elements: HTMLElement[]) {
  for (const el of elements) {
    el.style.removeProperty("transform");
    el.style.removeProperty("opacity");
    el.style.removeProperty("transform-origin");
  }
}

// Marks one step as the active one: the others are hidden from assistive technology, and the dot follows.
function setActive(articles: HTMLElement[], dots: HTMLElement[], index: number) {
  articles.forEach((article, i) => {
    if (i === index) {
      article.removeAttribute("aria-hidden");
    } else {
      article.setAttribute("aria-hidden", "true");
    }
  });
  dots.forEach((dot, i) => {
    dot.classList.toggle("is-active", i === index);
    if (i === index) {
      dot.setAttribute("aria-current", "step");
    } else {
      dot.removeAttribute("aria-current");
    }
  });
}

// The scroll progress at the middle of each step's plateau: the same resting points the snap uses.
const PLATEAU = [0.125, 0.375, 0.625, 0.875];

// Builds the scrubbed pinned timeline: only the crossfades between the four articles, nothing else.
// Every tween has both ends written out, so its start never depends on the DOM at the moment it first renders.
// Incoming tweens render immediately: as soon as the timeline exists, articles 2 to 4 are at their hidden start,
// and every later re-render (the refresh, a scroll) starts from that same state. Outgoing tweens do not render
// immediately: two outgoing tweens on one article would otherwise race over its hidden state.
// Boundary k (between step k - 1 and step k) runs inside its window: the outgoing article fades out and drifts up,
// a gap follows with nothing visible, then the incoming article rises from y 24 into place.
function buildPinnedTimeline(articles: HTMLElement[]) {
  const tl = gsap.timeline({ paused: true, defaults: { ease: EASE } });

  // The first step holds from time 0 until its fade-out starts; the last holds from its fade-in to the end.
  // The holds also make the articles' inline opacity 1 where no fade has written it yet.
  const firstHoldEnd = BOUNDARIES[0] - FADE_OUT_LEAD;
  tl.fromTo(
    articles[0],
    { opacity: 1, y: 0 },
    { opacity: 1, y: 0, duration: firstHoldEnd, immediateRender: false },
    0,
  );

  BOUNDARIES.forEach((boundary, index) => {
    const outgoing = articles[index];
    const incoming = articles[index + 1];
    tl.fromTo(
      outgoing,
      { opacity: 1, y: 0 },
      { opacity: 0, y: -24, duration: FADE, ease: "power1.in", immediateRender: false },
      boundary - FADE_OUT_LEAD,
    ).fromTo(
      incoming,
      { opacity: 0, y: 24 },
      { opacity: 1, y: 0, duration: FADE, ease: "power1.out", immediateRender: true },
      boundary + FADE_IN_LAG,
    );
  });

  const lastHoldStart = BOUNDARIES[BOUNDARIES.length - 1] + FADE_IN_LAG + FADE;
  tl.fromTo(
    articles[STEP_COUNT - 1],
    { opacity: 1, y: 0 },
    { opacity: 1, y: 0, duration: TIMELINE_LENGTH - lastHoldStart, immediateRender: false },
    lastHoldStart,
  );

  return tl;
}

// The four step micro-animations. Each is a time-based timeline, paused, played when its step becomes active and
// reset to its hidden state (progress 0) when the step becomes inactive. Not scrubbed.
// Order matches the step index: orders, leave, today, assistant.
function buildStepTimelines(t: Targets): gsap.core.Timeline[] {
  const orders = gsap
    .timeline({ paused: true, defaults: { ease: EASE } })
    .fromTo(
      t.orderRows,
      { x: -12, opacity: 0 },
      { x: 0, opacity: 1, duration: 0.45, stagger: 0.07, immediateRender: false },
      0,
    )
    .fromTo(
      t.orderPreview,
      { scaleY: 0.4, opacity: 0 },
      { scaleY: 1, opacity: 1, transformOrigin: "50% 0%", duration: 0.5, immediateRender: false },
      0.25,
    );

  const leave = gsap
    .timeline({ paused: true, defaults: { ease: EASE } })
    .fromTo(
      t.leaveBars,
      { scaleX: 0 },
      { scaleX: 1, transformOrigin: "0 50%", duration: 0.6, stagger: 0.09, immediateRender: false },
      0,
    );

  const today = gsap
    .timeline({ paused: true, defaults: { ease: EASE } })
    .fromTo(
      t.todayCards,
      { y: 16, opacity: 0 },
      { y: 0, opacity: 1, duration: 0.5, stagger: 0.12, immediateRender: false },
      0,
    );

  const assistant = gsap
    .timeline({ paused: true, defaults: { ease: EASE } })
    .fromTo(t.question, { x: 8, opacity: 0 }, { x: 0, opacity: 1, duration: 0.4, immediateRender: false }, 0)
    .fromTo(
      t.assistantRows,
      { opacity: 0 },
      { opacity: 1, duration: 0.3, stagger: 0.08, immediateRender: false },
      0.4,
    );

  return [orders, leave, today, assistant];
}

// The hidden starting states, for every step's article and micro-animation targets (the orders step included, since
// its entrance plays later). Called only after the timelines and the triggers were created without error.
function setHiddenStates(articles: HTMLElement[], t: Targets) {
  gsap.set(articles.slice(1), { opacity: 0, y: 24 });
  gsap.set(t.orderRows, { x: -12, opacity: 0 });
  gsap.set(t.orderPreview, { scaleY: 0.4, opacity: 0, transformOrigin: "50% 0%" });
  gsap.set(t.leaveBars, { scaleX: 0, transformOrigin: "0 50%" });
  gsap.set(t.todayCards, { y: 16, opacity: 0 });
  gsap.set(t.question, { x: 8, opacity: 0 });
  gsap.set(t.assistantRows, { opacity: 0 });
}

// Which step is active at this scroll progress: the number of boundaries passed. A step switches at the middle of
// each crossfade window (progress 0.25, 0.5, 0.75), where neither article is visible.
function stepAt(progress: number): number {
  if (progress < 0.25) {
    return 0;
  }
  if (progress < 0.5) {
    return 1;
  }
  if (progress < 0.75) {
    return 2;
  }
  return 3;
}

// Removes the timeline from GSAP. After its ScrollTrigger was reverted, GSAP's kill can throw while it clears the
// trigger reference; the trigger is already gone by then, so the error is ignored.
function killTimeline(timeline: gsap.core.Timeline | undefined) {
  try {
    timeline?.kill();
  } catch {
    // Ignored: see above.
  }
}

// Puts everything back to its static, fully visible state. Used when setup fails part-way.
function restoreVisible(root: HTMLElement, articles: HTMLElement[], dots: HTMLElement[], targets: HTMLElement[]) {
  try {
    gsap.killTweensOf(targets);
  } catch {
    // Ignored: the inline reset below is what matters.
  }
  clearInline(targets);
  root.classList.remove(PINNED_CLASS);
  for (const article of articles) {
    article.removeAttribute("aria-hidden");
  }
  for (const dot of dots) {
    dot.classList.remove("is-active");
    dot.removeAttribute("aria-current");
  }
}

// Showcase: four product screens, each with its caption beside it.
// Static by default (no script, reduced motion, short or narrow viewport): a vertical stack, every step fully visible.
// Pinned (768px and up, at least 640px tall, motion allowed): one sticky stage over a scroll track that swaps the steps.
// Phones with motion: each step reveals once as it enters the viewport. The static markup is complete on its own.
export function Showcase() {
  const sectionRef = useRef<HTMLElement>(null);
  // Set only while the pinned stage runs: scrolls the page to the resting point of one step. The step buttons call it.
  const goToStep = useRef<((index: number) => void) | null>(null);

  useGSAP(
    () => {
      const root = sectionRef.current;
      if (!root || !canAnimate()) {
        return;
      }
      const articles = within(root, "[data-step]");
      const dots = within(root, ".w-showcase-dot");
      // The scroll track: its height (set by CSS once the pinned class is on) is the pinned scroll distance.
      const track = root.querySelector<HTMLElement>(".w-showcase-track");
      if (articles.length !== STEPS.length || !track) {
        return;
      }

      try {
        registerGsap();
      } catch {
        // Without the plugins there is no motion; the static markup stays as it is.
        return;
      }

      const mm = gsap.matchMedia();

      mm.add(PINNED_QUERY, () => {
        let timeline: gsap.core.Timeline | undefined;
        let steps: gsap.core.Timeline[] = [];
        let trigger: ScrollTrigger | undefined;
        let entrance: ScrollTrigger | undefined;
        // The step that is active now. Only onUpdate changes it, and only when the index changes.
        let active = 0;
        const t = collectTargets(root);

        // Makes `next` the active step: aria-hidden and the dot follow, the old step's timeline is reset to its
        // hidden state, and the new step's timeline plays.
        const activate = (next: number) => {
          if (next === active) {
            return;
          }
          const previous = active;
          active = next;
          setActive(articles, dots, next);
          steps[previous]?.pause().progress(0);
          steps[next]?.restart();
        };

        try {
          // The timelines and the triggers come first. Nothing visible changes until all of them exist.
          const pinned = buildPinnedTimeline(articles);
          timeline = pinned;
          steps = buildStepTimelines(t);
          // No pin: the stage is CSS sticky inside the track, so the scroll distance is the track's own height.
          trigger = ScrollTrigger.create({
            trigger: track,
            start: "top top",
            end: "bottom bottom",
            scrub: 1,
            animation: pinned,
            // A scroll that stops between two steps glides to the nearest resting point: the middle of each plateau.
            snap: {
              snapTo: [0, 0.125, 0.375, 0.625, 0.875, 1],
              duration: { min: 0.4, max: 1 },
              delay: 0.15,
              ease: "power1.inOut",
            },
            onUpdate: (self) => activate(stepAt(self.progress)),
          });
          const created = trigger;
          goToStep.current = (index: number) => {
            const top = created.start + PLATEAU[index] * (created.end - created.start);
            window.scrollTo({ top, behavior: canAnimate() ? "smooth" : "auto" });
          };
          // Step 1 is drawn once when the showcase first reaches the viewport, before the stage sticks.
          entrance = ScrollTrigger.create({
            trigger: root,
            start: "top 75%",
            once: true,
            onEnter: () => {
              if (active === 0) {
                steps[0].restart();
              }
            },
          });
          // The class gives the track its height, so the trigger's start and end are measured again after it. The
          // refresh renders the timeline, so the hidden starting states are set after it, and the timeline is then
          // synced to the scroll.
          root.classList.add(PINNED_CLASS);
          ScrollTrigger.refresh();
          setHiddenStates(articles, t);
          setActive(articles, dots, 0);
          pinned.progress(trigger.progress);
          activate(stepAt(trigger.progress));
        } catch {
          trigger?.kill(true);
          entrance?.kill(true);
          // If ScrollTrigger.create itself threw part-way, GSAP may have left a half-built trigger on the timeline.
          // Dropping that reference keeps later reverts from calling into it.
          if (timeline) {
            (timeline as { scrollTrigger?: unknown }).scrollTrigger = undefined;
          }
          killTimeline(timeline);
          for (const step of steps) {
            killTimeline(step);
          }
          // Forget them, so the cleanup below does not kill them a second time.
          trigger = undefined;
          entrance = undefined;
          timeline = undefined;
          steps = [];
          restoreVisible(root, articles, dots, allTargets(articles, t));
        }
        return () => {
          trigger?.kill(true);
          entrance?.kill(true);
          killTimeline(timeline);
          for (const step of steps) {
            killTimeline(step);
          }
          clearInline(allTargets(articles, t));
          root.classList.remove(PINNED_CLASS);
          for (const article of articles) {
            article.removeAttribute("aria-hidden");
          }
          for (const dot of dots) {
            dot.classList.remove("is-active");
            dot.removeAttribute("aria-current");
          }
          goToStep.current = null;
        };
      });

      mm.add(PHONE_QUERY, () => {
        const reveals: { tween: gsap.core.Tween; trigger: ScrollTrigger }[] = [];
        try {
          for (const article of articles) {
            const tween = gsap.fromTo(
              article,
              { opacity: 0, y: 24 },
              { opacity: 1, y: 0, duration: 0.6, paused: true, immediateRender: false },
            );
            const trigger = ScrollTrigger.create({
              trigger: article,
              start: "top 85%",
              once: true,
              animation: tween,
            });
            reveals.push({ tween, trigger });
          }
          gsap.set(articles, { opacity: 0, y: 24 });
        } catch {
          for (const { tween, trigger } of reveals) {
            trigger.kill(true);
            tween.kill();
          }
          reveals.length = 0;
          restoreVisible(root, articles, dots, articles);
        }
        return () => {
          for (const { tween, trigger } of reveals) {
            trigger.kill(true);
            tween.kill();
          }
          clearInline(articles);
        };
      });
    },
    { scope: sectionRef },
  );

  return (
    <section id="showcase" data-tone="dark" className="w-showcase" ref={sectionRef}>
      {/* The track is the scroll distance; the stage is what stays on screen while the pinned mode is on. Neither
          wrapper has styles unless the pinned class is set, so the static and phone stacks are unchanged. */}
      <div className="w-showcase-track">
        <div className="w-showcase-stage">
          <div className="w-container">
            {/* Shown only while the pinned stage runs, where it is the way to jump between steps. */}
            <div className="w-showcase-indicator" role="group" aria-label={copy.showcase.stepsLabel}>
              {STEPS.map((step, index) => (
                <button
                  key={step.key}
                  type="button"
                  className="w-showcase-dot"
                  aria-label={copy.showcase.steps[index].title}
                  onClick={() => goToStep.current?.(index)}
                />
              ))}
            </div>
            <div className="w-showcase-steps">
              {STEPS.map(({ key, Mock }, index) => {
                const step = copy.showcase.steps[index];
                return (
                  <article key={key} data-step={key} className="w-showcase-step">
                    <div className="w-showcase-caption">
                      <p className="w-showcase-number">{String(index + 1).padStart(2, "0")}</p>
                      <h2 className="w-showcase-title">{step.title}</h2>
                      <p className="w-showcase-text">{step.text}</p>
                    </div>
                    <div className="w-showcase-mock">
                      <Mock />
                    </div>
                  </article>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
