"""Guards for D-017: HR never changes a production table and never hides one."""

import hashlib

import pytest
from django.apps import apps
from django.db import connection

FINGERPRINT_SQL = """
select string_agg(x, ',' order by x) from (
  select table_name||'.'||column_name||':'||data_type||':'||coalesce(character_maximum_length,0)
         ||':'||is_nullable||':'||coalesce(column_default,'') x
    from information_schema.columns where table_schema='public'
  union all
  select conrelid::regclass::text||':'||conname||':'||pg_get_constraintdef(oid)
    from pg_constraint where connamespace='public'::regnamespace
  union all
  select indexdef from pg_indexes where schemaname='public') t
"""


def fingerprint(cursor) -> str:  # type: ignore[no-untyped-def]
    cursor.execute(FINGERPRINT_SQL)
    return hashlib.md5((cursor.fetchone()[0] or "").encode()).hexdigest()  # noqa: S324


@pytest.mark.django_db
def test_production_tables_are_loaded() -> None:
    with connection.cursor() as c:
        c.execute("select count(*) from information_schema.tables where table_schema='public'")
        assert c.fetchone()[0] == 531


@pytest.mark.django_db
def test_hr_tables_never_share_a_name_with_production() -> None:
    with connection.cursor() as c:
        c.execute("select table_name from information_schema.tables where table_schema='public'")
        production = {r[0] for r in c.fetchall()}
    ours = {m._meta.db_table for m in apps.get_models() if m._meta.managed}
    assert ours & production == set()
