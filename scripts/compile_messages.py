"""Compile app/locale/*/LC_MESSAGES/*.po into .mo files.

Replaces `manage.py compilemessages`, which needs GNU gettext (not installed on
the Windows dev machine). Usage: python scripts/compile_messages.py
"""

import ast
import struct
from pathlib import Path

LOCALE_DIR = Path(__file__).resolve().parent.parent / "app" / "locale"


def parse_po(text: str) -> dict[str, str]:
    """Read msgid/msgstr pairs (single-line or continued strings; no plurals or contexts)."""
    messages: dict[str, str] = {}
    key: str | None = None
    current: list[str] = []
    msgid = ""

    def flush() -> None:
        nonlocal msgid
        if key == "msgid":
            msgid = "".join(current)
        elif key == "msgstr":
            value = "".join(current)
            if value:
                messages[msgid] = value

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("msgid ", "msgstr ")):
            flush()
            key, _, rest = line.partition(" ")
            current = [ast.literal_eval(rest)]
        elif line.startswith('"'):
            current.append(ast.literal_eval(line))
    flush()
    return messages


def write_mo(messages: dict[str, str], path: Path) -> None:
    """Write a GNU .mo file (same layout as CPython's Tools/i18n/msgfmt.py)."""
    keys = sorted(messages)
    ids = b"".join(k.encode() + b"\0" for k in keys)
    strs = b"".join(messages[k].encode() + b"\0" for k in keys)
    n = len(keys)
    keystart = 7 * 4 + 16 * n
    valuestart = keystart + len(ids)
    koffsets: list[int] = []
    voffsets: list[int] = []
    kpos = vpos = 0
    for k in keys:
        kb, vb = k.encode(), messages[k].encode()
        koffsets += [len(kb), keystart + kpos]
        voffsets += [len(vb), valuestart + vpos]
        kpos += len(kb) + 1
        vpos += len(vb) + 1
    header = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
    path.write_bytes(header + struct.pack(f"{2 * n}i", *koffsets) + struct.pack(f"{2 * n}i", *voffsets) + ids + strs)


def main() -> None:
    for po in sorted(LOCALE_DIR.glob("*/LC_MESSAGES/*.po")):
        messages = parse_po(po.read_text(encoding="utf-8"))
        write_mo(messages, po.with_suffix(".mo"))
        print(f"{po.relative_to(LOCALE_DIR)}: {len(messages) - ('' in messages)} messages")


if __name__ == "__main__":
    main()
