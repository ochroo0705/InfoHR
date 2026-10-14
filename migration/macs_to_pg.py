"""Copy the HR/payroll part of the MACS XE4 Firebird database into PostgreSQL.

Source: a working copy of MACSXE4DB.FDB, opened embedded (no server login).
Target: PostgreSQL database `info_hr`, schema `macs_legacy`. All names lowercase.
Table selection: docs/migration/table-selection.md.

The postgres password is read by libpq from %APPDATA%\\postgresql\\pgpass.conf
(or PGPASSWORD); it is never stored in this script.

Usage:
    python migration/macs_to_pg.py
"""

import os
import re
import shutil
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_values
from firebird.driver import connect as fb_connect, driver_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FB_DB = os.path.join(ROOT, "db", "work", "MACS_COPY.FDB")
FB_CLIENT = r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll"
ISQL = r"C:\Program Files\Firebird\Firebird_3_0\isql.exe"
PG = dict(host="localhost", port=5432, user="postgres")
PG_DB = "info_hr"
SCHEMA = "macs_legacy"
REPORT = os.path.join(ROOT, "docs", "migration", "migration-report.md")
LOGIC_DIR = os.path.join(ROOT, "docs", "migration", "legacy-logic")

# Groups A-E from table-selection.md (Group E as decided 2026-10-13).
TABLES = {
    "A": "EMPLOYEE EMPLOYEE_HISTORY EMP_PHOTO EMP_VACATION FAMILY FAMILY_MEMBERS "
         "EMP_TT11SUM EMP_COLNAMES EMP_ACTTYPE TIME_TABLENEW MONTH_DAYS ADDITIONAL_INFO",
    "B": "MONTHSALARY MONTHSALARY_NEW MONTHSALARY_STATUS COLNAMES COLNAMES_VERSION COLEXPR "
         "INSUR_COLNAMES INSUR_COLEXPR INSUR_TYPE NDSH_CONFIG SALARY_EMAIL_COLUMNS "
         "SALREPORTS SALREPORT_FIELDS",
    "C": "BRANCH DEPS OCCUPATION OCCUP_CLASS BANKS COUNTRY CITYTOWN DISTRICT EDUCATION "
         "GRADUATE WORK_SKILL",
    "D": "ADDRESS APARTMENT_COND ARMY_RANK AWARDS BEFORE_WORK BIRTH_PLACE BODY CAROWN_COND "
         "CAUSE_DAY CHECKINOUT CLOTHES_SIZE_TYPE COMMAND DEGREE DISCIPLINE DISCIPLINE_TYPE EDUC "
         "EMP_BONUS EMP_GRADE EMP_INSTYPES EMP_TALENTS ENTITLEMENT FACTORY_ACCIDENT "
         "FACTORY_ACCIDENT_TYPE FINGERPRINT FIRED_REASON FLANGUAGES FOREIGN_LANG GARNISHCHANGE "
         "GARNISHCHANGE_DETAIL GARNISHCHANGE_ITEM GARNISH_HISTORY GIVEN_PRESENT HOLIDAY "
         "HOLIDAY_SCHEDULE HOLIDAY_TYPE HR_ABSENTS HR_ADDEDVALBUDG HR_ADDEDVALSTAT HR_COMPLAINTS "
         "HR_LEGALHOLIDAYS HR_LOAN HR_OFFICE HR_SECTION HR_SKILLWORK HR_TEMPLATE HR_TEMPLATEWORDS "
         "HR_TRAINING LANG_LEVEL LEAVE_ASSIGN LEAVE_TYPE LOAN_REFS MARITAL_STATUS MATERIAL_HELP "
         "MATERIAL_HELP_TYPE MILITARY MONTHDECREASE MOVEMENT NATIONALITY NIIGMIIN_GARAL PERSONTIME "
         "PRESENT_TYPE PROFESSION_TYPE QUALIFICATION QUALIFICATION_TYPE RELATIVE SCHEDULE SHIFTS "
         "SPEC_EDU SPEC_EDU_TYPE TALENTS TIME_TABLE VOTING_WORK",
    "E": "CUSTOMER EMP_WORKS WORKS SERVCARDS EMP_WORKPERCENT EMP_ASSETS CONTRACTS REST_TIMES "
         "MACS_OPTIONS INFO",
}
SELECTED = {t: g for g, names in TABLES.items() for t in names.split()}

# CUSTOMER holds real customers too: copy only rows that selected tables point to.
FILTERED = {"CUSTOMER"}

# Procedures/triggers whose source mentions any of these are saved as text for rule reading.
LOGIC_KEYWORDS = ("MONTHSALARY", "COLEXPR", "COLNAMES", "NDSH", "INSUR", "SALARY", "EMPLOYEE",
                  "VACATION", "HOLIDAY", "MONTH_DAYS", "TIME_TABLE", "ХХОАТ", "НДШ")

# Firebird RDB$FIELD_TYPE codes
FB_SMALLINT, FB_INTEGER, FB_FLOAT, FB_DATE, FB_TIME, FB_CHAR, FB_BIGINT, FB_BOOLEAN = 7, 8, 10, 12, 13, 14, 16, 23
FB_DOUBLE, FB_TIMESTAMP, FB_VARCHAR, FB_BLOB = 27, 35, 37, 261


def pg_type(ftype, subtype, length, char_len, precision, scale):
    # Dialect 1 stores declared NUMERIC(p,s) above 9 digits as double, and values can exceed the
    # declared size; those fall through to unconstrained numeric below.
    if scale and scale < 0 and ftype in (FB_SMALLINT, FB_INTEGER, FB_BIGINT):
        return f"numeric({precision or 18},{-scale})"
    if ftype == FB_SMALLINT:
        return "smallint"
    if ftype == FB_INTEGER:
        return "integer"
    if ftype == FB_BIGINT:
        return "bigint"
    if ftype in (FB_FLOAT, FB_DOUBLE):
        # Dialect 1 stores many money fields as floating point; keep them exact as numeric.
        return "numeric"
    if ftype == FB_DATE:
        return "date"
    if ftype == FB_TIME:
        return "time"
    if ftype == FB_TIMESTAMP:
        return "timestamp"  # dialect 1 DATE = date + time
    if ftype in (FB_CHAR, FB_VARCHAR):
        return f"varchar({char_len or length})"
    if ftype == FB_BOOLEAN:
        return "boolean"
    if ftype == FB_BLOB:
        return "text" if subtype == 1 else "bytea"
    raise ValueError(f"unmapped Firebird type {ftype}")


def fetch_all(cur, query, params=()):
    cur.execute(query, params)
    return cur.fetchall()


def read_columns(fcur, table):
    rows = fetch_all(fcur, """
        SELECT TRIM(rf.RDB$FIELD_NAME), f.RDB$FIELD_TYPE, f.RDB$FIELD_SUB_TYPE, f.RDB$FIELD_LENGTH,
               f.RDB$CHARACTER_LENGTH, f.RDB$FIELD_PRECISION, f.RDB$FIELD_SCALE,
               COALESCE(rf.RDB$NULL_FLAG, f.RDB$NULL_FLAG, 0),
               IIF(f.RDB$COMPUTED_BLR IS NULL, 0, 1)
        FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
        WHERE rf.RDB$RELATION_NAME = ? ORDER BY rf.RDB$FIELD_POSITION""", (table,))
    return [dict(name=r[0], type=pg_type(*r[1:7]), notnull=bool(r[7]), computed=bool(r[8]),
                 is_char=r[1] in (FB_CHAR, FB_VARCHAR), is_blob=r[1] == FB_BLOB)
            for r in rows]


def read_keys(fcur):
    """Primary keys {table: [cols]} and foreign keys [(name, table, [cols], ref_table, [ref_cols])]."""
    seg = """SELECT TRIM(s.RDB$FIELD_NAME) FROM RDB$INDEX_SEGMENTS s
             WHERE s.RDB$INDEX_NAME = ? ORDER BY s.RDB$FIELD_POSITION"""
    pks = {}
    for table, idx in fetch_all(fcur, """
            SELECT TRIM(RDB$RELATION_NAME), TRIM(RDB$INDEX_NAME) FROM RDB$RELATION_CONSTRAINTS
            WHERE RDB$CONSTRAINT_TYPE = 'PRIMARY KEY'"""):
        pks[table] = [r[0] for r in fetch_all(fcur, seg, (idx,))]
    fks = []
    for name, table, idx, ref_table, ref_idx in fetch_all(fcur, """
            SELECT TRIM(rc.RDB$CONSTRAINT_NAME), TRIM(rc.RDB$RELATION_NAME), TRIM(rc.RDB$INDEX_NAME),
                   TRIM(rc2.RDB$RELATION_NAME), TRIM(rc2.RDB$INDEX_NAME)
            FROM RDB$RELATION_CONSTRAINTS rc
            JOIN RDB$REF_CONSTRAINTS r ON r.RDB$CONSTRAINT_NAME = rc.RDB$CONSTRAINT_NAME
            JOIN RDB$RELATION_CONSTRAINTS rc2 ON rc2.RDB$CONSTRAINT_NAME = r.RDB$CONST_NAME_UQ"""):
        fks.append((name, table, [r[0] for r in fetch_all(fcur, seg, (idx,))],
                    ref_table, [r[0] for r in fetch_all(fcur, seg, (ref_idx,))]))
    return pks, fks


def convert(value, col):
    if value is None:
        return None
    if hasattr(value, "read"):  # streamed BLOB
        value = value.read()
    if col["type"] == "numeric" and isinstance(value, float):
        return Decimal(repr(value))
    if col["is_char"] and isinstance(value, str):
        return value.rstrip()
    if col["type"] == "date" and isinstance(value, datetime):
        return value.date()
    return value


def ident(name):
    return sql.Identifier(name.lower())


def filter_clause(table, fks):
    """WHERE clause keeping only rows referenced from other selected tables."""
    refs = [(t, cols, rcols) for _, t, cols, rt, rcols in fks
            if rt == table and t in SELECTED and t not in FILTERED and len(cols) == 1]
    parts = [f"{rcols[0]} IN (SELECT {cols[0]} FROM {t} WHERE {cols[0]} IS NOT NULL)"
             for t, cols, rcols in refs]
    return " OR ".join(parts) if parts else "1=0"


def dump_logic():
    """Save procedure/trigger source via `isql -x`.

    Reading RDB$PROCEDURE_SOURCE through firebird-driver crashes the process, so the
    source comes from isql's metadata export instead. isql emits each procedure twice
    (an empty stub, then the real body); the last occurrence wins.
    """
    ddl = subprocess.run([ISQL, "-user", "SYSDBA", "-x", "-ch", "NONE", FB_DB],
                         capture_output=True).stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")
    blocks = {}
    for m in re.finditer(r"^(CREATE OR ALTER PROCEDURE|ALTER PROCEDURE|CREATE TRIGGER) (\S+).*?\^$", ddl, re.M | re.S):
        kind = "procedures" if "PROCEDURE" in m.group(1) else "triggers"
        blocks[(kind, m.group(2))] = m.group(0)
    shutil.rmtree(LOGIC_DIR, ignore_errors=True)
    saved = []
    for (kind, name), src in sorted(blocks.items()):
        if any(k in src.upper() for k in LOGIC_KEYWORDS):
            os.makedirs(os.path.join(LOGIC_DIR, kind), exist_ok=True)
            with open(os.path.join(LOGIC_DIR, kind, f"{name}.sql"), "w", encoding="utf-8") as fh:
                fh.write(src + "\n")
            saved.append((kind, name))
    return saved


def ensure_database():
    con = psycopg2.connect(dbname="postgres", **PG)
    con.autocommit = True
    with con.cursor() as c:
        c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DB,))
        if not c.fetchone():
            c.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(ident(PG_DB)))
    con.close()


def main():
    # isql must run before the embedded connection opens: embedded mode locks the file.
    logic = dump_logic()

    driver_config.fb_client_library.value = FB_CLIENT
    driver_config.stream_blob_threshold.value = 64 * 1024 * 1024
    fcon = fb_connect(FB_DB, user="SYSDBA", charset="UTF8")
    fcur = fcon.cursor()

    ensure_database()
    pcon = psycopg2.connect(dbname=PG_DB, **PG)
    pcur = pcon.cursor()
    pcur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(ident(SCHEMA)))
    pcur.execute(sql.SQL("CREATE SCHEMA {}").format(ident(SCHEMA)))

    pks, fks = read_keys(fcur)
    results, notes = [], []

    for table in sorted(SELECTED):
        cols = read_columns(fcur, table)
        if not cols:
            notes.append(f"{table}: not found in source, skipped")
            continue
        defs = [sql.SQL("{} {}{}").format(ident(c["name"]), sql.SQL(c["type"]),
                                          sql.SQL(" NOT NULL" if c["notnull"] else "")) for c in cols]
        if table in pks:
            defs.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(ident, pks[table]))))
        pcur.execute(sql.SQL("CREATE TABLE {}.{} ({})").format(ident(SCHEMA), ident(table),
                                                             sql.SQL(", ").join(defs)))
        computed = [c["name"] for c in cols if c["computed"]]
        if computed:
            notes.append(f"{table}: computed columns copied as plain values: {', '.join(computed)}")

        where = filter_clause(table, fks) if table in FILTERED else "1=1"
        fcur.execute(f"SELECT {', '.join(c['name'] for c in cols)} FROM {table} WHERE {where}")
        rows = [tuple(convert(v, c) for v, c in zip(r, cols)) for r in fcur.fetchall()]
        if rows:
            execute_values(pcur, sql.SQL("INSERT INTO {}.{} ({}) VALUES %s").format(
                ident(SCHEMA), ident(table), sql.SQL(", ").join(ident(c["name"]) for c in cols)
            ).as_string(pcur), rows, page_size=1000)
        pcur.execute(sql.SQL("SELECT COUNT(*) FROM {}.{}").format(ident(SCHEMA), ident(table)))
        results.append((SELECTED[table], table, len(cols), len(rows), pcur.fetchone()[0]))
        pcon.commit()

    fk_added, fk_skipped = 0, []
    for name, table, cols, ref_table, ref_cols in fks:
        if table not in SELECTED:
            continue
        if ref_table not in SELECTED:
            fk_skipped.append(f"{table}({', '.join(cols)}) -> {ref_table}: target not migrated")
            continue
        try:
            pcur.execute(sql.SQL("ALTER TABLE {}.{} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {}.{} ({})").format(
                ident(SCHEMA), ident(table), ident(name), sql.SQL(", ").join(map(ident, cols)),
                ident(SCHEMA), ident(ref_table), sql.SQL(", ").join(map(ident, ref_cols))))
            pcon.commit()
            fk_added += 1
        except psycopg2.Error as e:
            pcon.rollback()
            fk_skipped.append(f"{table}({', '.join(cols)}) -> {ref_table}: {e.pgerror.strip().splitlines()[0]}")

    pcon.close()
    write_report(results, notes, fk_added, fk_skipped, logic)
    bad = [r for r in results if r[3] != r[4]]
    print(f"{len(results)} tables, {sum(r[4] for r in results)} rows, {fk_added} FKs, "
          f"{len(fk_skipped)} FKs skipped, {len(logic)} logic files; mismatches: {len(bad)}")
    return 1 if bad else 0


def write_report(results, notes, fk_added, fk_skipped, logic):
    lines = [
        "# MACS → PostgreSQL migration report", "",
        f"Run: {datetime.now():%Y-%m-%d %H:%M}. Source `db/work/MACS_COPY.FDB` → "
        f"PostgreSQL `{PG_DB}`, schema `{SCHEMA}`. Generated by `migration/macs_to_pg.py`.", "",
        f"- Tables: {len(results)}", f"- Rows: {sum(r[4] for r in results)}",
        f"- Foreign keys added: {fk_added}; skipped: {len(fk_skipped)}",
        f"- Stored procedures/triggers saved as text: {len(logic)} (in `docs/migration/legacy-logic/`)", "",
        "## Tables", "", "| Group | Table | Columns | Rows read | Rows in PG |", "| --- | --- | --- | --- | --- |",
    ]
    lines += [f"| {g} | {t.lower()} | {c} | {r} | {p} |" for g, t, c, r, p in sorted(results)]
    lines += ["", "## Notes", ""] + [f"- {n}" for n in notes or ["(none)"]]
    lines += ["", "## Foreign keys not created", ""] + [f"- {s}" for s in fk_skipped or ["(none)"]]
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    # Exit hard: closing the embedded firebird-driver connection hangs on this setup.
    code = main()
    sys.stdout.flush()
    os._exit(code)
