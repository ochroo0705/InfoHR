/* Unfold tabs hide every tab but the first; when a form comes back with errors, open the first tab that holds one. */
(function () {
  function openErrorTab() {
    var wrappers = document.querySelectorAll(".tab-wrapper");
    for (var i = 0; i < wrappers.length; i++) {
      if (!wrappers[i].querySelector(".errorlist, .errors, [aria-invalid='true']")) continue;
      var bar = wrappers[i].parentElement && wrappers[i].parentElement.querySelector(":scope > ul");
      var links = bar ? bar.querySelectorAll("a") : [];
      if (links[i]) links[i].click();
      return;
    }
  }
  document.addEventListener("DOMContentLoaded", function () {
    setTimeout(openErrorTab, 0); // after Alpine has set up the tabs
  });
})();
