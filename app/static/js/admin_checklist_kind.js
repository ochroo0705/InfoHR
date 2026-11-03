// Checklist template form: show only the options of the chosen kind (reasons for leaving, or employment types for
// joining) and do not post the hidden ones; name the date the tasks' «Хугацаа (өдөр)» is counted from.
(function () {
  var DUE = {
    offboarding: {
      label: "Сүүлийн ажлын өдрөөс (өдөр)",
      help: "Ажлаас гарах сүүлийн ажлын өдрөөс тоолно: хасах = өмнө (-3 = 3 өдрийн өмнө), 0 = тэр өдөр, эерэг = дараа.",
    },
    onboarding: {
      label: "Ажилд орсон өдрөөс (өдөр)",
      help: "Ажилд орсон өдрөөс тоолно: хасах = өмнө (-3 = 3 өдрийн өмнө), 0 = тэр өдөр, эерэг = дараа.",
    },
  };

  function syncGroups(kind) {
    document.querySelectorAll(".chk-group").forEach(function (group) {
      var on = group.dataset.kind === kind.value;
      group.hidden = !on;
      group.querySelectorAll("input").forEach(function (box) {
        box.disabled = !on;
      });
    });
  }

  function syncDueHeader(kind) {
    var text = DUE[kind.value];
    var head = document.querySelector("th.column-due_offset_days > span");
    if (!text || !head) return;
    for (var node = head.firstChild; node; node = node.nextSibling) {
      if (node.nodeType === 3 && node.textContent.trim()) {
        node.textContent = "\n" + text.label + "\n";
        break;
      }
    }
    var icon = head.querySelector("[title]");
    if (icon) icon.title = text.help;
  }

  document.addEventListener("DOMContentLoaded", function () {
    var kind = document.getElementById("id_kind");
    if (!kind) return;
    function sync() {
      syncGroups(kind);
      syncDueHeader(kind);
    }
    kind.addEventListener("change", sync);
    sync();
  });
})();
