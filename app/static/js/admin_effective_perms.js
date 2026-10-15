/* User page in the admin: permissions that come from the ticked roles show ticked and greyed out,
   with the role names on hover, so the person's real access is visible at a glance.
   Display only: a greyed box is not sent. A permission also ticked directly on the user keeps
   that direct grant (a hidden input) and shows "+ шууд". Role map: accounts.admin.UserPermissionCheckboxes. */
(function () {
  "use strict";

  function init() {
    var source = document.getElementById("role-permissions");
    if (!source) return;
    var roles = JSON.parse(source.textContent);
    var boxes = Array.prototype.slice.call(document.querySelectorAll('input[type="checkbox"][name="user_permissions"]'));
    boxes.forEach(function (box) { box.dataset.direct = box.checked ? "1" : ""; });

    document.addEventListener("change", function (event) {
      var t = event.target;
      if (t.name === "user_permissions" && !t.disabled) t.dataset.direct = t.checked ? "1" : "";
      if (t.name === "groups" || t.name === "user_permissions") update();
    });

    function fromRoles() {
      var given = {};
      document.querySelectorAll('input[type="checkbox"][name="groups"]:checked').forEach(function (g) {
        var role = roles[g.value];
        if (!role) return;
        role.perms.forEach(function (id) { (given[id] = given[id] || []).push(role.name); });
      });
      return given;
    }

    function update() {
      var given = fromRoles();
      boxes.forEach(function (box) {
        var row = box.closest("label") || box.parentElement;
        var names = given[box.value];
        var direct = box.dataset.direct === "1";
        var keep = row.querySelector("input[data-direct-keep]");
        var mark = row.querySelector("[data-direct-mark]");
        if (names) {
          box.checked = true;
          box.disabled = true;
          row.style.opacity = "0.6";
          row.title = names.join(", ") + " бүлгээс";
          if (direct && !keep) {
            keep = document.createElement("input");
            keep.type = "hidden";
            keep.name = "user_permissions";
            keep.value = box.value;
            keep.dataset.directKeep = "1";
            row.appendChild(keep);
          }
          if (direct && !mark) {
            mark = document.createElement("span");
            mark.dataset.directMark = "1";
            mark.className = "text-xs text-primary-600";
            mark.textContent = "+ шууд";
            mark.title = "Хэрэглэгчид шууд өгсөн";
            row.appendChild(mark);
          }
        } else {
          box.disabled = false;
          box.checked = direct;
          row.style.opacity = "";
          row.title = "";
        }
        if ((!names || !direct) && keep) keep.remove();
        if ((!names || !direct) && mark) mark.remove();
      });
      document.querySelectorAll("fieldset").forEach(function (set) {
        var inSet = set.querySelectorAll('input[type="checkbox"][name="user_permissions"]');
        var count = set.querySelector("[data-perm-count]");
        if (!count || !inSet.length) return;
        var on = Array.prototype.filter.call(inSet, function (b) { return b.checked; }).length;
        count.textContent = on + "/" + inSet.length;
      });
    }

    update();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
