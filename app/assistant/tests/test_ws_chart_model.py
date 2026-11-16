"""The chart field on a workspace version (assistant charts, Task 1): add_version stores the chart JSON text, and a
version made without a chart keeps an empty string."""

from assistant.models import WorkspaceVersion
from assistant.ws_service import add_version, new_tab

BASE_SQL = "SELECT 1 AS N FROM RDB$DATABASE"


def test_add_version_stores_chart(db: None, role_user) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Диаграм")

    v = add_version(tab, "q", BASE_SQL, chart='{"type": "bar"}')

    assert WorkspaceVersion.objects.get(pk=v.pk).chart == '{"type": "bar"}'


def test_add_version_without_chart_stores_empty_string(db: None, role_user) -> None:
    user = role_user("staff")
    tab = new_tab(user, "Диаграм")

    v = add_version(tab, "q", BASE_SQL)

    assert WorkspaceVersion.objects.get(pk=v.pk).chart == ""
