# ruff: noqa: DJ001, DJ008  -- production columns are nullable by design; these are read-mirror models
"""Production MACS tables (D-017). Unmanaged: Django never creates or alters them.
Write only through employees.services.macs_writes."""

from django.db import models

from macs.fields import SmallintFlagField, TimestampDateField


class _Table(models.Model):
    class Meta:
        abstract = True
        managed = False


class _NamedList(_Table):
    """Common shape of the code-list tables: an id and a name, ordered by name."""

    class Meta(_Table.Meta):
        abstract = True
        ordering = ["name"]

    def __str__(self) -> str:
        return str(getattr(self, "name", "") or "")


class MaritalStatus(_NamedList):
    id = models.AutoField(primary_key=True, db_column="maritalstatus_id")
    name = models.CharField("Нэр", max_length=30, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "marital_status"
        verbose_name = "Гэр бүлийн байдал"


class Country(_NamedList):
    id = models.AutoField(primary_key=True, db_column="country_ident")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)
    code = models.CharField(max_length=10, db_column="country_code", null=True, blank=True)

    class Meta(_NamedList.Meta):
        db_table = "country"
        verbose_name = "Улс"


class Nationality(_NamedList):
    id = models.AutoField(primary_key=True, db_column="nationality_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "nationality"
        verbose_name = "Үндэс угсаа"


class SocialOrigin(_NamedList):
    id = models.AutoField(primary_key=True, db_column="niigmiin_garal_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "niigmiin_garal"
        verbose_name = "Нийгмийн гарал"


class HousingCondition(_NamedList):
    id = models.AutoField(primary_key=True, db_column="apartcond_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "apartment_cond"
        verbose_name = "Орон байрны нөхцөл"


class CarOwnership(_NamedList):
    id = models.AutoField(primary_key=True, db_column="carowncond_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "carown_cond"
        verbose_name = "Автомашин эзэмшил"


class ElectedPosition(_NamedList):
    id = models.AutoField(primary_key=True, db_column="voting_work_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "voting_work"
        verbose_name = "Сонгуульт ажил"


class ClothesSize(_NamedList):
    id = models.AutoField(primary_key=True, db_column="typeid")
    name = models.CharField("Нэр", max_length=10, db_column="clothessize", null=True)
    size_type = models.CharField(
        max_length=7,
        db_column="sizetype",
        choices=[("clothes", "Хувцас"), ("shoes", "Гутал")],
    )
    size_men = models.CharField(max_length=10, db_column="size_other_man", null=True, blank=True)
    size_women = models.CharField(max_length=10, db_column="size_other_woman", null=True, blank=True)

    class Meta(_NamedList.Meta):
        db_table = "clothes_size_type"
        verbose_name = "Хэмжээ"


class City(_NamedList):
    id = models.AutoField(primary_key=True, db_column="city_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "citytown"
        verbose_name = "Хот, сум"


class District(_NamedList):
    id = models.AutoField(primary_key=True, db_column="district_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)
    city = models.ForeignKey(City, db_column="city_ident", on_delete=models.DO_NOTHING, related_name="districts")

    class Meta(_NamedList.Meta):
        db_table = "district"
        verbose_name = "Дүүрэг, баг"


class EducationLevel(_NamedList):
    id = models.AutoField(primary_key=True, db_column="education_id")
    name = models.CharField("Нэр", max_length=25, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "education"
        verbose_name = "Боловсрол"


class AcademicDegree(_NamedList):
    id = models.AutoField(primary_key=True, db_column="graduate_id")
    name = models.CharField("Нэр", max_length=25, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "graduate"
        verbose_name = "Эрдмийн зэрэг"


class InsuredCategory(_NamedList):
    id = models.AutoField(primary_key=True, db_column="insur_id")
    name = models.CharField("Нэр", max_length=100, db_column="description", null=True)
    code = models.CharField(max_length=10, db_column="insur_code", null=True, blank=True)

    class Meta(_NamedList.Meta):
        db_table = "insur_type"
        verbose_name = "Даатгуулагчийн ангилал"


class Bank(_NamedList):
    id = models.AutoField(primary_key=True, db_column="bank_id")
    name = models.CharField("Нэр", max_length=100, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "banks"
        verbose_name = "Банк"


class Branch(_NamedList):
    """Салбар (production branch). Lookup only: HR never adds rows here (not on the Lists page)."""

    id = models.AutoField(primary_key=True, db_column="branch_id")
    name = models.CharField("Салбар", max_length=25, db_column="description")
    status = models.SmallIntegerField(db_column="status", default=1)  # NOT NULL in production; 1 = in use

    class Meta(_NamedList.Meta):
        db_table = "branch"
        verbose_name = "Салбар"


class Shift(_NamedList):
    id = models.AutoField(primary_key=True, db_column="id")
    name = models.CharField("Нэр", max_length=20, db_column="name", null=True)

    class Meta(_NamedList.Meta):
        db_table = "shifts"
        verbose_name = "Ажлын цагийн хуваарь"


class Department(_NamedList):
    id = models.SmallAutoField(primary_key=True, db_column="dep_id")
    name = models.CharField("Нэр", max_length=25, db_column="name", null=True)

    class Meta(_NamedList.Meta):
        db_table = "deps"
        verbose_name = "Хэлтэс"
        verbose_name_plural = "Хэлтсүүд"


class FiredReason(_NamedList):
    """Leaving reason (production fired_reason). The name is the list label; one entry can be marked "died"."""

    id = models.AutoField(primary_key=True, db_column="firedreason_id")
    name = models.CharField("Нэр", max_length=100, db_column="description")

    class Meta(_NamedList.Meta):
        db_table = "fired_reason"
        verbose_name = "Ажлаас гарсан шалтгаан"


class Office(_NamedList):
    id = models.AutoField(primary_key=True, db_column="office_id")
    name = models.CharField("Нэр", max_length=100, db_column="name")

    class Meta(_NamedList.Meta):
        db_table = "hr_office"
        verbose_name = "Алба"


class Section(_NamedList):
    id = models.AutoField(primary_key=True, db_column="section_id")
    name = models.CharField("Нэр", max_length=100, db_column="name")

    class Meta(_NamedList.Meta):
        db_table = "hr_section"
        verbose_name = "Хэсэг"


class Position(_Table):
    id = models.AutoField(primary_key=True, db_column="occupation_id")
    name = models.CharField("Нэр", max_length=100, db_column="description")

    class Meta(_Table.Meta):
        db_table = "occupation"
        verbose_name = "Албан тушаал"
        verbose_name_plural = "Албан тушаалууд"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def _fk(model: type[models.Model], column: str, label: str) -> models.ForeignKey:  # type: ignore[type-arg]
    return models.ForeignKey(
        model,
        verbose_name=label,
        db_column=column,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )


class Employee(_Table):
    id = models.AutoField(primary_key=True, db_column="employee_id")
    code = models.CharField("Ажилтны код", max_length=10, db_column="empno", null=True, blank=True)
    given_name = models.CharField("Нэр", max_length=25, db_column="name")
    family_name = models.CharField("Эцэг/эхийн нэр", max_length=25, db_column="surname", null=True)
    clan_name = models.CharField("Ургийн овог", max_length=25, db_column="ovog", null=True, blank=True)
    fullname = models.CharField(max_length=208, db_column="fullname", null=True, blank=True)
    register_no = models.CharField("Регистрийн дугаар", max_length=20, db_column="registerno", null=True)
    birth_date = TimestampDateField("Төрсөн огноо", db_column="birthday", null=True)
    birth_year = models.IntegerField(db_column="birthyear", null=True, blank=True)
    gender = models.CharField(
        "Хүйс",
        max_length=1,
        db_column="gender",
        choices=[("M", "Эрэгтэй"), ("F", "Эмэгтэй")],
        null=True,
    )
    work_phone = models.CharField("Ажлын утас", max_length=14, db_column="workphone", null=True)
    private_phone = models.CharField("Хувийн утас", max_length=14, db_column="homephone", null=True, blank=True)
    phone2 = models.CharField("Утас #2", max_length=14, db_column="phone2", null=True, blank=True)
    email = models.EmailField("И-мэйл", max_length=50, db_column="email", null=True, blank=True)
    passport_no = models.CharField(
        "Иргэний үнэмлэх / паспорт", max_length=14, db_column="passport", null=True, blank=True
    )
    first_hire_date = TimestampDateField("Анх ажилд орсон огноо", db_column="inworkdate", null=True)
    prior_service_years = models.SmallIntegerField("Өмнөх ажилласан жил", db_column="working_year", default=0)
    sector_years = models.SmallIntegerField("Салбарт ажилласан жил", db_column="workyear_sector", default=0)
    work_conditions = models.SmallIntegerField(
        "Ажлын нөхцөл",
        db_column="workcondtn",
        null=True,
        choices=[(1, "Хэвийн"), (2, "Хүнд"), (3, "Бусад")],
    )
    military_service = models.CharField(
        "Цэргийн алба хаасан",
        max_length=3,
        db_column="is_soldier",
        null=True,
        blank=True,
        choices=[("yes", "Тийм"), ("no", "Үгүй")],
    )
    blood_type = models.CharField(
        "Цусны бүлэг",
        max_length=2,
        db_column="blood_type",
        null=True,
        blank=True,
        choices=[("O", "I (O)"), ("A", "II (A)"), ("B", "III (B)"), ("AB", "IV (AB)")],
    )
    foreign_emp = models.SmallIntegerField("Гадаад иргэн", db_column="foreign_emp", null=True, blank=True)
    hr_flag = models.CharField(max_length=12, db_column="hr", default="no")
    loginpass = models.CharField(max_length=20, db_column="loginpass", null=True, blank=True)
    status = models.CharField(max_length=8, db_column="status", null=True, blank=True)
    contract_flag = models.CharField(max_length=12, db_column="contract_emp", default="no")
    wagetest = models.SmallIntegerField(db_column="wagetest_emp", null=True, blank=True)
    emptype = models.SmallIntegerField(db_column="emptype", null=True, blank=True)
    department = models.ForeignKey(
        Department,
        db_column="dep_ident",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    position = models.ForeignKey(
        Position,
        db_column="occupation_ident",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    second_position = _fk(Position, "occupation_ident2", "Албан тушаал (хавсарсан)")
    office = _fk(Office, "office_ident", "Алба")
    section = _fk(Section, "section_ident", "Хэсэг")
    job_type = models.CharField(
        "Ажлын төрөл",
        max_length=20,
        db_column="job_type",
        null=True,
        blank=True,
        choices=[("NonSesional", "Тогтмол"), ("Sesional", "Улирлын")],
    )
    job_figure = models.CharField(
        "Ажлын хэлбэр",
        max_length=20,
        db_column="job_figure",
        null=True,
        default="Main",
        choices=[("Main", "Үндсэн"), ("Temporary", "Түр")],
    )
    contract_no = models.CharField(max_length=10, db_column="contract_num", null=True, blank=True)
    contract_start = TimestampDateField(db_column="g_date", null=True, blank=True)
    contract_end = TimestampDateField(db_column="g_enddate", null=True, blank=True)
    salary = models.DecimalField(max_digits=15, decimal_places=2, db_column="salary", default=0)
    changed_date = TimestampDateField(db_column="changed_date", null=True, blank=True)
    account_no = models.CharField("Дансны дугаар", max_length=20, db_column="ecode", null=True, blank=True)
    bank = _fk(Bank, "bank_ident", "Банк")
    social_insurance_no = models.CharField("НДД-ийн дугаар", max_length=14, db_column="ndno", null=True, blank=True)
    health_insurance_no = models.CharField("ЭМДД-ийн дугаар", max_length=14, db_column="emdno", null=True, blank=True)
    insured_category = _fk(InsuredCategory, "insur_ident", "Даатгуулагчийн төрөл")
    taxpayer_no = models.CharField(
        "Татвар төлөгчийн дугаар", max_length=30, db_column="etax_code", null=True, blank=True
    )
    has_disability = SmallintFlagField("Хөгжлийн бэрхшээлтэй", db_column="disabled_emp", default=False)
    probation_months = models.SmallIntegerField("Туршилтын сар", db_column="test_month", null=True, blank=True)
    marital_status = _fk(MaritalStatus, "maritalstatus_ident", "Гэрлэлтийн байдал")
    citizenship = _fk(Country, "country_ident", "Иргэншил")
    nationality = _fk(Nationality, "nationality_ident", "Үндэс угсаа")
    social_origin = _fk(SocialOrigin, "niigmiin_garal_ident", "Нийгмийн гарал")
    housing_condition = _fk(HousingCondition, "apartcond_ident", "Орон байрны нөхцөл")
    car_ownership = _fk(CarOwnership, "carowncond_ident", "Автомашин эзэмшил")
    clothing_size = _fk(ClothesSize, "clothessize_ident", "Хувцасны хэмжээ")
    shoe_size = _fk(ClothesSize, "shoessize_ident", "Гутлын хэмжээ")
    elected_position = _fk(ElectedPosition, "voting_work_ident", "Сонгуульт ажил")
    work_schedule = _fk(Shift, "schedule", "Ажлын цагийн хуваарь")
    education_level = _fk(EducationLevel, "education_ident", "Боловсрол")
    academic_degree = _fk(AcademicDegree, "graduate_ident", "Эрдмийн зэрэг")
    fired_reason = _fk(FiredReason, "firedreason_ident", "Ажлаас гарсан шалтгаан")
    taken_leave = models.SmallIntegerField("Урт амралттай", db_column="taken_leave", null=True, blank=True)
    leave_type = models.SmallIntegerField(
        "Амралтын төрөл",
        db_column="leave_type",
        null=True,
        blank=True,
        choices=[(1, "Цалингүй"), (2, "Хүүхэд асрах"), (3, "Жирэмсний амралт")],
    )
    branch = _fk(Branch, "branch_ident", "Салбар")
    last_order_no = models.CharField(
        "Сүүлийн тушаалын дугаар", max_length=10, db_column="command_no", null=True, blank=True
    )
    last_order_text = models.CharField(
        "Сүүлийн тушаалын агуулга", max_length=100, db_column="command_description", null=True, blank=True
    )
    died = models.CharField(max_length=12, db_column="died", default="no")
    command_id_value = models.IntegerField(db_column="command_ident", null=True, blank=True)
    move_type = models.SmallIntegerField(db_column="move_type", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "employee"
        verbose_name = "Ажилтан"
        verbose_name_plural = "Ажилтнууд"
        ordering = ["family_name", "given_name"]
        permissions = [
            ("view_employees", "Бүх ажилтныг харах"),
            ("manage_employees", "Ажилтан нэмэх, засах, засвар хийх"),
            ("view_personal", "Хувийн мэдээллийг харах"),
            ("view_salary", "Цалин, даатгалын мэдээллийг харах"),
            ("manage_salary", "Цалин, даатгалын мэдээллийг засах"),
        ]

    def __str__(self) -> str:
        return f"{self.code or ''} {self.full_name}".strip()

    @property
    def full_name(self) -> str:
        return f"{self.family_name or ''} {self.given_name}".strip()

    @property
    def short_name(self) -> str:
        return f"{self.family_name[:1]}. {self.given_name}" if self.family_name else self.given_name


class Command(_Table):
    """A production HR order (тушаал). Written only through employees.services.macs_writes."""

    id = models.AutoField(primary_key=True, db_column="command_id")
    employee = models.ForeignKey(Employee, db_column="employee_ident", on_delete=models.DO_NOTHING, related_name="+")
    summary = models.CharField(max_length=50, db_column="command", null=True, blank=True)
    date = TimestampDateField(db_column="outdate", null=True)
    issued_by = models.CharField(max_length=25, db_column="human_command", null=True, blank=True)
    number = models.CharField(max_length=10, db_column="commandno")
    path = models.CharField(max_length=100, db_column="path", null=True, blank=True)
    order_type = models.SmallIntegerField(db_column="command_type", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "command"
        verbose_name = "Тушаал"
        verbose_name_plural = "Тушаалууд"


class BirthPlace(_Table):
    """Where the employee was born (production birth_place; one row per employee in practice)."""

    id = models.AutoField(primary_key=True, db_column="birth_place_id")
    employee = models.ForeignKey(Employee, db_column="emp_id", on_delete=models.DO_NOTHING, related_name="+")
    city = models.ForeignKey(City, db_column="city_id", on_delete=models.DO_NOTHING, related_name="+")
    district = models.ForeignKey(
        District, db_column="district_id", null=True, blank=True, on_delete=models.DO_NOTHING, related_name="+"
    )
    description = models.CharField(max_length=50, db_column="description", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "birth_place"


class EmployeePhoto(_Table):
    id = models.AutoField(primary_key=True, db_column="photo_id")
    employee = models.ForeignKey(Employee, db_column="emp_id", on_delete=models.DO_NOTHING, related_name="+")
    data = models.BinaryField(db_column="photo", null=True)

    class Meta(_Table.Meta):
        db_table = "emp_photo"


class EmployeeHistory(_Table):
    id = models.IntegerField(primary_key=True, db_column="history_id")
    employee_id_value = models.IntegerField(db_column="employee_ident")
    given_name = models.CharField(max_length=25, db_column="name")
    family_name = models.CharField(max_length=25, db_column="surname", null=True)
    fullname = models.CharField(max_length=208, db_column="fullname", null=True)
    salary = models.DecimalField(max_digits=15, decimal_places=2, db_column="salary", default=0)
    status = models.CharField(max_length=8, db_column="status", null=True)
    contract_flag = models.CharField(max_length=12, db_column="contract_emp", null=True)
    wagetest = models.SmallIntegerField(db_column="wagetest_emp", null=True)
    emptype = models.SmallIntegerField(db_column="emptype", null=True)
    department_id_value = models.IntegerField(db_column="dep_ident", null=True)
    position_id_value = models.IntegerField(db_column="occupation_ident", null=True)
    first_hire_date = TimestampDateField(db_column="inworkdate", null=True)
    contract_start = TimestampDateField(db_column="g_date", null=True)
    contract_end = TimestampDateField(db_column="g_enddate", null=True)
    changed_date = TimestampDateField(db_column="changed_date", null=True)
    work_conditions = models.SmallIntegerField(db_column="workcondtn", null=True)
    register_no = models.CharField(max_length=20, db_column="register", null=True)
    gender = models.CharField(max_length=1, db_column="gender", null=True)
    birth_date = TimestampDateField(db_column="birthday", null=True)
    is_default = models.SmallIntegerField(db_column="isdefault", null=True)
    fired_date = TimestampDateField(db_column="fired_date", null=True)
    fired_reason_id_value = models.IntegerField(db_column="firedreason_ident", null=True)
    branch_id_value = models.IntegerField(db_column="branch_ident", null=True, blank=True)
    move_type = models.SmallIntegerField(db_column="move_type", null=True, blank=True)
    command_id_value = models.IntegerField(db_column="command_ident", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "employee_history"


class Movement(_Table):
    id = models.AutoField(primary_key=True, db_column="movement_id")
    employee = models.ForeignKey(Employee, db_column="emp_id", on_delete=models.DO_NOTHING, related_name="+")
    kind = models.CharField(
        max_length=4,
        db_column="movement",
        choices=[("in", "in"), ("dep", "dep"), ("occ", "occ"), ("out", "out")],
    )
    date = TimestampDateField(db_column="move_date")
    description = models.CharField(max_length=100, db_column="description", null=True, blank=True)
    old_department_id_value = models.SmallIntegerField(db_column="old_depid", null=True)
    old_position_id_value = models.IntegerField(db_column="old_occupid", null=True)
    old_emptype = models.SmallIntegerField(db_column="old_emptype", null=True)
    new_department_id_value = models.SmallIntegerField(db_column="new_depid", null=True)
    new_position_id_value = models.IntegerField(db_column="new_occupid", null=True)
    new_emptype = models.SmallIntegerField(db_column="new_emptype", null=True)

    class Meta(_Table.Meta):
        db_table = "movement"


class LeaveTypeRow(_Table):
    """Leave type code list (`leave_type`). Named LeaveTypeRow to avoid clashing with the old `leave_type` column."""

    id = models.AutoField(primary_key=True, db_column="leavetype_id")
    name = models.CharField("Нэр", max_length=200, db_column="description")

    class Meta(_Table.Meta):
        db_table = "leave_type"
        verbose_name = "Ээлжийн амралтын төрөл"
        verbose_name_plural = "Ээлжийн амралтын төрлүүд"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class LeaveAssign(_Table):
    """Leave taken or planned by an employee (`leave_assign`)."""

    APPROVED = 1
    CANCELLED = 2
    REJECTED = 3

    id = models.AutoField(primary_key=True, db_column="assign_id")
    employee = models.ForeignKey(
        Employee,
        verbose_name="Ажилтан",
        db_column="emp_ident",
        db_constraint=False,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    leave_type = models.ForeignKey(
        LeaveTypeRow,
        verbose_name="Амралтын төрөл",
        db_column="leavetype_ident",
        db_constraint=False,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    date1 = TimestampDateField("Эхлэх огноо", db_column="date1")
    date2 = TimestampDateField("Дуусах огноо", db_column="date2")
    comment = models.CharField("Тайлбар", max_length=200, db_column="comment", null=True, blank=True)
    status = models.SmallIntegerField("Төлөв", db_column="status", null=True, blank=True)
    adays = models.IntegerField("Хоног", db_column="adays", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "leave_assign"
        verbose_name = "Ээлжийн амралт"
        verbose_name_plural = "Ээлжийн амралтууд"


class Entitlement(_Table):
    """Leave days granted to an employee for a period (`entitlement`). Negative days are allowed."""

    id = models.AutoField(primary_key=True, db_column="entitlement_id")
    employee = models.ForeignKey(
        Employee,
        verbose_name="Ажилтан",
        db_column="emp_ident",
        db_constraint=False,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    leave_type = models.ForeignKey(
        LeaveTypeRow,
        verbose_name="Амралтын төрөл",
        db_column="leavetype_ident",
        db_constraint=False,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    date1 = TimestampDateField("Эхлэх огноо", db_column="date1")
    date2 = TimestampDateField("Дуусах огноо", db_column="date2")
    ent_days = models.IntegerField("Эрх (хоног)", db_column="ent_days")
    comment = models.CharField("Тайлбар", max_length=200, db_column="comment", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "entitlement"
        verbose_name = "Ээлжийн амралтын эрх"
        verbose_name_plural = "Ээлжийн амралтын эрхүүд"


class AbsenceType(_NamedList):
    """Type list of the old program's «Амралт» log (`holiday_type`). Read only."""

    id = models.AutoField(primary_key=True, db_column="holidaytype_id")
    name = models.CharField("Нэр", max_length=50, db_column="description")

    class Meta(_NamedList.Meta):
        db_table = "holiday_type"
        verbose_name = "Амралтын бүртгэлийн төрөл"


class Absence(_Table):
    """One row of the old program's «Амралт» grid (`holiday`): employee, type, from/to, note.
    A side log: no status, no days column, no link to `entitlement`, feeds no balance. Info HR only
    shows it (read only); leave itself lives in `leave_assign` and `entitlement`."""

    id = models.AutoField(primary_key=True, db_column="holiday_id")
    employee = models.ForeignKey(
        Employee,
        verbose_name="Ажилтан",
        db_column="employee_ident",
        db_constraint=False,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    absence_type = models.ForeignKey(
        AbsenceType,
        verbose_name="Төрөл",
        db_column="holidaytype_ident",
        db_constraint=False,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    from_date = TimestampDateField("Эхэлсэн огноо", db_column="from_date")
    to_date = TimestampDateField("Дууссан огноо", db_column="to_date", null=True, blank=True)
    note = models.CharField("Үндэслэл", max_length=200, db_column="note", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "holiday"
        verbose_name = "Амралтын бүртгэл"
        verbose_name_plural = "Амралтын бүртгэлүүд"


class LegalHoliday(_Table):
    """Public holiday calendar entry (`hr_legalholidays`)."""

    id = models.AutoField(primary_key=True, db_column="holiday_id")
    name = models.CharField("Нэр", max_length=100, db_column="description")
    start_date = TimestampDateField("Эхлэх огноо", db_column="start_date")
    end_date = TimestampDateField("Дуусах огноо", db_column="end_date")
    hdays = models.SmallIntegerField("Хоног", db_column="hdays")

    class Meta(_Table.Meta):
        db_table = "hr_legalholidays"
        verbose_name = "Улсын баярын өдөр"
        verbose_name_plural = "Улсын баярын өдрүүд"


def _ref(
    model: type[models.Model],
    column: str,
    label: str | None = None,
    *,
    null: bool = False,
) -> models.ForeignKey:  # type: ignore[type-arg]
    """A reference to another production row, not enforced by Django (the DB keeps its own FK)."""
    return models.ForeignKey(
        model,
        verbose_name=label,
        db_column=column,
        on_delete=models.DO_NOTHING,
        related_name="+",
        db_constraint=False,
        null=null,
        blank=null,
    )


class FamilyRelation(_NamedList):
    """Гэр бүлийн хамаарал: the kind of family member (son, dad, ...). `fm_type` is the fixed key."""

    id = models.AutoField(primary_key=True, db_column="familymember_id")
    name = models.CharField("Нэр", max_length=30, db_column="description", null=True)
    fm_type = models.CharField(
        "Хамаарлын төрөл",
        max_length=10,
        db_column="fm_type",
        null=True,
        choices=[
            ("son", "Хүү"),
            ("daughter", "Охин"),
            ("dad", "Аав"),
            ("mother", "Ээж"),
            ("spouse", "Эхнэр, нөхөр"),
            ("other", "Бусад"),
        ],
    )

    class Meta(_NamedList.Meta):
        db_table = "family_members"
        verbose_name = "Гэр бүлийн хамаарал"


class EduType(_NamedList):
    id = models.AutoField(primary_key=True, db_column="education_id")
    name = models.CharField("Нэр", max_length=50, db_column="name", null=True)

    class Meta(_NamedList.Meta):
        db_table = "edu_type"
        verbose_name = "Боловсролын төрөл"


class QualificationType(_NamedList):
    """Мэргэшлийн төрөл (table `qualification_type`)."""

    id = models.AutoField(primary_key=True, db_column="qualificationtype_id")
    name = models.CharField("Нэр", max_length=100, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "qualification_type"
        verbose_name = "Мэргэшлийн төрөл"


class ProfessionType(_NamedList):
    """Мэргэжлийн төрөл (table `profession_type`)."""

    id = models.AutoField(primary_key=True, db_column="professiontype_id")
    name = models.CharField("Нэр", max_length=100, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "profession_type"
        verbose_name = "Мэргэжлийн төрөл"


class SpecEduType(_NamedList):
    """Тусгай боловсролын төрөл (table `spec_edu_type`)."""

    id = models.AutoField(primary_key=True, db_column="spec_edu_type_id")
    name = models.CharField("Нэр", max_length=30, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "spec_edu_type"
        verbose_name = "Тусгай боловсролын төрөл"


class ForeignLanguage(_NamedList):
    """Гадаад хэл (table `flanguages`)."""

    id = models.AutoField(primary_key=True, db_column="flanguage_id")
    name = models.CharField("Нэр", max_length=30, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "flanguages"
        verbose_name = "Гадаад хэл"


class LanguageLevel(_NamedList):
    """Хэлний түвшин (table `lang_level`)."""

    id = models.AutoField(primary_key=True, db_column="langlevel_id")
    name = models.CharField("Нэр", max_length=50, db_column="level_name", null=True)

    class Meta(_NamedList.Meta):
        db_table = "lang_level"
        verbose_name = "Хэлний түвшин"


class TalentKind(_NamedList):
    id = models.AutoField(primary_key=True, db_column="talent_id")
    name = models.CharField("Нэр", max_length=30, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "talents"
        verbose_name = "Авьяас"


class PresentType(_NamedList):
    id = models.AutoField(primary_key=True, db_column="presenttype_id")
    name = models.CharField("Нэр", max_length=50, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "present_type"
        verbose_name = "Бэлгийн төрөл"


class ContactType(_NamedList):
    id = models.AutoField(primary_key=True, db_column="contacttype_id")
    name = models.CharField("Нэр", max_length=30, db_column="description", null=True)

    class Meta(_NamedList.Meta):
        db_table = "contact_type"
        verbose_name = "Холбоо барих төрөл"


class FamilyRow(_Table):
    """Ажилтны гэр бүлийн гишүүн (table `family`)."""

    id = models.AutoField(primary_key=True, db_column="family_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    relation = _ref(FamilyRelation, "familymember_ident", "Хамаарал")
    given_name = models.CharField("Нэр", max_length=40, db_column="given_name")
    surname = models.CharField("Овог", max_length=30, db_column="surname", null=True, blank=True)
    birth_date = TimestampDateField("Төрсөн огноо", db_column="birth_date", null=True, blank=True)
    job = models.CharField("Ажил, албан тушаал", max_length=100, db_column="job", null=True, blank=True)
    phone = models.CharField("Утас", max_length=14, db_column="phone", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "family"
        verbose_name = "Гэр бүлийн гишүүн"


class EducRow(_Table):
    """Ажилтны боловсрол (table `educ`)."""

    id = models.SmallAutoField(primary_key=True, db_column="educ_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    edu_type = _ref(EduType, "edu_ident", "Боловсролын төрөл")
    startdate = TimestampDateField("Эхэлсэн огноо", db_column="startdate", null=True, blank=True)
    start_year = models.SmallIntegerField("Эхэлсэн он", db_column="start_year")

    class Meta(_Table.Meta):
        db_table = "educ"
        verbose_name = "Боловсрол"


class QualificationRow(_Table):
    """Ажилтны мэргэшил, дипломын мэдээлэл (table `qualification`)."""

    id = models.SmallAutoField(primary_key=True, db_column="qualification_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    qualification_type = _ref(QualificationType, "qualificationtype_ident", "Мэргэшлийн төрөл", null=True)
    profession_type = _ref(ProfessionType, "professiontype_ident", "Мэргэжлийн төрөл", null=True)
    org_name = models.CharField("Байгууллагын нэр", max_length=60, db_column="org_name")
    diplom_number = models.CharField("Дипломын дугаар", max_length=10, db_column="diplom_number", null=True, blank=True)
    start_date = TimestampDateField("Эхэлсэн огноо", db_column="start_date", null=True, blank=True)
    ending_date = TimestampDateField("Дууссан огноо", db_column="ending_date", null=True, blank=True)
    credit_score = models.DecimalField(
        "Кредит оноо", max_digits=6, decimal_places=2, db_column="credit_score", null=True, blank=True
    )
    country = models.CharField("Улс", max_length=20, db_column="country", null=True, blank=True)
    edu_level = _ref(EducationLevel, "edu_ident", "Боловсрол", null=True)
    grade = _ref(AcademicDegree, "grade", "Эрдмийн зэрэг", null=True)
    start_year = models.SmallIntegerField("Эхэлсэн он", db_column="start_year")
    end_year = models.SmallIntegerField("Дууссан он", db_column="end_year")

    class Meta(_Table.Meta):
        db_table = "qualification"
        verbose_name = "Мэргэшил"


class CertificateRow(_Table):
    """Ажилтны тусгай боловсрол, сертификат (table `spec_edu`)."""

    id = models.AutoField(primary_key=True, db_column="spec_edu_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    cert_type = _ref(SpecEduType, "spec_edu_type_ident", "Төрөл")
    org_edu = models.CharField("Байгууллагын нэр", max_length=30, db_column="org_edu")
    certify_number = models.CharField(
        "Гэрчилгээний дугаар", max_length=20, db_column="certify_number", null=True, blank=True
    )
    certify_date = TimestampDateField("Гэрчилгээ олгосон огноо", db_column="certify_date", null=True, blank=True)
    profession = models.CharField("Мэргэжил", max_length=20, db_column="profession", null=True, blank=True)
    end_date = TimestampDateField("Дууссан огноо", db_column="end_date", null=True, blank=True)
    spec_profession = models.CharField(
        "Тусгай мэргэжил", max_length=20, db_column="spec_profession", null=True, blank=True
    )
    certify_year = models.SmallIntegerField("Гэрчилгээний он", db_column="certify_year")

    class Meta(_Table.Meta):
        db_table = "spec_edu"
        verbose_name = "Тусгай боловсрол, сертификат"


class TrainingRow(_Table):
    """Ажилтны сургалт (table `hr_training`). The key column is `emp_ident`."""

    id = models.AutoField(primary_key=True, db_column="training_id")
    employee = _ref(Employee, "emp_ident", "Ажилтан")
    tr_type = models.SmallIntegerField("Сургалтын төрөл", db_column="tr_type")
    description = models.CharField("Сургалтын нэр", max_length=50, db_column="description")
    start_date = TimestampDateField("Эхэлсэн огноо", db_column="start_date", null=True, blank=True)
    days = models.SmallIntegerField("Хоног", db_column="days", null=True, blank=True)
    amount = models.DecimalField("Зардал", max_digits=14, decimal_places=2, db_column="amount")
    pay_type = models.SmallIntegerField("Төлбөр хариуцсан", db_column="pay_type")
    training_center = models.CharField(
        "Сургалтын төв", max_length=100, db_column="training_center", null=True, blank=True
    )
    start_year = models.SmallIntegerField("Эхэлсэн он", db_column="start_year")

    class Meta(_Table.Meta):
        db_table = "hr_training"
        verbose_name = "Сургалт"


class LanguageRow(_Table):
    """Ажилтны гадаад хэлний мэдлэг (table `foreign_lang`). Level columns hold the level name text."""

    id = models.AutoField(primary_key=True, db_column="foreignlang_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    language = _ref(ForeignLanguage, "flanguage_ident", "Гадаад хэл")
    understand_lvl = models.CharField("Ойлгох түвшин", max_length=15, db_column="understand_lvl", null=True, blank=True)
    speaking_lvl = models.CharField("Ярих түвшин", max_length=15, db_column="speaking_lvl", null=True, blank=True)
    reading_lvl = models.CharField("Унших түвшин", max_length=15, db_column="reading_lvl", null=True, blank=True)
    writing_lvl = models.CharField("Бичих түвшин", max_length=15, db_column="writing_lvl", null=True, blank=True)
    description = models.CharField("Тайлбар", max_length=50, db_column="description", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "foreign_lang"
        verbose_name = "Гадаад хэл"


class PresentRow(_Table):
    """Ажилтанд өгсөн бэлэг (table `given_present`)."""

    id = models.AutoField(primary_key=True, db_column="present_id")
    employee = _ref(Employee, "empid", "Ажилтан")
    childqty = models.IntegerField("Хүүхдийн тоо", db_column="childqty")
    price = models.IntegerField("Үнэ", db_column="price")
    given_year = models.IntegerField("Бэлэглэсэн он", db_column="given_year")
    pdate = TimestampDateField("Огноо", db_column="pdate")
    present_type = _ref(PresentType, "presenttype_ident", "Бэлгийн төрөл")
    child_age = models.SmallIntegerField("Хүүхдийн нас", db_column="child_age")
    given = models.SmallIntegerField("Өгсөн эсэх", db_column="given")

    class Meta(_Table.Meta):
        db_table = "given_present"
        verbose_name = "Бэлэг"


class AddressRow(_Table):
    """Ажилтны хаяг (table `address`). The DB key is (address_id, employee_ident); writes must
    always also filter by employee."""

    id = models.AutoField(primary_key=True, db_column="address_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    street = models.CharField("Хаяг", max_length=50, db_column="address", null=True, blank=True)
    city = _ref(City, "city_id", "Аймаг, хот")
    district = _ref(District, "district", "Сум, дүүрэг")

    class Meta(_Table.Meta):
        db_table = "address"
        verbose_name = "Хаяг"


class ContactRow(_Table):
    """Яаралтай үед холбогдох хүн (table `contacting`)."""

    id = models.AutoField(primary_key=True, db_column="contacting_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    contact_type = _ref(ContactType, "contacttype_ident", "Холбоо барих төрөл")
    value = models.CharField("Утас, имэйл", max_length=30, db_column="contacting", null=True, blank=True)
    name = models.CharField("Нэр", max_length=100, db_column="contact_name")
    relative = models.CharField("Хамаарал", max_length=10, db_column="contact_relative")

    class Meta(_Table.Meta):
        db_table = "contacting"
        verbose_name = "Холбоо барих хүн"
