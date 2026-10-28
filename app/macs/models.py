# ruff: noqa: DJ001, DJ008  -- production columns are nullable by design; these are read-mirror models
"""Production MACS tables (D-017). Unmanaged: Django never creates or alters them.
Write only through employees.services.macs_writes."""

from decimal import Decimal

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
    fullname = models.CharField("Бүтэн нэр", max_length=208, db_column="fullname", null=True, blank=True)
    register_no = models.CharField("Регистрийн дугаар", max_length=20, db_column="registerno", null=True)
    birth_date = TimestampDateField("Төрсөн огноо", db_column="birthday", null=True)
    birth_year = models.IntegerField("Төрсөн он", db_column="birthyear", null=True, blank=True)
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
    hr_flag = models.CharField("Хүний нөөцөд бүртгэлтэй", max_length=12, db_column="hr", default="no")
    loginpass = models.CharField(
        "Хуучин программын нэвтрэх нууц үг", max_length=20, db_column="loginpass", null=True, blank=True
    )
    status = models.CharField("Төлөв", max_length=8, db_column="status", null=True, blank=True)
    contract_flag = models.CharField("Гэрээт ажилтан", max_length=12, db_column="contract_emp", default="no")
    wagetest = models.SmallIntegerField("Цалингийн туршилт", db_column="wagetest_emp", null=True, blank=True)
    emptype = models.SmallIntegerField("Ажилтны төрлийн код", db_column="emptype", null=True, blank=True)
    department = models.ForeignKey(
        Department,
        verbose_name="Хэлтэс",
        db_column="dep_ident",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="+",
    )
    position = models.ForeignKey(
        Position,
        verbose_name="Албан тушаал",
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
    contract_no = models.CharField("Гэрээний дугаар", max_length=10, db_column="contract_num", null=True, blank=True)
    contract_start = TimestampDateField("Гэрээ эхлэх", db_column="g_date", null=True, blank=True)
    contract_end = TimestampDateField("Гэрээ дуусах", db_column="g_enddate", null=True, blank=True)
    salary = models.DecimalField("Цалин", max_digits=15, decimal_places=2, db_column="salary", default=0)
    changed_date = TimestampDateField("Сүүлд өөрчилсөн огноо", db_column="changed_date", null=True, blank=True)
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
    died = models.CharField("Нас барсан", max_length=12, db_column="died", default="no")
    command_id_value = models.IntegerField(
        "Сүүлийн тушаалын дотоод дугаар", db_column="command_ident", null=True, blank=True
    )
    move_type = models.SmallIntegerField("Сүүлийн шилжилтийн төрөл", db_column="move_type", null=True, blank=True)

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
    # The rest of what INS_EMPHISTORY copied from the employee row (the columns the employee row also has).
    work_phone = models.CharField(max_length=14, db_column="workphone", null=True, blank=True)
    private_phone = models.CharField(max_length=14, db_column="homephone", null=True, blank=True)
    email = models.CharField(max_length=50, db_column="email", null=True, blank=True)
    passport_no = models.CharField(max_length=20, db_column="passport", null=True, blank=True)
    account_no = models.CharField(max_length=20, db_column="ecode", null=True, blank=True)
    social_insurance_no = models.CharField(max_length=14, db_column="ndno", null=True, blank=True)
    health_insurance_no = models.CharField(max_length=14, db_column="emdno", null=True, blank=True)
    prior_service_years = models.SmallIntegerField(db_column="working_year", default=0)
    foreign_emp = models.SmallIntegerField(db_column="foreign_emp", null=True, blank=True)
    citizenship_id_value = models.IntegerField(db_column="country_ident", null=True, blank=True)
    education_level_id_value = models.IntegerField(db_column="education_ident", null=True, blank=True)
    academic_degree_id_value = models.IntegerField(db_column="graduate_ident", null=True, blank=True)
    insured_category_id_value = models.IntegerField(db_column="insur_ident", null=True, blank=True)
    last_order_text = models.CharField(max_length=100, db_column="command_description", null=True, blank=True)

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


class MaterialHelpType(_NamedList):
    """Буцалтгүй тусламжийн үндэслэл (table `material_help_type`)."""

    id = models.AutoField(primary_key=True, db_column="material_help_type_id")
    name = models.CharField("Нэр", max_length=50, db_column="description")

    class Meta(_NamedList.Meta):
        db_table = "material_help_type"
        verbose_name = "Буцалтгүй тусламжийн үндэслэл"


class DisciplineType(_NamedList):
    """Сахилгын шийтгэлийн төрөл (table `discipline_type`)."""

    id = models.AutoField(primary_key=True, db_column="disctype_id")
    name = models.CharField("Нэр", max_length=50, db_column="description")

    class Meta(_NamedList.Meta):
        db_table = "discipline_type"
        verbose_name = "Шийтгэлийн төрөл"


class DriverType(_NamedList):
    """Жолооны ангилал (table `driver_type`)."""

    id = models.AutoField(primary_key=True, db_column="driver_type_id")
    name = models.CharField("Нэр", max_length=30, db_column="description")

    class Meta(_NamedList.Meta):
        db_table = "driver_type"
        verbose_name = "Жолооны ангилал"


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


class RelativeRow(_Table):
    """Ажилтны хамаатан садан (table `relative`). Branch, department and position are optional lookups."""

    id = models.AutoField(primary_key=True, db_column="relative_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    given_name = models.CharField("Нэр", max_length=20, db_column="given_name")
    father_name = models.CharField("Эцэг/эхийн нэр", max_length=20, db_column="father_name", null=True, blank=True)
    job = models.CharField("Ажил", max_length=50, db_column="job", null=True, blank=True)
    phone = models.CharField("Утас", max_length=14, db_column="phone", null=True, blank=True)
    description = models.CharField("Ажилтны хэн болох", max_length=50, db_column="description")
    branch = _ref(Branch, "branch_ident", "Ажилладаг салбар", null=True)
    department = _ref(Department, "dep_ident", "Хэлтэс", null=True)
    position = _ref(Position, "occup_ident", "Албан тушаал", null=True)

    class Meta(_Table.Meta):
        db_table = "relative"
        verbose_name = "Хамаатан садан"


class BeforeWorkRow(_Table):
    """Ажилтны өмнө ажиллаж байсан газар (table `before_work`). Dates are free text, years are numbers."""

    id = models.AutoField(primary_key=True, db_column="id_before")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    worked_place = models.CharField(
        "Өмнө нь ажиллаж байсан газар", max_length=40, db_column="worked_place", null=True, blank=True
    )
    start_text = models.CharField("Орсон", max_length=20, db_column="start_date", null=True, blank=True)
    end_text = models.CharField("Гарсан", max_length=20, db_column="end_date", null=True, blank=True)
    profession = models.CharField("Мэргэжил", max_length=30, db_column="profession", null=True, blank=True)
    shaltgaan = models.CharField("Гарсан шалтгаан", max_length=30, db_column="shaltgaan", null=True, blank=True)
    start_year = models.SmallIntegerField("Орсон он", db_column="start_year")
    end_year = models.SmallIntegerField("Гарсан он", db_column="end_year")

    class Meta(_Table.Meta):
        db_table = "before_work"
        verbose_name = "Өмнө ажилласан газар"


class SkillWorkRow(_Table):
    """Ажилтны ур чадварын даалгавар, норм (table `hr_skillwork`). The key column is `emp_ident`; norm is NOT NULL."""

    id = models.AutoField(primary_key=True, db_column="skillwork_id")
    employee = _ref(Employee, "emp_ident", "Ажилтан")
    description = models.CharField("Даалгавар", max_length=50, db_column="description", null=True, blank=True)
    norm = models.DecimalField("Нормын тоо", max_digits=14, decimal_places=2, db_column="norm")
    department = _ref(Department, "dep_ident", "Хэлтэс", null=True)
    sdate = TimestampDateField("Огноо", db_column="sdate", null=True, blank=True)
    comment = models.CharField("Тайлбар", max_length=100, db_column="comment", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "hr_skillwork"
        verbose_name = "Ур чадварын даалгавар"


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


class MaterialHelpRow(_Table):
    """Ажилтанд олгосон буцалтгүй тусламж (table `material_help`). amount, help_date and material_type are NOT NULL."""

    id = models.AutoField(primary_key=True, db_column="material_help_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    amount = models.DecimalField("Мөнгөний дүн", max_digits=14, decimal_places=2, db_column="amount")
    help_date = TimestampDateField("Огноо", db_column="help_date")
    material_type = _ref(MaterialHelpType, "material_type", "Үндэслэл")
    description = models.CharField("Тайлбар", max_length=100, db_column="description", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "material_help"
        verbose_name = "Буцалтгүй тусламж"


class AwardRow(_Table):
    """Ажилтанд олгосон шагнал (table `awards`). award_name and description are NOT NULL."""

    id = models.AutoField(primary_key=True, db_column="award_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    give_org = models.CharField("Хаанаас", max_length=40, db_column="give_org", null=True, blank=True)
    award_name = models.CharField("Шагналын нэр", max_length=40, db_column="award_name")
    award_date = TimestampDateField("Огноо", db_column="award_date", null=True, blank=True)
    description = models.CharField("Тайлбар", max_length=50, db_column="description")

    class Meta(_Table.Meta):
        db_table = "awards"
        verbose_name = "Шагнал урамшил"


class DisciplineRow(_Table):
    """Ажилтанд оногдуулсан сахилгын шийтгэл (table `discipline`). Type (discipline_name) and date are NOT NULL."""

    id = models.AutoField(primary_key=True, db_column="discipline_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    from_discipline = models.CharField("Хаанаас", max_length=40, db_column="from_discipline", null=True, blank=True)
    discipline_type = _ref(DisciplineType, "discipline_name", "Шийтгэлийн нэр")
    discipline_date = TimestampDateField("Огноо", db_column="discipline_date")
    description = models.CharField("Тайлбар", max_length=50, db_column="description", null=True, blank=True)
    discipline_sal_percent = models.DecimalField(
        "Шийтгэлийн хувь", max_digits=7, decimal_places=2, db_column="discipline_sal_percent", null=True, blank=True
    )
    discipline_enddate = TimestampDateField("Дуусах огноо", db_column="discipline_enddate", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "discipline"
        verbose_name = "Сахилгын шийтгэл"


class ComplaintRow(_Table):
    """Ажилтны эсрэг гаргасан үйлчлүүлэгчийн гомдол (table `hr_complaints`). Date, type and name are NOT NULL.
    ctype and complaint_name are codes from fixed lists (personal_writes.COMPLAINT_TYPES / COMPLAINT_KINDS)."""

    id = models.AutoField(primary_key=True, db_column="complaint_id")
    employee = _ref(Employee, "emp_ident", "Ажилтан")
    cdate = TimestampDateField("Огноо", db_column="cdate")
    ctype = models.SmallIntegerField("Төрөл", db_column="ctype")
    complaint_name = models.SmallIntegerField("Гомдол", db_column="complaint_name")
    comment = models.CharField("Тайлбар", max_length=100, db_column="comment", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "hr_complaints"
        verbose_name = "Үйлчлүүлэгчийн гомдол"


class BodyRow(_Table):
    """Ажилтны эрүүл мэндийн үзлэг (table `body`). Every column is nullable in production.
    The conclusion attribute maps to the column `finally`, which is a Python keyword."""

    id = models.AutoField(primary_key=True, db_column="body_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    inserted_ognoo = TimestampDateField("Үзлэгийн огноо", db_column="inserted_ognoo", null=True, blank=True)
    term_type = models.CharField("Үзлэгийн төрөл", max_length=10, db_column="term_type", null=True, blank=True)
    end_date = TimestampDateField("Дуусах хугацаа", db_column="end_date", null=True, blank=True)
    own_letter = models.CharField("Өөрийн мэдүүлэгээр", max_length=80, db_column="own_letter", null=True, blank=True)
    ear = models.CharField("Чих хамар хоолой", max_length=60, db_column="ear", null=True, blank=True)
    dotor = models.CharField("Дотор", max_length=60, db_column="dotor", null=True, blank=True)
    medrel = models.CharField("Мэдрэл", max_length=60, db_column="medrel", null=True, blank=True)
    setgel_medrel = models.CharField("Сэтгэл мэдрэл", max_length=60, db_column="setgel_medrel", null=True, blank=True)
    mes_zasal = models.CharField("Мэс засал", max_length=60, db_column="mes_zasal", null=True, blank=True)
    nud = models.CharField("Нүд", max_length=60, db_column="nud", null=True, blank=True)
    female = models.CharField("Эмэгтэйчүүд", max_length=60, db_column="female", null=True, blank=True)
    rentgen = models.CharField("Рентген", max_length=60, db_column="rentgen", null=True, blank=True)
    skin = models.CharField("Арьс", max_length=60, db_column="skin", null=True, blank=True)
    conclusion = models.CharField("Дүгнэлт", max_length=60, db_column="finally", null=True, blank=True)
    sign = models.CharField("Гарын үсэг", max_length=40, db_column="sign", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "body"
        verbose_name = "Эрүүл мэндийн үзлэг"


class DriverRow(_Table):
    """Ажилтны жолооны үнэмлэх (table `driver`). drivertype (driver_type) is NOT NULL."""

    id = models.AutoField(primary_key=True, db_column="id_driver")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    number_driver = models.CharField(
        "Үнэмлэхний дугаар", max_length=15, db_column="number_driver", null=True, blank=True
    )
    inserted_ognoo = TimestampDateField("Үнэмлэх авсан огноо", db_column="inserted_ognoo", null=True, blank=True)
    driver_type = _ref(DriverType, "drivertype", "Жолооны ангилал")

    class Meta(_Table.Meta):
        db_table = "driver"
        verbose_name = "Жолоо"


class MilitaryRow(_Table):
    """Цэргийн алба (table `military`). Every column except the employee is optional."""

    id = models.AutoField(primary_key=True, db_column="military_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    army_rank = models.CharField("Цэргийн цол", max_length=20, db_column="army_rank", null=True, blank=True)
    mil_rank = models.CharField("Бэлтгэл зэрэг", max_length=20, db_column="mil_rank", null=True, blank=True)
    study_type = models.CharField("Алба хаасан жил", max_length=20, db_column="study_type", null=True, blank=True)
    sacking_date = TimestampDateField("Халагдсан огноо", db_column="sacking_date", null=True, blank=True)
    sacking_reason = models.CharField(
        "Халагдсан шалтгаан", max_length=50, db_column="sacking_reason", null=True, blank=True
    )

    class Meta(_Table.Meta):
        db_table = "military"
        verbose_name = "Цэргийн алба"


class ArmyRankRow(_Table):
    """Цэргийн цол (table `army_rank`). Every column except the employee is optional."""

    id = models.AutoField(primary_key=True, db_column="rank_id")
    employee = _ref(Employee, "employee_ident", "Ажилтан")
    rank_date = TimestampDateField("Цол олгосон огноо", db_column="rank_date", null=True, blank=True)
    rank = models.CharField("Цэргийн цол", max_length=20, db_column="rank", null=True, blank=True)
    addition_r = models.DecimalField(
        "Нэмэгдлийн хэмжээ", max_digits=14, decimal_places=2, db_column="addition_r", null=True, blank=True
    )

    class Meta(_Table.Meta):
        db_table = "army_rank"
        verbose_name = "Цэргийн цол"


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


class IncomeLevel(_Table):
    """Орлогын түвшин (table `income`): per-person income band, `lower < x <= upper`."""

    id = models.AutoField(primary_key=True, db_column="income_id")
    level = models.CharField("Түвшин", max_length=20, db_column="income_level")
    lower = models.IntegerField("Доод хязгаар", db_column="c1")
    upper = models.IntegerField("Дээд хязгаар", db_column="c2")

    class Meta(_Table.Meta):
        db_table = "income"
        verbose_name = "Орлогын түвшин"
        ordering = ["lower"]


class NazgRow(_Table):
    """Нормативт орон тоо (table `nazg`): budgeted posts per kind, position, branch and year."""

    id = models.AutoField(primary_key=True, db_column="nazg_id")
    kind = models.CharField("Төрөл", max_length=10, db_column="nazg_type")  # Main / Temporary
    qty = models.IntegerField("Тоо", db_column="qty")
    year = models.IntegerField("Он", db_column="rep_year")
    position = _ref(Position, "occupation_ident", "Албан тушаал")
    branch = _ref(Branch, "branch_ident", "Салбар")

    class Meta(_Table.Meta):
        db_table = "nazg"
        verbose_name = "Нормативт орон тоо"


class OccupationKind(_Table):
    """Албан тушаалын ангилал (same table as `Position`, `occupation`): read-only view of the category code."""

    id = models.AutoField(primary_key=True, db_column="occupation_id")
    character = models.CharField("Ангилал", max_length=20, db_column="occupation_character", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "occupation"
        verbose_name = "Албан тушаалын ангилал"


class EmployeeIncomeRow(_Table):
    """Ажилтны орлого (same table as `Employee`, `employee`): read-only view of the income column."""

    id = models.AutoField(primary_key=True, db_column="employee_id")
    income = models.IntegerField("Орлого", db_column="income", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "employee"
        verbose_name = "Ажилтны орлого"


class AddedValStat(_Table):
    """Нэмэгдэх гүйцэтгэлийн үзүүлэлт (table `hr_addedvalstat`): one indicator and its monthly weight (`percentm`)."""

    id = models.AutoField(primary_key=True, db_column="stat_id")
    description = models.CharField("Үзүүлэлт", max_length=50, db_column="description")
    stat_type = models.SmallIntegerField("Төрөл", db_column="stat_type", null=True, blank=True)
    type_descr = models.CharField("Төрлийн тайлбар", max_length=50, db_column="type_descr", null=True, blank=True)
    rownum = models.SmallIntegerField("Дугаар", db_column="rownum", null=True, blank=True)
    percentm = models.DecimalField("Жин (%)", max_digits=14, decimal_places=2, db_column="percentm")

    class Meta(_Table.Meta):
        db_table = "hr_addedvalstat"
        verbose_name = "Нэмэгдэх гүйцэтгэлийн үзүүлэлт"


class AddedValBudgetRow(_Table):
    """Нэмэгдэх гүйцэтгэлийн төлөвлөгөө, биелэлт (table `hr_addedvalbudg`): one row per indicator, person,
    department and year, with 12 monthly budget (norm) and execution columns.

    The production key is composite (stat_ident, byear, emp_ident, dep_ident). `pk` is the composite key;
    never look a row up by `pk` alone, filter by the four fields.
    """

    pk = models.CompositePrimaryKey("stat", "year", "employee", "dep_id")
    stat = models.IntegerField("Үзүүлэлт", db_column="stat_ident")
    year = models.SmallIntegerField("Он", db_column="byear")
    employee = _ref(Employee, "emp_ident", "Ажилтан")
    dep_id = models.SmallIntegerField("Хэлтэс", db_column="dep_ident")
    budget1 = models.DecimalField("Норм 1", max_digits=14, decimal_places=2, db_column="budget1", default=Decimal("0"))
    budget2 = models.DecimalField("Норм 2", max_digits=14, decimal_places=2, db_column="budget2", default=Decimal("0"))
    budget3 = models.DecimalField("Норм 3", max_digits=14, decimal_places=2, db_column="budget3", default=Decimal("0"))
    budget4 = models.DecimalField("Норм 4", max_digits=14, decimal_places=2, db_column="budget4", default=Decimal("0"))
    budget5 = models.DecimalField("Норм 5", max_digits=14, decimal_places=2, db_column="budget5", default=Decimal("0"))
    budget6 = models.DecimalField("Норм 6", max_digits=14, decimal_places=2, db_column="budget6", default=Decimal("0"))
    budget7 = models.DecimalField("Норм 7", max_digits=14, decimal_places=2, db_column="budget7", default=Decimal("0"))
    budget8 = models.DecimalField("Норм 8", max_digits=14, decimal_places=2, db_column="budget8", default=Decimal("0"))
    budget9 = models.DecimalField("Норм 9", max_digits=14, decimal_places=2, db_column="budget9", default=Decimal("0"))
    budget10 = models.DecimalField(
        "Норм 10", max_digits=14, decimal_places=2, db_column="budget10", default=Decimal("0")
    )
    budget11 = models.DecimalField(
        "Норм 11", max_digits=14, decimal_places=2, db_column="budget11", default=Decimal("0")
    )
    budget12 = models.DecimalField(
        "Норм 12", max_digits=14, decimal_places=2, db_column="budget12", default=Decimal("0")
    )
    exec1 = models.DecimalField("Гүйцэтгэл 1", max_digits=14, decimal_places=2, db_column="exec1", default=Decimal("0"))
    exec2 = models.DecimalField("Гүйцэтгэл 2", max_digits=14, decimal_places=2, db_column="exec2", default=Decimal("0"))
    exec3 = models.DecimalField("Гүйцэтгэл 3", max_digits=14, decimal_places=2, db_column="exec3", default=Decimal("0"))
    exec4 = models.DecimalField("Гүйцэтгэл 4", max_digits=14, decimal_places=2, db_column="exec4", default=Decimal("0"))
    exec5 = models.DecimalField("Гүйцэтгэл 5", max_digits=14, decimal_places=2, db_column="exec5", default=Decimal("0"))
    exec6 = models.DecimalField("Гүйцэтгэл 6", max_digits=14, decimal_places=2, db_column="exec6", default=Decimal("0"))
    exec7 = models.DecimalField("Гүйцэтгэл 7", max_digits=14, decimal_places=2, db_column="exec7", default=Decimal("0"))
    exec8 = models.DecimalField("Гүйцэтгэл 8", max_digits=14, decimal_places=2, db_column="exec8", default=Decimal("0"))
    exec9 = models.DecimalField("Гүйцэтгэл 9", max_digits=14, decimal_places=2, db_column="exec9", default=Decimal("0"))
    exec10 = models.DecimalField(
        "Гүйцэтгэл 10", max_digits=14, decimal_places=2, db_column="exec10", default=Decimal("0")
    )
    exec11 = models.DecimalField(
        "Гүйцэтгэл 11", max_digits=14, decimal_places=2, db_column="exec11", default=Decimal("0")
    )
    exec12 = models.DecimalField(
        "Гүйцэтгэл 12", max_digits=14, decimal_places=2, db_column="exec12", default=Decimal("0")
    )

    class Meta(_Table.Meta):
        db_table = "hr_addedvalbudg"
        verbose_name = "Нэмэгдэх гүйцэтгэлийн төлөвлөгөө"
        verbose_name_plural = "Нэмэгдэх гүйцэтгэлийн төлөвлөгөөнүүд"

    def months(self, quarter: int) -> list[tuple[Decimal, Decimal]]:
        """(budget, execution) of the three months of `quarter` (1-4), first month first."""
        if quarter not in (1, 2, 3, 4):
            raise ValueError(f"quarter must be 1-4, got {quarter}")
        first = 3 * (quarter - 1) + 1
        return [(getattr(self, f"budget{n}"), getattr(self, f"exec{n}")) for n in (first, first + 1, first + 2)]


class FactoryAccidentRow(_Table):
    """Үйлдвэрлэлийн осол, хортой нөлөөлөл (table `factory_accident`). `kind` is `accident` or `toxic`."""

    id = models.AutoField(primary_key=True, db_column="faccident_id")
    kind = models.CharField("Төрөл", max_length=50, db_column="faccident")
    type_code = models.IntegerField(
        "Ослын төрлийн код", db_column="faccident_type", default=0
    )  # NOT NULL in production
    employee = _ref(Employee, "empid", "Ажилтан")
    accident_date = TimestampDateField("Огноо", db_column="accident_date")
    group_accident = models.SmallIntegerField("Бүлэг", db_column="group_accident", null=True, blank=True)
    facc_type = models.SmallIntegerField("Ослын төрөл", db_column="facc_type")
    facc_reason = models.SmallIntegerField("Ослын шалтгаан", db_column="facc_reason")
    facc_result = models.SmallIntegerField("Ослын үр дагавар", db_column="facc_result")
    name = models.CharField("Нэр", max_length=100, db_column="name")
    description = models.CharField("Тайлбар", max_length=150, db_column="description", null=True, blank=True)
    branch = _ref(Branch, "branch_ident", "Салбар", null=True)

    class Meta(_Table.Meta):
        db_table = "factory_accident"
        verbose_name = "Үйлдвэрлэлийн осол"


class LoanRefRow(_Table):
    """Зээлийн үндэслэл (table `loan_refs`)."""

    id = models.AutoField(primary_key=True, db_column="ref_id")
    description = models.CharField("Нэр", max_length=100, db_column="description")

    class Meta(_Table.Meta):
        db_table = "loan_refs"
        verbose_name = "Зээлийн үндэслэл"


class LoanRow(_Table):
    """Ажилтны зээл (table `hr_loan`). Read only here."""

    id = models.AutoField(primary_key=True, db_column="loan_id")
    employee = _ref(Employee, "emp_ident", "Ажилтан")
    get_date = TimestampDateField("Авсан огноо", db_column="get_date", null=True, blank=True)
    end_date = TimestampDateField("Дуусах огноо", db_column="end_date", null=True, blank=True)
    amount = models.DecimalField("Зээлийн дүн", max_digits=14, decimal_places=2, db_column="amount")
    pay_permonth = models.DecimalField("Сарын төлбөр", max_digits=14, decimal_places=2, db_column="pay_permonth")
    loan_ref = _ref(LoanRefRow, "loanref1_ident", "Үндэслэл", null=True)

    class Meta(_Table.Meta):
        db_table = "hr_loan"
        verbose_name = "Ажилтны зээл"


class InfoRow(_Table):
    """Байгууллагын мэдээлэл (table `info`): only the key and the organisation type code are mirrored."""

    register_no = models.CharField("Регистрийн дугаар", max_length=20, db_column="registerno", primary_key=True)
    orgtype_code = models.CharField("Байгууллагын төрөл", max_length=2, db_column="orgtype_code", null=True, blank=True)

    class Meta(_Table.Meta):
        db_table = "info"
        verbose_name = "Байгууллагын мэдээлэл"


class EmployeeGradeRow(_Table):
    """Ажилтны зэрэглэлийн хувь (same table as `Employee`, `employee`): read-only view of `grade_perc`."""

    id = models.AutoField(primary_key=True, db_column="employee_id")
    grade_perc = models.DecimalField(
        "Зэргийн хувь", max_digits=7, decimal_places=2, db_column="grade_perc", default=Decimal("0")
    )

    class Meta(_Table.Meta):
        db_table = "employee"
        verbose_name = "Ажилтны зэрэглэлийн хувь"
