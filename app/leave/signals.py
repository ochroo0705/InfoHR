"""Leave reacts to a deleted auth group (role). When the role is a leave approval step, the database clears that step
(SET_NULL) and the settings are flagged, so Admin is told (spec 5.1)."""

from django.contrib.auth.models import Group
from django.db.models import Q
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from leave.models import LeaveSettings


@receiver(pre_delete, sender=Group, dispatch_uid="leave_approval_role_removed")
def mark_removed_approval_role(sender: type[Group], instance: Group, **kwargs: object) -> None:
    # pre_delete runs before the SET_NULL update of the settings row, so the link still shows the deleted role.
    LeaveSettings.objects.filter(Q(approval1_group=instance) | Q(approval2_group=instance)).update(
        approval_role_removed=True
    )
