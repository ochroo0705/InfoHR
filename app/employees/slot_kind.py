"""The Main / Temporary kind of a person, shared by the slot check (services.slots) and the survey report A9
(reports.engineers): contract staff are Temporary, everyone else Main."""

from macs.models import Employee

CONTRACT = "yes"  # Employee.contract_flag value of contract staff
MAIN = "Main"
TEMPORARY = "Temporary"


def kind_for(contract_flag: str | None) -> str:
    """The `nazg` kind of a person with this contract flag."""
    return TEMPORARY if contract_flag == CONTRACT else MAIN


def kind_of(employee: Employee) -> str:
    return kind_for(employee.contract_flag)
