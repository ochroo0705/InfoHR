import { useGSAP } from "@gsap/react";
import { useRef } from "react";
import { copy } from "../copy";
import { OrdersMock } from "../mock/OrdersMock";
import { EASE, canAnimate, gsap, registerGsap } from "../motion";
import "./hero.css";

const TITLE_LINES = [copy.hero.titleLine1, copy.hero.titleLine2];

// Each word sits in an overflow-hidden mask so it can rise into place from below its line.
// Words are split by hand (not with SplitText) so the markup is the same with or without animation.
function TitleLine({ text }: { text: string }) {
  const words = text.split(" ");
  return (
    <span className="w-hero-line">
      {words.map((word, i) => (
        <span key={i}>
          <span className="w-hero-mask">
            <span className="w-hero-word">{word}</span>
          </span>
          {i < words.length - 1 ? " " : null}
        </span>
      ))}
    </span>
  );
}

// Hero section: text on the left, the Orders mockup on the right (stacked on phones, text first).
// Static by default. Motion runs only when canAnimate(); the content is never hidden by CSS.
export function Hero() {
  const sectionRef = useRef<HTMLElement>(null);

  useGSAP(
    () => {
      if (!canAnimate()) {
        return;
      }
      const root = sectionRef.current;
      if (!root) {
        return;
      }
      const select = (selector: string) => Array.from(root.querySelectorAll<HTMLElement>(selector));
      const eyebrow = select(".w-hero-eyebrow");
      const words = select(".w-hero-word");
      const intro = select(".w-hero-lead, .w-hero-cta");
      const frame = select(".w-hero-frame");
      const rows = select('[data-anim="order-row"]');
      const preview = select('[data-anim="order-preview"]');
      const hidden = [...eyebrow, ...words, ...intro, ...frame, ...rows, ...preview];

      try {
        registerGsap();
        // Initial states are set from JavaScript, so a page without scripts still shows everything.
        gsap.set(eyebrow, { y: 16, opacity: 0 });
        gsap.set(words, { yPercent: 100 });
        gsap.set(intro, { y: 16, opacity: 0 });
        gsap.set(frame, { y: 80, opacity: 0 });
        gsap.set(rows, { x: -12, opacity: 0 });
        gsap.set(preview, { scaleY: 0.4, opacity: 0, transformOrigin: "50% 0%" });

        const tl = gsap.timeline({ defaults: { ease: EASE } });
        tl.to(eyebrow, { y: 0, opacity: 1, duration: 0.5 }, 0)
          .to(words, { yPercent: 0, duration: 0.8, stagger: 0.06 }, 0.1)
          .to(frame, { y: 0, opacity: 1, duration: 0.8 }, 0.45)
          .to(intro, { y: 0, opacity: 1, duration: 0.5, stagger: 0.08 }, 0.7)
          .to(rows, { x: 0, opacity: 1, duration: 0.35, stagger: 0.08 }, 0.8)
          .to(preview, { scaleY: 1, opacity: 1, duration: 0.4 }, 1.2);
      } catch {
        // If GSAP fails, drop the hidden states it may have set and leave the page static and visible.
        try {
          gsap.killTweensOf(hidden);
        } catch {
          // Ignored: the inline reset below is what matters.
        }
        for (const el of hidden) {
          el.style.removeProperty("transform");
          el.style.removeProperty("opacity");
          el.style.removeProperty("transform-origin");
        }
      }
    },
    { scope: sectionRef },
  );

  return (
    <section id="hero" data-tone="dark" className="w-hero" ref={sectionRef}>
      <div className="w-container w-hero-inner">
        <div className="w-hero-text">
          <p className="w-hero-eyebrow">{copy.hero.eyebrow}</p>
          <h1 className="w-hero-title">
            <TitleLine text={TITLE_LINES[0]} /> <TitleLine text={TITLE_LINES[1]} />
          </h1>
          <p className="w-hero-lead">{copy.hero.lead}</p>
          <div className="w-hero-actions">
            <a className="w-button w-hero-cta" href="#demo">
              {copy.demoCta}
            </a>
          </div>
        </div>
        <div className="w-hero-product">
          <div className="w-hero-frame">
            <OrdersMock />
          </div>
        </div>
      </div>
    </section>
  );
}
