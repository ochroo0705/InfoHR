// Staff import, column mapping: the page is shown at once with the plain matches; the AI's guesses for the columns
// left empty are fetched afterwards and filled in. Only a select that is still empty is filled, and a field already
// chosen on another column is never offered twice, so nothing the user did meanwhile is overwritten.
(function () {
  const status = document.getElementById("ai-status");
  if (!status) return;
  const form = status.closest("section").closest("form");
  const text = status.querySelector("[data-ai-text]");
  const spinner = status.querySelector("[data-ai-spinner]");
  const aiField = form.querySelector('input[name="ai_cols"]');
  const BADGE =
    "shrink-0 rounded-full bg-violet-100 px-2 py-0.5 text-xs font-medium text-violet-900 ring-1 ring-inset ring-violet-300";

  function finish(message, failed) {
    if (spinner) spinner.remove();
    text.textContent = message;
    status.classList.toggle("bg-amber-50", !!failed);
    status.classList.toggle("text-amber-800", !!failed);
    status.classList.toggle("bg-violet-50", !failed);
    status.classList.toggle("text-violet-900", !failed);
  }

  function apply(suggestions) {
    const filled = [];
    Object.keys(suggestions).forEach((index) => {
      const key = suggestions[index];
      const select = form.querySelector('select[name="col_' + index + '"]');
      if (!select || select.value !== "") return;
      if (Array.from(form.querySelectorAll('select[name^="col_"]')).some((other) => other.value === key)) return;
      if (!Array.from(select.options).some((option) => option.value === key)) return;
      select.value = key;
      const badge = document.createElement("span");
      badge.className = BADGE;
      badge.title = "AI санал болгосон — шалгана уу";
      badge.textContent = "AI";
      select.insertAdjacentElement("afterend", badge);
      select.addEventListener(
        "change",
        () => {
          badge.remove();
          const kept = (aiField.value ? aiField.value.split(",") : []).filter((pair) => pair !== index + ":" + key);
          aiField.value = kept.join(",");
        },
        { once: true }
      );
      filled.push(index + ":" + key);
    });
    if (filled.length) {
      aiField.value = (aiField.value ? aiField.value.split(",") : []).concat(filled).join(",");
    }
    return filled.length;
  }

  fetch(status.dataset.url, { headers: { Accept: "application/json" }, credentials: "same-origin" })
    .then((response) => (response.ok ? response.json() : Promise.reject(new Error("status " + response.status))))
    .then((data) => {
      const count = apply(data.suggestions || {});
      finish(
        count
          ? "AI " + count + " баганыг тааруулав («AI» тэмдэгтэй). Шалгаад засна уу."
          : "AI нэмж тааруулах багана олсонгүй.",
        false
      );
    })
    .catch(() => finish("AI санал өгч чадсангүй. Үлдсэн баганыг гараар холбоно уу.", true));
})();
