/* «Сонгосныг хэвлэх» for many orders: the PDF is built in the background (employees/services/print_jobs.py).
   The user stays on the register; the badge #print-job shows «Бэлтгэж байна…» (animated), then «Бэлэн болсон» + «Нээх».
   Fewer orders than data-background-from are printed as before (the form posts to a new tab). UI_RULES §8b. */
(function () {
  var badge = document.getElementById("print-job"), form = document.getElementById("order-print-form");
  if (!badge || !form) { return; }
  var threshold = parseInt(badge.dataset.backgroundFrom, 10) || 11;
  var timer = null, ids = [], running = false;

  function show(state, message, fileUrl) {
    badge.hidden = false;
    badge.dataset.state = state;
    badge.querySelectorAll("[data-pj]").forEach(function (el) { el.hidden = el.dataset.pj !== state; });
    if (message !== undefined) { badge.querySelector("[data-pj-message]").textContent = message; }
    if (fileUrl) { badge.querySelector("[data-pj-open]").href = fileUrl; }
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } running = false; }
  function fail(message) { stop(); show("failed", message || "Бэлтгэж чадсангүй."); }
  function csrf() { var t = form.querySelector("input[name=csrfmiddlewaretoken]"); return t ? t.value : ""; }

  function poll(job) {
    fetch(job.status, { credentials: "same-origin", headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) { throw new Error("status " + r.status); } return r.json(); })
      .then(function (info) {
        if (info.state === "ready") { stop(); show("ready", undefined, job.file); }
        else if (info.state === "failed") { fail(info.message); }
      })
      .catch(function () { fail(); });
  }

  function start() {
    var body = new FormData();
    body.append("csrfmiddlewaretoken", csrf());
    ids.forEach(function (id) { body.append("ids", id); });
    running = true;
    show("running");
    fetch(badge.dataset.startUrl, { method: "POST", body: body, credentials: "same-origin" })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, json: j }; }); })
      .then(function (res) {
        if (!res.ok) { fail(res.json && res.json.error); return; }
        timer = setInterval(function () { poll(res.json); }, 1500);
        poll(res.json);
      })
      .catch(function () { fail(); });
  }

  form.addEventListener("submit", function (e) {
    var picked = Array.prototype.map.call(form.querySelectorAll("input[name=ids]"), function (i) { return i.value; });
    if (picked.length < threshold) { return; }  // few orders: the normal post opens the PDF in a new tab
    e.preventDefault();
    if (running) { return; }  // one job at a time
    ids = picked;
    start();
  });
  badge.querySelector("[data-pj-retry]").addEventListener("click", function () { if (!running) { start(); } });
  badge.querySelector("[data-pj-close]").addEventListener("click", function () { stop(); badge.hidden = true; });
})();
