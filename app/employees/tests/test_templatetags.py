import pytest

from employees.forms import EmployeeForm
from employees.models import Employee
from employees.templatetags.hr import field

pytestmark = pytest.mark.django_db


def test_inline_textarea_starts_at_one_line_and_grows(hired: Employee) -> None:
    html = str(field(EmployeeForm(instance=hired)["address"])["widget"])
    assert 'rows="1"' in html and "[field-sizing:content]" in html and "resize-none" in html


def test_form_textareas_do_not_default_to_ten_rows() -> None:
    from employees.forms import HirePersonForm

    html = str(HirePersonForm()["address"])
    assert 'rows="2"' in html and 'rows="10"' not in html
