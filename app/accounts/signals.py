from typing import Any

from django.contrib.auth.models import Group
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import User
from .roles import EMPLOYEE


@receiver(post_save, sender=User)
def add_employee_role(sender: type[User], instance: User, created: bool, **kwargs: Any) -> None:
    """Every user gets the Employee role automatically (core-hr-scope §1)."""
    if created:
        group, _ = Group.objects.get_or_create(name=EMPLOYEE)
        instance.groups.add(group)
