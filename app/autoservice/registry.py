"""The directories (reference lists) the API serves, read straight from the MACS tables.

Read-only SQL, not Django models: the tables belong to MACS (Django never creates or alters them) and an ORM
model would add migration state to the app. Table and column names below are constants of this file, never
request input, so they are safe to put in SQL; request values only ever travel as query parameters.
"""

from dataclasses import dataclass

MAX_LIMIT = 500
DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class Directory:
    table: str
    pk: str
    columns: dict[str, str]  # output key -> column
    search: tuple[str, ...] = ()  # text columns `?q=` looks in
    order: str = ""  # default: the primary key
    where: str = ""  # a fixed condition (a constant of this file) that limits the rows, e.g. only mechanics


def _d(
    table: str, pk: str, columns: dict[str, str], search: tuple[str, ...] = (), order: str = "", where: str = ""
) -> Directory:
    return Directory(table, pk, columns, search, order or pk, where)


DIRECTORIES: dict[str, Directory] = {
    "car-types": _d(
        "CAR_TYPE", "CARTYPE_ID", {"id": "CARTYPE_ID", "name": "DESCRIPTION"}, ("DESCRIPTION",), "DESCRIPTION"
    ),
    "car-manufacturers": _d(
        "MANUF_REF", "MANUF_ID", {"id": "MANUF_ID", "name": "DESCRIPTION"}, ("DESCRIPTION",), "DESCRIPTION"
    ),
    "car-makes": _d(
        "CAR_REF",
        "CAR_ID",
        {"id": "CAR_ID", "name": "DESCRIPTION", "manufacturer_id": "MANUF_IDENT", "car_type_id": "CARTYPE_IDENT"},
        ("DESCRIPTION",),
        "DESCRIPTION",
    ),
    "car-models": _d(
        "CAR_MODEL",
        "MODEL_ID",
        {
            "id": "MODEL_ID",
            "model": "MODEL_NUM",
            "engine": "MOTOR_NUM",
            "manufacturer_id": "MANUF_IDENT",
            "car_id": "CAR_IDENT",
            "from": "YYMM1",
            "to": "YYMM2",
            "note": "NOTE",
        },
        ("MODEL_NUM", "MOTOR_NUM"),
        "MODEL_NUM",
    ),
    "cars": _d(
        "CARS",
        "CARS_ID",
        {
            "id": "CARS_ID",
            "plate": "CAR_NO",
            "vin": "VIN_NUMBER",
            "body_no": "KUZOV_NO",
            "engine_no": "ENGINE_NUMBER",
            "engine_type": "ENGINE_TYPE",
            "color": "CAR_COLOR",
            "year": "MAKE_YEAR",
            "car_id": "CAR_IDENT",
            "owner_id": "REQCUST_IDENT",
            "owner_name": "REQCUST_NAME",
            "owner_phone": "REQCUST_PHONE",
        },
        ("CAR_NO", "VIN_NUMBER", "REQCUST_NAME"),
        "CAR_NO",
    ),
    "customers": _d(
        "CUSTOMER",
        "CUST_ID",
        {
            "id": "CUST_ID",
            "name": "DESCRIPTION",
            "code": "CODE",
            "register": "REGISTER",
            "phone": "PHONE",
            "address": "ADDRESS",
        },
        ("DESCRIPTION", "CODE", "REGISTER", "PHONE"),
        "DESCRIPTION",
    ),
    "work-types": _d(
        "WORKS_TYPE", "WORKSTYPE_ID", {"id": "WORKSTYPE_ID", "name": "DESCRIPTION"}, ("DESCRIPTION",), "DESCRIPTION"
    ),
    "works": _d(
        "WORKS",
        "WORK_ID",
        {
            "id": "WORK_ID",
            "code": "CODE",
            "name": "DESCRIPTION",
            "short_name": "SHORTNAME",
            "unit": "WORK_UNIT",
            "price": "PRICE",
            "sale_price": "SALE_PRICE",
            "work_type_id": "WORKSTYPE_IDENT",
            "kind": "WORK_TYPE",  # 1 Төмрийн, 2 Замаск, 3 Будаг, other Бусад (FINISH_SERVCARDS)
            "car_type_id": "CARTYPE_IDENT",
            "norm_days": "NORM_DAYS",
            "max_days": "MAX_DAY",
        },
        ("DESCRIPTION", "CODE", "SHORTNAME"),
        "DESCRIPTION",
    ),
    "item-classes": _d(
        "ITEMCLASS", "ITEMCLASS_ID", {"id": "ITEMCLASS_ID", "name": "NAME", "code": "CODE"}, ("NAME", "CODE"), "NAME"
    ),
    "units": _d(
        "ITEMUNIT",
        "ITEMUNIT_ID",
        {"id": "ITEMUNIT_ID", "short_name": "SHORTNAME", "name": "NAME"},
        ("NAME", "SHORTNAME"),
        "NAME",
    ),
    "items": _d(
        "ITEM",
        "ITEM_ID",
        {
            "id": "ITEM_ID",
            "code": "ITEMCODE",
            "name": "DESCRIPTION",
            "barcode": "BARCODE",
            "price": "PRICE",
            "cost": "COST",
            "on_hand": "ONHAND",
            "class_id": "ITEMCLASS",
        },
        ("DESCRIPTION", "ITEMCODE", "BARCODE"),
        "DESCRIPTION",
    ),
    "accounts": _d(
        "ACCOUNT",
        "ACCNO",
        {
            "number": "ACCNO",
            "name": "DESCRIPTION",
            "type": "ACCOUNT_TYPE",
            "bank_name": "BANKNAME",
            "bank_number": "BANKNUMBER",
            "currency_id": "VALCODE",
            "branch_id": "BRANCH_IDENT",
        },
        ("ACCNO", "DESCRIPTION"),
    ),
    "discount-cards": _d(
        "DIS_CARD",
        "DISCOUNT_CARD",
        {
            "id": "DISCOUNT_CARD",
            "card_no": "CARDNO",
            "percent": "DISCOUNT_PERCENT",
            "owner_name": "OWNERNAME",
            "customer_id": "CUST_IDENT",
            "plate": "CAR_NO",
            "phone": "PHONENUMBER",
            "valid_since": "VALID_SINCE",
            "expires": "EXPIRE_DATE",
        },
        ("CARDNO", "OWNERNAME", "CAR_NO"),
        "CARDNO",
    ),
    "employees": _d(
        "EMPLOYEE",
        "EMPLOYEE_ID",
        {
            "id": "EMPLOYEE_ID",
            "name": "FULLNAME",
            "position": "POST",
            "department_id": "DEP_IDENT",
            "phone": "WORKPHONE",
            "status": "STATUS",
        },
        ("FULLNAME", "POST"),
        "FULLNAME",
    ),
    # Mechanics are customers flagged as employees: SERVJOBS.EMP_IDENT and EMP_WORKS.EMP_IDENT point at CUSTOMER.
    "mechanics": _d(
        "CUSTOMER",
        "CUST_ID",
        {"id": "CUST_ID", "name": "DESCRIPTION", "code": "CODE"},
        ("DESCRIPTION", "CODE"),
        "DESCRIPTION",
        "EMPLOYEE = 'yes'",
    ),
    "branches": _d(
        "BRANCH",
        "BRANCH_ID",
        {"id": "BRANCH_ID", "name": "DESCRIPTION", "phone": "PHONE", "address": "ADDRESS"},
        ("DESCRIPTION",),
        "DESCRIPTION",
    ),
    "warehouses": _d(
        "WAREHOUSE", "WARE_ID", {"id": "WARE_ID", "name": "NAME", "code": "WCODE"}, ("NAME", "WCODE"), "NAME"
    ),
    # Logins, without the password columns.
    "users": _d(
        "SECURITY",
        "USER_NAME",
        {"username": "USER_NAME", "rights": "RGHT", "email": "EMAIL", "branch_id": "BRANCH_IDENT"},
        ("USER_NAME",),
    ),
}
