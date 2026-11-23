import { useGSAP } from "@gsap/react";
import { useRef } from "react";
import { copy } from "../copy";
import { EASE, ScrollTrigger, canAnimate, gsap, registerGsap } from "../motion";
import "./proof.css";

const COUNT_FROM = 5;
const COUNT_TO = 500;

// Proof strip: one calm line and a large counter. The counter counts from 5 up to 500 once, when it scrolls into view.
// Static by default: the final 500 is the visible text, so nothing depends on script to read the number.
// Motion runs only when canAnimate(). The counter's text is written by GSAP; the page never hides it with CSS.
export function Proof() {
  const sectionRef = useRef<HTMLElement>(null);
  const valueRef = useRef<HTMLSpanElement>(null);

  useGSAP(
    () => {
      const root = sectionRef.current;
      const valueEl = valueRef.current;
      if (!root || !valueEl || !canAnimate()) {
        return;
      }

      let tween: gsap.core.Tween | undefined;
      let trigger: ScrollTrigger | undefined;
      const counter = { value: COUNT_FROM };
      try {
        registerGsap();
        // The tween and the trigger come first. The counter shows 5 only after both exist.
        tween = gsap.to(counter, {
          value: COUNT_TO,
          duration: 1.6,
          ease: EASE,
          snap: { value: 1 },
          paused: true,
          onUpdate: () => {
            valueEl.textContent = String(Math.round(counter.value));
          },
        });
        trigger = ScrollTrigger.create({
          trigger: root,
          start: "top 85%",
          once: true,
          animation: tween,
        });
        valueEl.textContent = String(COUNT_FROM);
      } catch {
        // If GSAP fails part-way, drop what was built and put the final number back.
        trigger?.kill(true);
        tween?.kill();
        valueEl.textContent = String(COUNT_TO);
      }
    },
    { scope: sectionRef },
  );

  return (
    <section id="proof" data-tone="dark" className="w-proof" ref={sectionRef}>
      <div className="w-container w-proof-inner">
        <p className="w-proof-line">{copy.proof.line}</p>
        <p className="w-proof-counter">
          <span className="w-proof-value" data-proof-value aria-hidden="true" ref={valueRef}>
            {String(COUNT_TO)}
          </span>
          <span className="w-proof-sr">{String(COUNT_TO)}</span>
          <span className="w-proof-label">{copy.proof.counterLabel}</span>
        </p>
      </div>
    </section>
  );
}
