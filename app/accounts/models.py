from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Login account. Roles are Django groups (see accounts.roles)."""

    # Set when a manager hands over a system-made temporary password; cleared when the user changes it.
    must_change_password = models.BooleanField("нууц үгээ солих ёстой", default=False)

    class Meta:
        # Own Meta replaces AbstractUser's, so repeat its (translated) names.
        verbose_name = _("user")
        verbose_name_plural = _("users")
        permissions = [
            # Admin-controlled switches (core-hr-scope §1), granted per role group.
            ("approve_leave", "Чөлөө, амралт батлах"),
            ("issue_orders", "Тушаал гаргах / баталгаажуулах"),
            ("export_lists", "Жагсаалтыг Excel рүү гаргах"),
        ]

    def get_full_name(self) -> str:
        """Mongolian order, like Employee.full_name: family (patronymic) name first."""
        return f"{self.last_name} {self.first_name}".strip()
