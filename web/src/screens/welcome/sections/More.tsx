import { useGSAP } from "@gsap/react";
import { useEffect, useRef } from "react";
import { copy } from "../copy";
import { EASE, ScrollTrigger, canAnimate, gsap, registerGsap } from "../motion";
import "./more.css";

// Removes the inline styles motion may have written. The static CSS and the markup are untouched.
function clearInline(cards: HTMLElement[]) {
  for (const card of cards) {
    card.style.removeProperty("opacity");
    card.style.removeProperty("transform");
  }
}

// "More" cards: a small grid of the other things MACS Human Capital does. Light tone.
// Static by default: every card is fully visible in the markup. Motion (one soft reveal as the grid scrolls in)
// runs only when canAnimate(). Hidden states are set from JavaScript after the trigger exists.
export function More() {
  const sectionRef = useRef<HTMLElement>(null);
  // Undoes the motion set up in the last effect run. useGSAP's revert does not clear the inline state that
  // gsap.set wrote on a paused tween's targets, so the cleanup is explicit.
  const undoRef = useRef<(() => void) | undefined>(undefined);

  useGSAP(
    () => {
      const root = sectionRef.current;
      if (!root || !canAnimate()) {
        return;
      }
      const cards = Array.from(root.querySelectorAll<HTMLElement>("[data-more-card]"));
      if (cards.length === 0) {
        return;
      }

      let tween: gsap.core.Tween | undefined;
      let trigger: ScrollTrigger | undefined;
      const undo = () => {
        trigger?.kill(true);
        tween?.kill();
        clearInline(cards);
      };
      try {
        registerGsap();
        // The tween and the trigger come first. Nothing is hidden until both exist.
        tween = gsap.fromTo(
          cards,
          { opacity: 0, y: 16 },
          { opacity: 1, y: 0, duration: 0.6, ease: EASE, stagger: 0.08, paused: true, immediateRender: false },
        );
        trigger = ScrollTrigger.create({
          trigger: root,
          start: "top 85%",
          once: true,
          animation: tween,
        });
        gsap.set(cards, { opacity: 0, y: 16 });
        undoRef.current = undo;
      } catch {
        // If GSAP fails part-way, drop what was built and leave every card visible.
        undo();
      }
    },
    { scope: sectionRef },
  );

  useEffect(() => {
    return () => {
      undoRef.current?.();
      undoRef.current = undefined;
    };
  }, []);

  return (
    <section id="more" data-tone="light" className="w-more" ref={sectionRef}>
      <div className="w-container">
        <h2 className="w-more-title">{copy.more.title}</h2>
        <ul className="w-more-grid">
          {copy.more.cards.map((card, index) => (
            <li key={`${index}-${card.title}`} className="w-more-card" data-more-card>
              <span className="w-more-index">{String(index + 1).padStart(2, "0")}</span>
              <h3 className="w-more-card-title">{card.title}</h3>
              <p className="w-more-card-text">{card.text}</p>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
