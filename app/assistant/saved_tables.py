"""Who may see and delete a saved workspace table (saved tables Task 1)."""

from accounts.models import User
from django.db.models import Q, QuerySet

from .models import SavedTable


def visible_to(user: User) -> QuerySet[SavedTable]:
    """Shared tables, and the user's own private ones, by name."""
    return SavedTable.objects.filter(Q(visibility="shared") | Q(author=user)).order_by("name")


VISIBILITIES = ("shared", "private")


def filter_tables(tables: QuerySet[SavedTable], q: str = "", visibility: str = "") -> QuerySet[SavedTable]:
    """Narrow a list of saved tables. `visibility` is "shared" or "private" (anything else means all). Every word of
    `q` must match the table's name or its author's name or username."""
    if visibility in VISIBILITIES:
        tables = tables.filter(visibility=visibility)
    for word in q.split():
        tables = tables.filter(
            Q(name__icontains=word)
            | Q(author__first_name__icontains=word)
            | Q(author__last_name__icontains=word)
            | Q(author__username__icontains=word)
        )
    return tables


def can_delete(user: User, table: SavedTable) -> bool:
    """The author may delete a table, and so may a user with `assistant.manage_saved_tables`."""
    return table.author_id == user.pk or user.has_perm("assistant.manage_saved_tables")
