"""Search words on Firebird (plan 6, Task fix-2): a word longer than the VARCHAR cut-off matches nothing, a normal word
still finds its row. Runs the real query in a subprocess against the module clone of the template (migrated_clone)."""

from typing import Any

from infohr_firebird.tests.test_settings_seam import result_of, run_django

SEARCH_CODE = """
import json
import django
django.setup()
from employees.models import Employee
from macs.dialect import search_match
first = Employee.objects.order_by("pk").first()
word = (first.family_name or "")[:3]
long_counts = {
    length: Employee.objects.filter(search_match("ж" * length, "family_name", "given_name", icase=True)).count()
    for length in (5000, 9000)
}
hits = set(Employee.objects.filter(search_match(word, "family_name", icase=True)).values_list("pk", flat=True))
print("RESULT " + json.dumps({
    "long_counts": {str(k): v for k, v in long_counts.items()},
    "word": word,
    "first_found": first.pk in hits,
}))
"""


def test_long_word_matches_nothing_and_normal_word_finds_its_row(migrated_clone: str) -> None:
    data: dict[str, Any] = result_of(run_django(SEARCH_CODE, DB_ENGINE="firebird", FIREBIRD_NAME=migrated_clone))
    # 9000 characters is past Firebird's UTF8 VARCHAR limit (about 8191 characters): the bug reproduces there.
    assert data["long_counts"] == {"5000": 0, "9000": 0}, data
    assert data["word"], data
    assert data["first_found"] is True, data
