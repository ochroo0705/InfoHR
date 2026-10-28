"""A2 «Ажилчдын мэдээлэл»: the old employee information sheet. It is the staff list under its old name, with the old
sheet's columns preselected and the column picker on. Saved views are off."""

import dataclasses

from reports import staff_list
from reports.filters import Filters

DEFAULT = (
    "code",
    "name",
    "clan_name",
    "register_no",
    "birth_date",
    "gender",
    "department",
    "position",
    "first_hire_date",
    "contract_no",
    "contract_start",
    "contract_end",
    "work_phone",
    "private_phone",
    "email",
    "marital_status",
    "education_level",
    "academic_degree",
    "nationality",
    "citizenship",
    "housing_condition",
    "car_ownership",
)
CONTRACT_NOTE = "Гэрээт ажилтнууд мөн орсон."  # the old sheet showed only non-contract staff; this one shows everyone


def _note(f: Filters) -> str:
    """The staff list's grey line, then the note that contract staff are included too."""
    base = staff_list._note(f)
    return f"{base} {CONTRACT_NOTE}" if base else CONTRACT_NOTE


REPORT = dataclasses.replace(
    staff_list.REPORT,
    key="employee-info",
    title="Ажилчдын мэдээлэл",
    filters=("state", "as_of", "branch", "department"),
    filter_needs={},
    default_columns=DEFAULT,
    saved_views=False,
    picks_columns=True,
    group_options=("department", "branch", "position"),
    note=_note,
)
