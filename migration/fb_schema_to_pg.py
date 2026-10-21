"""Copy the full MACS XE4 structure (no data) from Firebird into an empty PostgreSQL database.

Source: the working copy `db/work/MACS_COPY.FDB` (structural copy of production, fake data).
Target: PostgreSQL database `macs_pg`, schema `public`. All names lowercase.
Copies every user table with columns, NOT NULL, defaults, primary/unique keys, indexes,
foreign keys (with ON DELETE/UPDATE rules), CHECK constraints and generators (as sequences,
wired as the column default where a trigger filled the ID from one). Triggers and stored
procedures are NOT copied: their rules are enforced in the HR code (D-018); their source is
in `docs/migration/legacy-logic/` and `docs/migration/firebird-rules-audit.md`.

The postgres password is read by libpq from %APPDATA%\\postgresql\\pgpass.conf (or PGPASSWORD).

Usage:
    python migration/fb_schema_to_pg.py            # refuses if macs_pg already exists
    python migration/fb_schema_to_pg.py --replace  # drops and recreates macs_pg
"""

import os
import re
import sys
from datetime import datetime

import psycopg2
from firebird.driver import connect as fb_connect
from firebird.driver import driver_config
from macs_to_pg import FB_CLIENT, FB_DB, PG, ROOT, fetch_all, ident, read_columns
from psycopg2 import sql

PG_DB = "macs_pg"
REPORT = os.path.join(ROOT, "docs", "migration", "macs-pg-structure-report.md")
SCHEMA_SQL = os.path.join(ROOT, "db", "schema", "macs_public.sql")

# Trigger bodies like "NEW.EMPLOYEE_ID = GEN_ID(GEN_EMPLOYEEID, 1)" tell which generator fills which column.
GEN_FILL = re.compile(r"NEW\.(\w+)\s*=\s*GEN_ID\s*\(\s*(\w+)\s*,\s*1\s*\)", re.I)


def blob(value):
    if value is not None and hasattr(value, "read"):
        value = value.read()
    return value.strip() if isinstance(value, str) else value


def pg_expr(src):
    """Firebird expression -> PostgreSQL. Dialect 1 double quotes are string literals."""
    src = re.sub(r'"([^"]*)"', lambda m: "'" + m.group(1).replace("'", "''") + "'", src)
    src = re.sub(r"\bCURRENT_TIMESTAMP\b|'NOW'", "CURRENT_TIMESTAMP", src, flags=re.I)
    return src


def lower_outside_quotes(src):
    """Lowercase identifiers so they match the lowercase columns; string literals keep their case."""
    return "".join(part if i % 2 else part.lower() for i, part in enumerate(re.split(r"('(?:[^']|'')*')", src)))


def read_tables(fcur):
    return [
        r[0]
        for r in fetch_all(
            fcur,
            """
        SELECT TRIM(RDB$RELATION_NAME) FROM RDB$RELATIONS
        WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0 AND RDB$VIEW_BLR IS NULL ORDER BY 1""",
        )
    ]


def read_defaults(fcur):
    rows = fetch_all(
        fcur,
        """
        SELECT TRIM(rf.RDB$RELATION_NAME), TRIM(rf.RDB$FIELD_NAME),
               COALESCE(rf.RDB$DEFAULT_SOURCE, f.RDB$DEFAULT_SOURCE)
        FROM RDB$RELATION_FIELDS rf JOIN RDB$FIELDS f ON f.RDB$FIELD_NAME = rf.RDB$FIELD_SOURCE
        WHERE COALESCE(rf.RDB$SYSTEM_FLAG, 0) = 0""",
    )
    out = {}
    for table, col, src in rows:
        src = blob(src)
        if src:
            out[(table, col)] = re.sub(r"^DEFAULT\s+", "", src, flags=re.I)
    return out


def read_constraints(fcur):
    """Primary/unique keys and foreign keys with their rules."""
    seg = """SELECT TRIM(RDB$FIELD_NAME) FROM RDB$INDEX_SEGMENTS
             WHERE RDB$INDEX_NAME = ? ORDER BY RDB$FIELD_POSITION"""
    keys = []
    for name, table, kind, idx in fetch_all(
        fcur,
        """
            SELECT TRIM(RDB$CONSTRAINT_NAME), TRIM(RDB$RELATION_NAME), TRIM(RDB$CONSTRAINT_TYPE),
                   TRIM(RDB$INDEX_NAME)
            FROM RDB$RELATION_CONSTRAINTS WHERE RDB$CONSTRAINT_TYPE IN ('PRIMARY KEY', 'UNIQUE')""",
    ):
        keys.append((name, table, kind, [r[0] for r in fetch_all(fcur, seg, (idx,))], idx))
    fks = []
    for name, table, idx, ref_table, ref_idx, on_del, on_upd in fetch_all(
        fcur,
        """
            SELECT TRIM(rc.RDB$CONSTRAINT_NAME), TRIM(rc.RDB$RELATION_NAME), TRIM(rc.RDB$INDEX_NAME),
                   TRIM(rc2.RDB$RELATION_NAME), TRIM(rc2.RDB$INDEX_NAME),
                   TRIM(r.RDB$DELETE_RULE), TRIM(r.RDB$UPDATE_RULE)
            FROM RDB$RELATION_CONSTRAINTS rc
            JOIN RDB$REF_CONSTRAINTS r ON r.RDB$CONSTRAINT_NAME = rc.RDB$CONSTRAINT_NAME
            JOIN RDB$RELATION_CONSTRAINTS rc2 ON rc2.RDB$CONSTRAINT_NAME = r.RDB$CONST_NAME_UQ""",
    ):
        fks.append(
            (
                name,
                table,
                [r[0] for r in fetch_all(fcur, seg, (idx,))],
                ref_table,
                [r[0] for r in fetch_all(fcur, seg, (ref_idx,))],
                on_del,
                on_upd,
            )
        )
    # Plain indexes (not backing a constraint).
    indexes = []
    for name, table, unique in fetch_all(
        fcur,
        """
            SELECT TRIM(i.RDB$INDEX_NAME), TRIM(i.RDB$RELATION_NAME), COALESCE(i.RDB$UNIQUE_FLAG, 0)
            FROM RDB$INDICES i
            WHERE COALESCE(i.RDB$SYSTEM_FLAG, 0) = 0 AND i.RDB$EXPRESSION_BLR IS NULL
              AND NOT EXISTS (SELECT 1 FROM RDB$RELATION_CONSTRAINTS c WHERE c.RDB$INDEX_NAME = i.RDB$INDEX_NAME)""",
    ):
        indexes.append((name, table, bool(unique), [r[0] for r in fetch_all(fcur, seg, (name,))]))
    return keys, fks, indexes


def read_checks(fcur):
    rows = fetch_all(
        fcur,
        """
        SELECT DISTINCT TRIM(rc.RDB$CONSTRAINT_NAME), TRIM(rc.RDB$RELATION_NAME), t.RDB$TRIGGER_SOURCE
        FROM RDB$RELATION_CONSTRAINTS rc
        JOIN RDB$CHECK_CONSTRAINTS cc ON cc.RDB$CONSTRAINT_NAME = rc.RDB$CONSTRAINT_NAME
        JOIN RDB$TRIGGERS t ON t.RDB$TRIGGER_NAME = cc.RDB$TRIGGER_NAME
        WHERE rc.RDB$CONSTRAINT_TYPE = 'CHECK'""",
    )
    seen, out = set(), []
    for name, table, src in rows:
        if name not in seen:  # each CHECK has an insert and an update trigger
            seen.add(name)
            out.append((name, table, blob(src)))
    return out


def read_generators(fcur):
    gens = {}
    for name in [
        r[0]
        for r in fetch_all(
            fcur,
            """
            SELECT TRIM(RDB$GENERATOR_NAME) FROM RDB$GENERATORS WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0""",
        )
    ]:
        gens[name] = fetch_all(fcur, f'SELECT GEN_ID("{name}", 0) FROM RDB$DATABASE')[0][0]  # noqa: S608  -- names come from the Firebird catalog
    fills = {}
    for table, src in fetch_all(
        fcur,
        """
            SELECT TRIM(RDB$RELATION_NAME), RDB$TRIGGER_SOURCE FROM RDB$TRIGGERS
            WHERE COALESCE(RDB$SYSTEM_FLAG, 0) = 0 AND RDB$RELATION_NAME IS NOT NULL
              AND RDB$TRIGGER_TYPE = 1""",
    ):
        for col, gen in GEN_FILL.findall(blob(src) or ""):
            fills[(table, col.upper())] = gen.upper()
    return gens, fills


def recreate_database(replace):
    con = psycopg2.connect(dbname="postgres", **PG)
    con.autocommit = True
    with con.cursor() as c:
        c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (PG_DB,))
        if c.fetchone():
            if not replace:
                sys.exit(f"{PG_DB} already exists; rerun with --replace to rebuild it")
            c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(ident(PG_DB)))
        c.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(ident(PG_DB)))
    con.close()


def main():
    replace = "--replace" in sys.argv
    driver_config.fb_client_library.value = FB_CLIENT
    driver_config.stream_blob_threshold.value = 64 * 1024 * 1024
    fcur = fb_connect(FB_DB, user="SYSDBA", charset="UTF8").cursor()

    tables = read_tables(fcur)
    defaults = read_defaults(fcur)
    keys, fks, indexes = read_constraints(fcur)
    checks = read_checks(fcur)
    gens, fills = read_generators(fcur)
    user = set(tables)
    keys = [k for k in keys if k[1] in user]  # skip Firebird's own system tables
    broken = [f for f in fks if not f[2] or not f[4]]
    fks = [f for f in fks if f[2] and f[4] and f[1] in user]

    recreate_database(replace)
    pcon = psycopg2.connect(dbname=PG_DB, **PG)
    pcur = pcon.cursor()
    issues = [f"FK {f[0]} on {f[1]} -> {f[3]}: has no columns in Firebird (broken index), skipped" for f in broken]
    counts = dict(tables=0, columns=0, defaults=0, keys=0, fks=0, indexes=0, checks=0, sequences=0, id_defaults=0)

    executed: list[str] = []
    failed: list[str] = []

    def run(label, statement):
        try:
            pcur.execute(statement)
            pcon.commit()
            executed.append(statement.as_string(pcur) + ";")
            return True
        except psycopg2.Error as e:
            pcon.rollback()
            failed.append(label)
            issues.append(f"{label}: {e.pgerror.strip().splitlines()[0] if e.pgerror else e}")
            return False

    for gen, value in gens.items():
        start = max(int(value or 0), 0) + 1
        if run(f"sequence {gen}", sql.SQL("CREATE SEQUENCE {} START {}").format(ident(gen), sql.Literal(start))):
            counts["sequences"] += 1

    for table in tables:
        cols = read_columns(fcur, table)
        defs = []
        for c in cols:
            parts = [ident(c["name"]), sql.SQL(c["type"])]
            gen = fills.get((table, c["name"]))
            if gen in gens:
                parts.append(sql.SQL("DEFAULT nextval({})").format(sql.Literal(gen.lower())))
                counts["id_defaults"] += 1
            if c["notnull"]:
                parts.append(sql.SQL("NOT NULL"))
            defs.append(sql.SQL(" ").join(parts))
        if run(f"table {table}", sql.SQL("CREATE TABLE {} ({})").format(ident(table), sql.SQL(", ").join(defs))):
            counts["tables"] += 1
            counts["columns"] += len(cols)
            for c in cols:
                expr = defaults.get((table, c["name"]))
                if (
                    expr
                    and (table, c["name"]) not in fills
                    and run(
                        f"default {table}.{c['name']} = {expr}",
                        sql.SQL("ALTER TABLE {} ALTER COLUMN {} SET DEFAULT {}").format(
                            ident(table), ident(c["name"]), sql.SQL(pg_expr(expr))
                        ),
                    )
                ):
                    counts["defaults"] += 1
            computed = [c["name"] for c in cols if c["computed"]]
            if computed:
                issues.append(f"table {table}: computed columns created as plain columns: {', '.join(computed)}")

    for name, table, kind, cols, _ in keys:
        if run(
            f"{kind} {table}({', '.join(cols)})",
            sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} {} ({})").format(
                ident(table), ident(name), sql.SQL(kind), sql.SQL(", ").join(map(ident, cols))
            ),
        ):
            counts["keys"] += 1

    for name, table, unique, cols in indexes:
        if run(
            f"index {name} on {table}",
            sql.SQL("CREATE {}INDEX {} ON {} ({})").format(
                sql.SQL("UNIQUE " if unique else ""), ident(name), ident(table), sql.SQL(", ").join(map(ident, cols))
            ),
        ):
            counts["indexes"] += 1

    rule = {
        "RESTRICT": "NO ACTION",
        "NO ACTION": "NO ACTION",
        "CASCADE": "CASCADE",
        "SET NULL": "SET NULL",
        "SET DEFAULT": "SET DEFAULT",
    }
    for name, table, cols, ref_table, ref_cols, on_del, on_upd in fks:
        if run(
            f"FK {table}({', '.join(cols)}) -> {ref_table}",
            sql.SQL(
                "ALTER TABLE {} ADD CONSTRAINT {} FOREIGN KEY ({}) REFERENCES {} ({}) ON DELETE {} ON UPDATE {}"
            ).format(
                ident(table),
                ident(name),
                sql.SQL(", ").join(map(ident, cols)),
                ident(ref_table),
                sql.SQL(", ").join(map(ident, ref_cols)),
                sql.SQL(rule.get(on_del or "", "NO ACTION")),
                sql.SQL(rule.get(on_upd or "", "NO ACTION")),
            ),
        ):
            counts["fks"] += 1

    for name, table, src in checks:
        body = re.sub(r"^\s*CHECK\s*", "", src or "", flags=re.I)
        if run(
            f"CHECK {table}: {src}",
            sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} CHECK {}").format(
                ident(table), ident(name), sql.SQL(lower_outside_quotes(pg_expr(body)))
            ),
        ):
            counts["checks"] += 1

    pcon.close()
    expected = dict(
        tables=len(tables), keys=len(keys), fks=len(fks), indexes=len(indexes), checks=len(checks), sequences=len(gens)
    )
    write_report(counts, expected, issues)
    if failed:
        print(f"{len(failed)} statement(s) failed; {SCHEMA_SQL} not written; report written with errors")
        return 1
    os.makedirs(os.path.dirname(SCHEMA_SQL), exist_ok=True)
    with open(SCHEMA_SQL, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("-- Production MACS structure (public schema), no rows. Generated by migration/fb_schema_to_pg.py.\n")
        fh.write("\n".join(executed) + "\n")
    print(counts, "expected", expected, "issues", len(issues))
    return 0


def write_report(counts, expected, issues):
    lines = [
        "# macs_pg structure report",
        "",
        f"Run: {datetime.now():%Y-%m-%d %H:%M}. Source `db/work/MACS_COPY.FDB` → PostgreSQL `{PG_DB}`, "
        "schema `public`, structure only (no rows). Generated by `migration/fb_schema_to_pg.py`.",
        "",
        "| Item | Created | In Firebird |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {k} | {v} | {expected.get(k, '—')} |" for k, v in counts.items()]
    lines += [
        "",
        "Not copied by design: triggers, stored procedures, views (rules enforced in HR code, D-018).",
        "",
        "## Issues",
        "",
    ] + [f"- {i}" for i in issues or ["(none)"]]
    with open(REPORT, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    # Exit hard: closing the embedded firebird-driver connection hangs on this setup.
    code = main()
    sys.stdout.flush()
    os._exit(code)
