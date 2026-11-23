import { useEffect } from "react";
import "./welcome.css";
import { DemoSection } from "./sections/DemoSection";
import { BackToTop } from "./BackToTop";
import { Faq } from "./sections/Faq";
import { Fit } from "./sections/Fit";
import { Hero } from "./sections/Hero";
import { More } from "./sections/More";
import { Showcase } from "./sections/Showcase";
import { Footer } from "./Footer";
import { copy } from "./copy";
import { canAnimate } from "./motion";
import { TopBar } from "./TopBar";

// The welcome page. welcome.css is imported here only, so the palette and layout ship inside the lazy chunk.
// Tone runs dark (hero, showcase), light (more), dark (fit), light (faq), dark (demo). Each section paints its own background, so the
// change of tone needs no extra CSS. The top bar is not sticky, so the #demo and #showcase links need no offset.
export default function WelcomePage() {
  // The page sets its own title and puts the previous one back on leaving, so the app's title is not changed.
  useEffect(() => {
    const previous = document.title;
    document.title = copy.brand;
    return () => {
      document.title = previous;
    };
  }, []);

  // Smooth in-page scrolling only when motion is allowed. It is set on the root element and restored on leaving,
  // so it does not leak into the app.
  useEffect(() => {
    if (!canAnimate()) {
      return;
    }
    const root = document.documentElement;
    const previous = root.style.scrollBehavior;
    root.style.scrollBehavior = "smooth";
    return () => {
      root.style.scrollBehavior = previous;
    };
  }, []);

  return (
    <div className="welcome">
      <TopBar />
      <main data-testid="welcome-page">
        <Hero />
        <Showcase />
        <More />
        <Fit />
        <Faq />
        <DemoSection />
      </main>
      <Footer />
      <BackToTop />
    </div>
  );
}
