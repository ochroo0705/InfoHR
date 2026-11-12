"""The HR MCP server's own text: what the HR host tells an AI client on top of the generic sqlcore text.

These strings are the client-facing contract. tests/test_contract_snapshot.py pins them;
change them only together with that test.
"""

from sqlmcp import SQL_MCP_VERSION

HR_INSTRUCTIONS = f"MACS Human Capital governed SQL, contract {SQL_MCP_VERSION}. Call describe_data before run_query."

HR_RUN_QUERY_DESCRIPTION = (
    "Run one read-only SELECT over the views that describe_data lists. Only those GOV_ views may be used. "
    "List the columns you need instead of SELECT *. Join views on their ID columns. "
    "For a head count of working employees use WORKING = 1 where the view has that column. "
    "Count people with COUNT(DISTINCT ...) when a view has one row per child or per record."
)
