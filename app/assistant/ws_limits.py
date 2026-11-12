"""Limits of the assistant workspace, in one place. Plain Python, no Django."""

PAGE_SIZE = 100  # rows the workspace page draws at a time
EXPORT_MAX_ROWS = 20000  # an export is cut at this many rows, with a visible message
EXPORT_TIMEOUT_S = 60.0  # seconds one export run may take (the page run keeps the 15 s default of sqlcore)
MAX_TABS = 20  # workspace tabs one viewer may keep
MAX_VERSIONS = 30  # saved versions kept per tab
MAX_PAGE = 10000  # the largest page number a viewer may ask for; above it the page is refused
