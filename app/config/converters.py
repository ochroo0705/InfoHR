"""URL path converters shared by the project's urls.py files."""

INT4_MIN, INT4_MAX = -(2**31), 2**31 - 1


class SignedIntConverter:
    """Like <int:...> but also accepts negative numbers. MACS lookup tables can hold negative ids (QC 2b)."""

    regex = r"-?[0-9]{1,10}"

    def to_python(self, value: str) -> int:
        number = int(value)
        if not INT4_MIN <= number <= INT4_MAX:  # outside the id column's range: a 404, not a database error
            raise ValueError(value)
        return number

    def to_url(self, value: int) -> str:
        return str(value)
