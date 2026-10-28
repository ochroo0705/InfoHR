import re
from pathlib import Path

REPORTS = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"\b(JobRecord|SalaryRecord|EmployeeHistory|Movement)\b")


def _code(text: str) -> str:
    """The text without comments and without docstring-like triple-quoted blocks."""
    text = re.sub(r'""".*?"""', "", text, flags=re.S)
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


def test_reports_never_name_the_job_salary_or_history_models() -> None:
    """T-028: job facts reach the reports only through employees.listing. Importing or naming these models in
    app/reports (tests excluded) is how the rule used to break."""
    hits = []
    for path in sorted(REPORTS.glob("*.py")):
        for number, line in enumerate(_code(path.read_text(encoding="utf-8")).splitlines(), start=1):
            if FORBIDDEN.search(line):
                hits.append(f"{path.name}:{number}: {line.strip()}")
    assert hits == []
