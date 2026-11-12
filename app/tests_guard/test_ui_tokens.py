"""Guards for the selection and motion tokens in static/css/input.css (plan 2026-11-08-selection-motion, task 1).

Plain file reads and arithmetic: no database, no Django fixtures that touch the DB.
"""

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[1] / "static/css/input.css"
PICK_NAMES = ["bright", "tint", "edge", "ink"]
MOTION_NAMES = ["dur-hover", "dur-in", "dur-out", "ease-out", "ease-in"]


def _css() -> str:
    return CSS.read_text(encoding="utf-8")


def _theme_block(css: str) -> str:
    m = re.search(r"@theme\s*\{([^}]*)\}", css)
    assert m, "@theme block not found in input.css"
    return m.group(1)


def _dark_block(css: str) -> str:
    m = re.search(r':root\[data-theme="dark"\]\s*\{([^}]*)\}', css)
    assert m, 'the :root[data-theme="dark"] variable block not found in input.css'
    return m.group(1)


def _root_block(css: str) -> str:
    m = re.search(r":root\s*\{([^}]*)\}", css)
    assert m, "a plain :root block (motion variables) not found in input.css"
    return m.group(1)


def _colour(block: str, name: str) -> str:
    """The value of --color-<name> as #rrggbb (a 3-digit #fff is expanded)."""
    m = re.search(rf"--color-{name}:\s*#([0-9a-fA-F]{{3}}|[0-9a-fA-F]{{6}})\s*;", block)
    assert m, f"--color-{name} with a hex value not found"
    digits = m.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits


def _lum(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = []
    for i in (0, 2, 4):
        c = int(h[i : i + 2], 16) / 255
        channels.append(c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast(hex_a: str, hex_b: str) -> float:
    """WCAG 2.x contrast ratio between two #rrggbb colours (1.0 to 21.0)."""
    hi, lo = sorted([_lum(hex_a), _lum(hex_b)], reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_pick_tokens_in_light_and_dark() -> None:
    css = _css()
    light = _theme_block(css)
    dark = _dark_block(css)
    for name in PICK_NAMES:
        assert re.search(rf"--color-pick-{name}:", light), f"--color-pick-{name} missing from @theme"
        assert re.search(rf"--color-pick-{name}:", dark), f"--color-pick-{name} missing from the dark block"


def test_pick_contrast_light() -> None:
    css = _css()
    light = _theme_block(css)
    bright = _colour(light, "pick-bright")
    tint = _colour(light, "pick-tint")
    edge = _colour(light, "pick-edge")
    ink = _colour(light, "pick-ink")
    surface = _colour(light, "surface")
    assert contrast(ink, bright) >= 4.5, "ink on bright pick colour must be at least 4.5:1"
    assert contrast(edge, surface) >= 3, "edge on white surface must be at least 3:1"
    assert contrast(edge, tint) >= 4.5, "edge text on tint must be at least 4.5:1"


def test_pick_contrast_dark() -> None:
    css = _css()
    dark = _dark_block(css)
    bright = _colour(dark, "pick-bright")
    tint = _colour(dark, "pick-tint")
    edge = _colour(dark, "pick-edge")
    ink = _colour(dark, "pick-ink")
    surface = _colour(dark, "surface")
    assert surface.lower() == "#1e2b38", "dark surface is expected to be #1e2b38"
    assert contrast(ink, bright) >= 4.5, "ink on bright pick colour must be at least 4.5:1 in dark"
    assert contrast(bright, tint) >= 4.5, "bright pick text on dark tint must be at least 4.5:1"
    assert contrast(edge, surface) >= 3, "edge on dark surface must be at least 3:1"
    assert contrast(edge, tint) >= 3, "edge on dark tint must be at least 3:1"


def test_motion_vars_defined() -> None:
    css = _css()
    root = _root_block(css)
    for name in MOTION_NAMES:
        assert re.search(rf"--{name}:", root), f"--{name} missing from the :root block"
    durations = re.findall(r"--dur-[\w-]+:\s*(\d+)ms", root)
    assert durations, "the --dur-* variables must be given in ms"
    for value in durations:
        assert int(value) <= 300, f"a --dur-* variable is {value} ms; motion must not exceed 300 ms"
    fallback = re.search(r"var FALLBACK_MS = (\d+);", MOTION_JS.read_text(encoding="utf-8"))
    assert fallback, "FALLBACK_MS must be a number in motion.js"
    assert int(fallback.group(1)) <= 300, "FALLBACK_MS must not exceed 300 ms"


JS = Path(__file__).resolve().parents[1] / "static/js/report_select.js"


def test_picked_row_class_in_report_select_js() -> None:
    js = JS.read_text(encoding="utf-8")
    assert "classList.toggle(PICKED_CLASS" in js, "paintRow must toggle PICKED_CLASS on the row"
    assert "bg-violet-50" not in js, "report_select.js must not paint picked rows with bg-violet-50"


def _outside_layers(css: str) -> str:
    """The stylesheet with every @layer block removed (brace-matched), so only unlayered rules remain."""
    out = []
    i = 0
    while True:
        m = re.search(r"@layer\s+[\w-]+\s*\{", css[i:])
        if not m:
            out.append(css[i:])
            break
        out.append(css[i : i + m.start()])
        depth = 0
        j = i + m.end() - 1
        while True:
            if css[j] == "{":
                depth += 1
            elif css[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        i = j + 1
    return "".join(out)


def test_is_picked_css_rules() -> None:
    css = _css()
    assert re.search(r"\.is-picked\s*\{", css), ".is-picked rule missing from input.css"
    assert re.search(r':root\[data-theme="dark"\]\s+\.is-picked\s*\{', css), (
        "the dark-theme .is-picked rule is missing from input.css"
    )
    assert re.search(r"\.is-picked\s*>\s*td:first-child\s*\{", css), (
        "the .is-picked > td:first-child bar rule is missing from input.css"
    )
    unlayered = _outside_layers(css)
    assert re.search(r"\.is-picked\s*>\s*td\.bg-surface\s*\{", unlayered), (
        ".is-picked > td.bg-surface must be an unlayered rule (outside any @layer)"
    )


BASE_HTML = Path(__file__).resolve().parents[1] / "templates/base.html"


def test_motion_js_loaded_before_select_js() -> None:
    html = BASE_HTML.read_text(encoding="utf-8")
    motion = html.find("js/motion.js")
    select = html.find("js/select.js")
    assert motion != -1, "base.html must load js/motion.js (window.hrLeave)"
    assert select != -1, "base.html must load js/select.js"
    assert motion < select, "js/motion.js must come before js/select.js in base.html"


def test_leaving_rule_in_input_css() -> None:
    assert "[data-leaving]" in _css(), "input.css must style [data-leaving] (the exit helper's rule)"


MODAL_JS = Path(__file__).resolve().parents[1] / "static/js/modal.js"


def test_modal_js_exit_uses_hrleave_and_skips_leaving_shells() -> None:
    js = MODAL_JS.read_text(encoding="utf-8")
    assert "hrLeave" in js, "modal.js must play the pop-up exit through window.hrLeave (motion.js)"
    assert "[data-leaving]" in js, "modal.js must skip shells that are [data-leaving] (topShell / Escape picker)"
    assert re.search(r"function pickTopShell\(.*?data-leaving.*?\n  \}", js, re.S), (
        "pickTopShell in modal.js must skip shells with the data-leaving attribute"
    )


SELECT_JS = Path(__file__).resolve().parents[1] / "static/js/select.js"
DATEPICKER_JS = Path(__file__).resolve().parents[1] / "static/js/datepicker.js"


def _function_body(js: str, name: str) -> str:
    """The text of `function <name>() { ... }` (brace-matched)."""
    m = re.search(rf"function {name}\(\)\s*\{{", js)
    assert m, f"function {name}() not found"
    depth = 0
    for j in range(m.end() - 1, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[m.start() : j + 1]
    raise AssertionError(f"function {name}() is not closed")


def _assert_close_leaves(path: Path) -> None:
    body = _function_body(path.read_text(encoding="utf-8"), "close")
    assert "hrLeave(" in body, f"{path.name}: close() must call hrLeave (the exit animation)"
    clear = body.find("popup = null")
    if clear == -1:
        clear = body.find("popup = current = null")
    assert clear != -1, f"{path.name}: close() must clear the popup variable"
    assert clear < body.find("hrLeave("), f"{path.name}: close() must clear state before calling hrLeave"


def test_select_close_leaves_through_hrleave_after_clearing_state() -> None:
    _assert_close_leaves(SELECT_JS)


def test_datepicker_close_leaves_through_hrleave_after_clearing_state() -> None:
    _assert_close_leaves(DATEPICKER_JS)


def test_picker_selected_states_use_pick_tokens() -> None:
    css = _css()
    assert re.search(r"\.sel-selected\s*\{[^}]*--color-pick-tint", css), (
        ".sel-selected must use --color-pick-tint (lime tint background)"
    )
    assert re.search(r"\.dp-selected\b[^{}]*\{[^}]*--color-pick-bright", css), (
        ".dp-selected must use --color-pick-bright (lime fill)"
    )


def test_picker_popups_have_entry_keyframe() -> None:
    css = _css()
    assert "@keyframes hr-pop-in" in css, "the entry keyframe hr-pop-in is missing from input.css"
    assert re.search(r"\.sel-popup\b[^{}]*\{[^}]*animation:\s*hr-pop-in", css), (
        ".sel-popup must play the hr-pop-in entry animation"
    )
    assert re.search(r"\.dp-popup\b[^{}]*\{[^}]*animation:\s*hr-pop-in", css), (
        ".dp-popup must play the hr-pop-in entry animation"
    )


def test_selected_and_active_option_has_edge_ring() -> None:
    css = _css()
    assert re.search(
        r"\.sel-selected\.sel-active\s*\{[^}]*box-shadow:\s*inset 0 0 0 2px var\(--color-pick-edge\)", css
    ), (
        ".sel-selected.sel-active must show an inset 2px pick-edge ring so a keyboard-highlighted selected option "
        "is visible"
    )


NAV_JS = Path(__file__).resolve().parents[1] / "static/js/nav.js"


def _named_fn_body(js: str, name: str) -> str:
    """The text of `function <name>(<args>) { ... }` (brace-matched)."""
    m = re.search(rf"function {name}\([^)]*\)\s*\{{", js)
    assert m, f"function {name}() not found"
    depth = 0
    for j in range(m.end() - 1, len(js)):
        if js[j] == "{":
            depth += 1
        elif js[j] == "}":
            depth -= 1
            if depth == 0:
                return js[m.start() : j + 1]
    raise AssertionError(f"function {name}() is not closed")


def test_nav_menus_close_only_through_closemenu() -> None:
    js = NAV_JS.read_text(encoding="utf-8")
    body = _named_fn_body(js, "closeMenu")
    assert "hrLeaveFn(" in body, "closeMenu must play the exit through hrLeave"
    direct = len(re.findall(r"\.open\s*=\s*false", js))
    inside = len(re.findall(r"\.open\s*=\s*false", body))
    assert direct == inside, (
        "nav.js sets .open = false outside closeMenu: every menu close must go through the helper "
        "(only its done() and its no-panel / no-hrLeave fallback may set it)"
    )
    assert inside >= 1
    assert "__closing !== token" in body, "a stale done() must be ignored through the exit token"
    assert re.search(r"function reopen\(menu\)", js), "reopen(menu) must exist"
    assert re.search(r"reopen\(menu\);\s*menu\.open = true", js), (
        "the hover-in branch must reopen a leaving menu before it sets open = true"
    )


def _rules(css: str) -> list[tuple[str, str]]:
    """(selector, body) for every rule block with no nested braces, in file order (at-rule wrappers are skipped)."""
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def test_swap_in_keyframes_and_class() -> None:
    css = _css()
    assert re.search(r"@keyframes hr-swap-in\s*\{", css), "the hr-swap-in keyframes are missing from input.css"
    assert re.search(r"from\s*\{[^}]*opacity:\s*0[^}]*translateY\(6px\)", css), (
        "hr-swap-in must start at opacity 0 and 6 px below its place"
    )
    assert re.search(r"to\s*\{[^}]*opacity:\s*1[^}]*translateY\(0\)", css) or re.search(
        r"to\s*\{[^}]*opacity:\s*1[^}]*transform:\s*none", css
    ), "hr-swap-in must end at opacity 1 in its place"
    assert re.search(r"\.swap-in\s*\{[^}]*animation:\s*hr-swap-in\s+var\(--dur-in\)\s+var\(--ease-out\)", css), (
        ".swap-in must play hr-swap-in over --dur-in with --ease-out"
    )


def test_personal_menu_rules_are_gone() -> None:
    """The personal section menu (rail sub-menu, lime picked item) and the group-as-page hiding are removed: the
    topic groups are collapsible <details> now (UI_RULES §8). Replaces the lime-item rule checks."""
    css = _css()
    assert "#personal-nav" not in css, "the rail sub-menu rules must be deleted with the menu"
    assert "[data-off]" not in css, "the group-as-page hiding (data-off) is gone"
    assert "sec-flash" not in css, "the menu-click flash is gone with the menu"
    assert "data-pgroup-link" not in css, "the menu group links are gone"


def test_main_tabs_and_rail_stay_red() -> None:
    """Controller ruling: .rtab (rail copy of the main tabs) and .tab-on are navigation and stay red."""
    for selector, body in _rules(_css()):
        if re.search(r"\.(rtab|tab-on)\b", selector):
            assert "pick-" not in body, f"{selector} must not use pick-* colours (main tabs stay red)"


# --- Inline list rows (plan 2026-11-08-selection-motion, task 8) ---
ROOT = Path(__file__).resolve().parents[1]
SECTIONS_JS = ROOT / "static/js/sections.js"
MOTION_JS = ROOT / "static/js/motion.js"
INLINE_ROW = ROOT / "employees/templates/employees/_inline_row.html"
INLINE_LIST = ROOT / "employees/templates/employees/_inline_list.html"


def test_inline_row_motion_is_scoped_to_the_list_block() -> None:
    css = _css()
    assert re.search(r"@keyframes hr-row-in\s*\{\s*from\s*\{[^}]*opacity:\s*0[^}]*translateY\(-4px\)", css), (
        "hr-row-in must start at opacity 0 and 4 px up"
    )
    for selector in (r"\[data-inline-list\] \[data-inline-row\] > td", r"\[data-inline-list\] \.row-enter > td"):
        m = re.search(selector + r"\s*\{([^}]*)\}", css)
        assert m, f"the rule for {selector} is missing"
        assert "animation: hr-row-in var(--dur-in) var(--ease-out)" in m.group(1), f"{selector} must play hr-row-in"
    for selector, body in _rules(css):
        if "hr-row-in" in body:
            assert "[data-inline-list]" in selector, (
                f"hr-row-in must be scoped to the list block, not {selector.strip()}"
            )
            assert "htmx-added" not in selector and "height" not in body, "rows must not animate height or htmx-added"


def test_inline_list_block_and_row_hooks() -> None:
    lst = INLINE_LIST.read_text(encoding="utf-8")
    row = INLINE_ROW.read_text(encoding="utf-8")
    assert "data-inline-list" in lst, "the list block carries data-inline-list (the CSS scope)"
    assert 'data-row-key="{{ it.key }}"' in lst, "a normal row carries its key (sections.js row-enter)"
    assert 'data-row-key="{{ open_key }}"' in row, "the open row carries its key"
    assert "data-inline-delete" in row, "the Тийм button is marked for the delete hook"
    btn = re.search(r"<button[^>]*data-inline-delete[^>]*>", row)
    assert btn and 'hx-sync="this:drop"' in btn.group(0), "the Тийм button drops a second click while one is in flight"
    m = re.search(r"data-inline-delete[^>]*hx-swap=\"outerHTML swap:(\d+)ms\"", row)
    assert m, "the Тийм button swaps with a delay (swap:<ms>)"
    assert int(m.group(1)) == _dur_ms(_root_block(_css()), "dur-out"), "the delete swap delay must equal --dur-out"


def _dur_ms(block: str, name: str) -> int:
    m = re.search(rf"--{name}:\s*(\d+)ms\s*;", block)
    assert m, f"--{name} in ms not found"
    return int(m.group(1))


def test_inline_delete_hook_in_sections_js() -> None:
    js = SECTIONS_JS.read_text(encoding="utf-8")
    assert js.count("htmx:beforeSwap") == 1, "one shared htmx:beforeSwap listener for list swaps"
    assert "window.hrCollapse(row)" in js, "a successful delete collapses its row through hrCollapse"
    assert "window.hrDeleteRow(d)" in js, "the delete decision comes from motion.js deleteRow"
    assert "d.elt" not in js, "beforeSwap detail.elt is the swap target, never the issuing button"
    motion = MOTION_JS.read_text(encoding="utf-8")
    assert "d.requestConfig.elt" in motion, "deleteRow reads the issuing element from requestConfig.elt"
    assert "row-enter" in js, "rows a save adds are marked row-enter"
    assert "htmx-added" not in js, "list swaps do not use htmx-added (it lands on the whole block)"


def test_motion_js_hardening() -> None:
    js = MOTION_JS.read_text(encoding="utf-8")
    assert "window.hrCollapse = hrCollapse" in js, "hrCollapse is a window global"
    assert "try {" in js and "finally {" in js, "finish() clears the leaving state even when done throws"
    assert "EXIT_PROPERTIES" in js and "propertyName" in js, "transitionend counts only for opacity or transform"
    assert re.search(r"--dur-out[\s\S]{0,400}?var FALLBACK_MS = 250;", js), (
        "the comment above FALLBACK_MS must say it stays above --dur-out"
    )


# --- Assistant panel slide (plan 2026-11-08-selection-motion, task 9) ---
PALETTE_JS = ROOT / "static/js/palette.js"


def test_palette_close_starts_exit_after_focus_and_state() -> None:
    js = PALETTE_JS.read_text(encoding="utf-8")
    body = _named_fn_body(js, "closePanel")
    assert "startExit(panel, window.hrLeave" in body, "closePanel must play the panel exit through window.hrLeave"
    assert "panel.hidden = true" not in body, "closePanel must not hide the panel at once (the exit hides it)"
    exit_at = body.find("startExit(")
    assert body.find("panel.contains(document.activeElement)") < exit_at, "focus is moved before the exit starts"
    assert body.find("setFab(false)") < exit_at, "setFab(false) is called outside and before the delayed hide"
    assert body.find("saveOpen(false)") < exit_at, "saveOpen(false) is called outside and before the delayed hide"


def test_palette_exit_done_checks_token_and_hides_last() -> None:
    js = PALETTE_JS.read_text(encoding="utf-8")
    body = _named_fn_body(js, "startExit")
    assert "__closing !== token" in body, "a stale done() must be ignored through the exit token"
    assert 'removeAttribute("data-leaving")' in body and "inert = false" in body, "done clears the leaving state"
    done_at = body.find("done: function")
    assert done_at != -1, "startExit passes a done() to hrLeave"
    assert body.find("hide()", done_at) > body.find('removeAttribute("data-leaving")', done_at), (
        "the panel is hidden last, inside done"
    )


def test_palette_is_open_excludes_leaving_and_reopen_cancels_exit() -> None:
    js = PALETTE_JS.read_text(encoding="utf-8")
    assert 'hasAttribute("data-leaving")' in _named_fn_body(js, "isPanelOpen"), "isPanelOpen excludes a leaving panel"
    assert "return isPanelOpen(panel)" in _named_fn_body(js, "isOpen"), "isOpen uses isPanelOpen"
    assert "cancelExit(panel)" in _named_fn_body(js, "openPanel"), "openPanel cancels an exit in flight"


def test_assistant_slide_keyframes_and_rules() -> None:
    css = _css()
    assert "@keyframes hr-slide-in" in css, "the hr-slide-in keyframes are missing from input.css"
    assert "@keyframes hr-slide-out" in css, "the hr-slide-out keyframes are missing from input.css"
    rules = _rules(css)
    for ident in ("#assistant-panel",):
        enter = [
            i
            for i, (sel, body) in enumerate(rules)
            if ident + ":not([hidden])" in sel and "hr-slide-in var(--dur-in) var(--ease-out)" in body
        ]
        leave = [
            i
            for i, (sel, body) in enumerate(rules)
            if ident + "[data-leaving]" in sel and "hr-slide-out var(--dur-out) var(--ease-in)" in body
        ]
        assert enter, f"{ident}:not([hidden]) must slide in with hr-slide-in"
        assert leave, f"{ident}[data-leaving] must slide out with hr-slide-out"
        assert leave[-1] > enter[0], f"the {ident} exit rule must come after its entry rule (equal specificity)"


# --- Fix round 1 (task 9): no slide on page-load open ---
def test_page_load_open_does_not_slide_in() -> None:
    js = PALETTE_JS.read_text(encoding="utf-8")
    body = _named_fn_body(js, "openPanel")
    assert 'setAttribute("data-no-enter"' in body, "a page-load open (fromUser false) sets data-no-enter"
    assert 'removeAttribute("data-no-enter")' in body, "a user open removes data-no-enter"
    unhide = body.find("panel.hidden = false")
    assert unhide != -1 and body.find('removeAttribute("data-no-enter")') < unhide, (
        "data-no-enter is removed before the panel is un-hidden"
    )
    rules = _rules(_css())
    enter = [sel for sel, body_ in rules if "#assistant-panel:not([hidden])" in sel and "hr-slide-in" in body_]
    assert enter, "the enter rule for the panel must exist"
    assert ":not([data-no-enter])" in enter[0], "the enter rule skips a page-load open"
    assert ":not([data-leaving])" in enter[0], "the enter rule does not apply while the panel leaves"


# --- Task 10: page cross-fade (plan 2026-11-08-selection-motion) ---
NO_PREFERENCE_MEDIA = re.compile(r"@media\s*\(\s*prefers-reduced-motion:\s*no-preference\s*\)")


def _css_blocks(css: str) -> list[tuple[tuple[str, ...], str, str]]:
    """Every {}-block as (enclosing preludes outermost first, its own prelude, its body). Comments stripped first."""
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[tuple[tuple[str, ...], str, str]] = []
    stack: list[tuple[str, int]] = []
    start = 0
    for i, ch in enumerate(css):
        if ch == "{":
            stack.append((css[start:i].strip(), i + 1))
            start = i + 1
        elif ch == "}":
            prelude, body_start = stack.pop()
            out.append((tuple(p for p, _ in stack), prelude, css[body_start:i]))
            start = i + 1
        elif ch == ";":
            start = i + 1
    return out


def test_page_fade_is_reduced_motion_safe() -> None:
    blocks = _css_blocks(_css())
    fades = [b for b in blocks if b[1] == "@view-transition"]
    assert fades, "@view-transition { navigation: auto; } not found in input.css"
    for enclosing, _prelude, body in fades:
        assert any(NO_PREFERENCE_MEDIA.fullmatch(p) for p in enclosing), (
            "@view-transition must sit inside @media (prefers-reduced-motion: no-preference)"
        )
        assert "navigation: auto" in body, "@view-transition must set navigation: auto"
    named = [b for b in blocks if b[1] == "header.sticky" and "view-transition-name: topbar" in b[2]]
    assert named, "header.sticky must carry view-transition-name: topbar (the top bar stays still during the fade)"
    assert any(NO_PREFERENCE_MEDIA.fullmatch(p) for p in named[0][0]), (
        "the topbar name must sit inside the no-preference media block too"
    )


SWITCHER = Path(__file__).resolve().parents[1] / "reports/templates/reports/_switcher.html"


def test_switcher_current_segment_is_picked_not_violet() -> None:
    """The report view switcher marks the layout on screen with .is-picked (task 11b), not the old violet tint."""
    html = SWITCHER.read_text(encoding="utf-8")
    assert "is-picked" in html, "_switcher.html must mark the current layout segment with is-picked"
    assert "bg-violet-50" not in html, "_switcher.html must not paint the current segment with bg-violet-50"


# --- Task 12: print safety. Picked (lime) looks are screen only; print stays plain (spec: print unchanged). ---
PICK_TOKEN = re.compile(r"--color-pick-|accent-color:\s*var\(--color-pick")


def _selector_list(prelude: str) -> list[str]:
    return [" ".join(part.split()) for part in prelude.split(",") if part.strip()]


def test_picked_css_is_screen_only_or_print_neutralised() -> None:
    """Every lime rule (a plain rule whose body uses a pick-* colour, or .is-picked / td.bg-surface / a.is-picked)
    sits inside @media screen, or each of its selectors is listed in an @media print reset that uses !important."""
    blocks = _css_blocks(_css())
    lime = [
        (enclosing, sel, body)
        for enclosing, sel, body in blocks
        if not sel.startswith("@")
        # `:not(.is-picked)` styles rows that are NOT picked (hover, phone cards): not a picked rule.
        and (
            PICK_TOKEN.search(body)
            or re.search(r"\.is-picked|bg-surface|a\.is-picked", sel.replace(":not(.is-picked)", ""))
        )
    ]
    assert lime, "no picked (lime) rules found: the guard would pass vacuously"
    print_selectors: set[str] = set()
    for enclosing, sel, body in blocks:
        if any(p.startswith("@media print") for p in enclosing) and "!important" in body:
            print_selectors.update(_selector_list(sel))
    for enclosing, sel, _body in lime:
        if any(p.startswith("@media screen") for p in enclosing):
            continue
        missing = [s for s in _selector_list(sel) if s not in print_selectors]
        assert not missing, f"picked rule not screen-only and not reset for print: {missing}"


# --- Final fix wave (plan 2026-11-08-selection-motion, final review): open row, weight, popups, swap cancel. ---
INLINE_ROW = Path(__file__).resolve().parents[1] / "employees/templates/employees/_inline_row.html"
STATIC_JS = Path(__file__).resolve().parents[1] / "static/js"
DETAIL_HTML = Path(__file__).resolve().parents[1] / "employees/templates/employees/detail.html"


def test_open_inline_row_is_picked_not_violet() -> None:
    """The row opened in place in an inline list is a picked row (.is-picked), not the old violet tint."""
    html = INLINE_ROW.read_text(encoding="utf-8")
    m = re.search(r"<tr\s+data-inline-row[^>]*>", html)
    assert m, "_inline_row.html must open with the data-inline-row <tr>"
    tag = m.group(0)
    assert "is-picked" in tag.split("class=", 1)[1], "the open <tr> must carry is-picked"
    assert "bg-violet-50" not in tag, "the open <tr> must not use bg-violet-50/60 (same look as a hovered row)"
    assert "align-top" in tag, "the open <tr> keeps align-top"


def test_is_picked_rule_does_not_change_font_weight() -> None:
    """.is-picked is used on table rows; a weight change moves auto-layout columns, so the rule sets no weight."""
    css = _css()
    m = re.search(r"\.is-picked\s*\{([^}]*)\}", css)
    assert m, ".is-picked rule missing from input.css"
    assert "font-weight" not in m.group(1), ".is-picked must not set font-weight (the 3 px bar is the cue)"


def test_picked_text_inputs_keep_ink_colour() -> None:
    """Preflight makes inputs inherit text colour: inside a picked row the boxes must stay slate-800, not olive."""
    css = _css()
    m = re.search(r"\.is-picked input, \.is-picked select, \.is-picked textarea\s*\{([^}]*)\}", css)
    assert m, "the .is-picked input/select/textarea colour rule is missing from input.css"
    assert "color: var(--color-slate-800)" in m.group(1), "form boxes in a picked row use slate-800 text"
    print_block = re.search(r"@media print\s*\{", css)
    assert print_block and ".is-picked input" in css[print_block.start() :], (
        "the new .is-picked input selector must also be in the @media print reset"
    )


def test_popup_queries_skip_leaving_elements() -> None:
    """A dropdown or calendar that is fading out keeps its element: a popup query must say :not([data-leaving])."""
    call = re.compile(r"querySelector(?:All)?\(\s*(['\"`])(.*?)\1\s*\)")
    offenders = []
    for path in sorted(STATIC_JS.glob("*.js")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in call.finditer(line):
                sel = m.group(2)
                for part in re.findall(r"\.(?:sel-popup|dp-popup)\b[^,]*", sel):
                    if ":not([data-leaving])" not in part:
                        offenders.append(f"{path.name}:{lineno}: {m.group(0)}")
    assert not offenders, "popup queries must skip leaving elements:\n" + "\n".join(offenders)


def test_swap_in_is_not_used_by_the_groups() -> None:
    """Opening a personal group is a <details> toggle (one scroll, 2026-11-09): sections.js adds no swap-in class,
    so no animation can be left stuck on a hidden panel. Replaces the old animationcancel check on swapIn()."""
    text = (STATIC_JS / "sections.js").read_text(encoding="utf-8")
    assert "swap-in" not in text
    assert "swapIn" not in text
    assert "animationcancel" not in text
