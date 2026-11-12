"""Who may see and delete a saved workspace table (saved tables Task 1)."""

from accounts.models import User
from django.db.models import Q, QuerySet

from .models import SavedTable


def visible_to(user: User) -> QuerySet[SavedTable]:
    """Shared tables, and the user's own private ones, by name."""
    return SavedTable.objects.filter(Q(visibility="shared") | Q(author=user)).order_by("name")


def can_delete(user: User, table: SavedTable) -> bool:
    """The author may delete a table, and so may a user with `assistant.manage_saved_tables`."""
    return table.author_id == user.pk or user.has_perm("assistant.manage_saved_tables")
