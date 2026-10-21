"""One-off: copies old education rows (educ + HR EducationExt) into the production qualification table.

Match for "already copied": same employee, start_year and org_name (school cut to 60, or "—" when no school).
Writes go through personal_writes.add with the inactive `system` user as actor. educ rows are never deleted.
"""

from typing import Any, cast

from accounts.models import User
from django.core.management.base import BaseCommand
from macs.models import EducRow, ProfessionType, QualificationRow

from employees.models import EducationExt, Employee
from employees.services import personal_writes

ORG_MAX = 60
NO_SCHOOL = "—"


def _system_user() -> User:
    user, created = User.objects.get_or_create(username="system", defaults={"first_name": "Систем", "is_active": False})
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


class Command(BaseCommand):
    help = "Copy old education rows (educ) into the qualification table. educ rows are never changed."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("--dry-run", action="store_true", help="Show what would be copied; write nothing.")

    def handle(self, *args: object, dry_run: bool = False, **options: object) -> None:
        exts = EducationExt.objects.in_bulk(list(EducRow.objects.values_list("id", flat=True)))
        professions: dict[str, int] = {}
        for pt in ProfessionType.objects.order_by("pk"):
            if pt.name:
                professions.setdefault(pt.name.strip().lower(), pt.pk)
        actor: User | None = None

        for educ in EducRow.objects.select_related("employee").order_by("pk"):
            employee = cast(Employee, educ.employee)
            ext = exts.get(educ.pk)
            school = ((ext.school if ext else "") or "").strip()
            org_full = school or NO_SCHOOL
            org_name = org_full[:ORG_MAX]
            field = ((ext.field if ext else "") or "").strip()
            end_year = (ext.graduation_year if ext and ext.graduation_year else None) or educ.start_year
            profession_id = professions.get(field.lower()) if field else None

            label = f"educ {educ.pk} ({employee.pk}, {org_name}, {educ.start_year})"
            if QualificationRow.objects.filter(
                employee=employee, start_year=educ.start_year, org_name=org_name
            ).exists():
                self.stdout.write(f"{label}: skipped (already there)")
                continue

            notes = []
            if len(org_full) > ORG_MAX:
                notes.append(f"school cut to {ORG_MAX}")
            if field and profession_id is None:
                notes.append(f"field not matched to a profession: {field}")
            note = f" [{'; '.join(notes)}]" if notes else ""

            if dry_run:
                self.stdout.write(f"{label}: would copy{note}")
                continue
            if actor is None:
                actor = _system_user()
            values: dict[str, object] = {
                "org_name": org_name,
                "start_year": educ.start_year,
                "end_year": end_year,
                "profession_type_id": profession_id,
            }
            personal_writes.add("education", employee, values, {}, by=actor)
            self.stdout.write(f"{label}: copied{note}")
