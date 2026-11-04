"""Foreign keys: the schema editor creates a database constraint only when the referenced table is an HR table.

MACS (the old program) must still be able to delete a row that an HR table points at, so a
constraint from an HR table to a MACS table would break MACS. The column and its index are
still created; only the constraint is skipped.
"""

from typing import Any

import pytest
from django.db import IntegrityError, connections, models
from django.test.utils import CaptureQueriesContext, isolate_apps
from firebird.driver import DatabaseError as FbDatabaseError  # type: ignore[import-untyped]
from pytest_django.fixtures import SettingsWrapper


def _fk_count(connection: Any, table: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "select count(*) from rdb$relation_constraints "
            "where rdb$relation_name = %s and rdb$constraint_type = 'FOREIGN KEY'",
            [table.upper()],
        )
        return int(cursor.fetchone()[0])


def _index_count_on_column(connection: Any, table: str, column: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "select count(*) from rdb$index_segments s "
            "join rdb$indices i on i.rdb$index_name = s.rdb$index_name "
            "where i.rdb$relation_name = %s and trim(s.rdb$field_name) = %s and s.rdb$field_position = 0",
            [table.upper(), column.upper()],
        )
        return int(cursor.fetchone()[0])


def _fk_identities(connection: Any, table: str) -> list[tuple[str, str]]:
    """(constraint name, index name) of each foreign key. Firebird gives a recreated
    constraint a new index name even when Django reuses the constraint name."""
    with connection.cursor() as cursor:
        cursor.execute(
            "select trim(rdb$constraint_name), trim(rdb$index_name) from rdb$relation_constraints "
            "where rdb$relation_name = %s and rdb$constraint_type = 'FOREIGN KEY' order by 1",
            [table.upper()],
        )
        return [(str(row[0]), str(row[1])) for row in cursor.fetchall()]


def _constraint_ddl_on(queries: Any, table: str) -> list[str]:
    """ALTER TABLE statements on `table` that add or drop a constraint."""
    prefix = f"ALTER TABLE {table}".upper()
    return [
        str(q["sql"])
        for q in queries
        if str(q["sql"]).upper().startswith(prefix) and "CONSTRAINT" in str(q["sql"]).upper()
    ]


def _drop_table_if_exists(connection: Any, table: str) -> None:
    if table.upper() in [name.upper() for name in connection.introspection.table_names()]:
        with connection.cursor() as cursor:
            cursor.execute(f"DROP TABLE {table}")


def _column_count(connection: Any, table: str, column: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "select count(*) from rdb$relation_fields where rdb$relation_name = %s and trim(rdb$field_name) = %s",
            [table.upper(), column.upper()],
        )
        return int(cursor.fetchone()[0])


def _macs_employee_stub() -> Any:
    """Unmanaged model on the existing MACS table EMPLOYEE (never created, altered or dropped)."""

    class MacsEmployee(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True, db_column="EMPLOYEE_ID")

        class Meta:
            app_label = "infohr_firebird"
            managed = False
            db_table = "EMPLOYEE"

    return MacsEmployee


def _make_child(target: Any, table_name: str) -> Any:
    """Managed model with one foreign key 'ref' (column REF_ID) pointing at target."""

    class Child(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        ref = models.ForeignKey(target, on_delete=models.DO_NOTHING, db_constraint=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = table_name

    return Child


def _insert_macs_employee(connection: Any) -> int:
    with connection.cursor() as cursor:
        cursor.execute(
            "insert into employee (name, surname) values (%s, %s) returning employee_id",
            ["Тест", "Тестов"],
        )
        return int(cursor.fetchone()[0])


def _delete_macs_employee(connection: Any, employee_id: int) -> int:
    with connection.cursor() as cursor:
        cursor.execute("delete from employee where employee_id = %s", [employee_id])
        return int(cursor.rowcount)


@isolate_apps("infohr_firebird")
def test_fk_to_macs_table_has_no_constraint(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]
    macs = _macs_employee_stub()
    child = _make_child(macs, "IHR_T_CHILD")

    with connection.schema_editor() as editor:
        editor.create_model(child)
    try:
        assert _fk_count(connection, "IHR_T_CHILD") == 0
        assert _column_count(connection, "IHR_T_CHILD", "REF_ID") == 1
        assert _index_count_on_column(connection, "IHR_T_CHILD", "REF_ID") == 1

        # EMPLOYEE is the throwaway template copy, never the real MACS database.
        employee_id = _insert_macs_employee(connection)
        child.objects.using(fb_alias).create(ref_id=employee_id)
        # MACS must still be able to delete the employee that an HR row points at.
        assert _delete_macs_employee(connection, employee_id) == 1
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(child)


@isolate_apps("infohr_firebird")
def test_fk_between_hr_tables_is_kept(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_PARENT"

    child = _make_child(Parent, "IHR_T_CHILD")

    with connection.schema_editor() as editor:
        editor.create_model(Parent)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(child)
        try:
            assert _fk_count(connection, "IHR_T_CHILD") == 1

            parent_model: Any = Parent
            parent = parent_model.objects.using(fb_alias).create(name="родитель")
            child.objects.using(fb_alias).create(ref_id=parent.pk)
            with connection.cursor() as cursor:
                try:
                    cursor.execute("delete from IHR_T_PARENT where id = %s", [parent.pk])
                except IntegrityError:
                    pass
                else:
                    raise AssertionError("deleting a referenced HR row must fail")
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(child)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Parent)


@isolate_apps("infohr_firebird")
def test_empty_prefix_keeps_all_fks(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = ""
    connection = connections[fb_alias]
    macs = _macs_employee_stub()
    child = _make_child(macs, "IHR_T_CHILD_EP")

    with connection.schema_editor() as editor:
        editor.create_model(child)
    try:
        assert _fk_count(connection, "IHR_T_CHILD_EP") == 1
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(child)


@isolate_apps("infohr_firebird")
def test_add_field_fk_to_macs_table_has_no_constraint(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]
    macs = _macs_employee_stub()

    class Holder(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_HOLDER"

    ref: models.Field[Any, Any] = models.ForeignKey(macs, on_delete=models.DO_NOTHING, db_constraint=True)
    ref.set_attributes_from_name("ref")

    with connection.schema_editor() as editor:
        editor.create_model(Holder)
    try:
        with connection.schema_editor() as editor:
            editor.add_field(Holder, ref)
        assert _fk_count(connection, "IHR_T_HOLDER") == 0
        assert _column_count(connection, "IHR_T_HOLDER", "REF_ID") == 1
        assert _index_count_on_column(connection, "IHR_T_HOLDER", "REF_ID") == 1
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Holder)


@isolate_apps("infohr_firebird")
def test_alter_field_fk_to_macs_table_has_no_constraint(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]
    macs = _macs_employee_stub()

    class Holder(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        ref = models.IntegerField(null=True, db_column="REF_ID")

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_HOLDER_A"

    old_ref: models.Field[Any, Any] = models.IntegerField(null=True, db_column="REF_ID")
    old_ref.set_attributes_from_name("ref")
    new_ref: models.Field[Any, Any] = models.ForeignKey(
        macs, on_delete=models.DO_NOTHING, db_constraint=True, null=True, db_column="REF_ID"
    )
    new_ref.set_attributes_from_name("ref")

    with connection.schema_editor() as editor:
        editor.create_model(Holder)
    try:
        with connection.schema_editor() as editor:
            editor.alter_field(Holder, old_ref, new_ref)
        assert _fk_count(connection, "IHR_T_HOLDER_A") == 0
        assert _index_count_on_column(connection, "IHR_T_HOLDER_A", "REF_ID") == 1
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Holder)


@isolate_apps("infohr_firebird")
def test_m2m_through_to_macs_table_has_no_constraint(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]
    macs = _macs_employee_stub()

    class Owner(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        links: Any = models.ManyToManyField(macs)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_OWNER"

    links_field: Any = Owner._meta.get_field("links")
    through_table = links_field.remote_field.through._meta.db_table

    with connection.schema_editor() as editor:
        editor.create_model(Owner)
    try:
        # Only the foreign key to the HR owner table remains; the one to EMPLOYEE is skipped.
        assert _fk_count(connection, through_table) == 1
        assert _column_count(connection, through_table, "MACSEMPLOYEE_ID") == 1
        assert _index_count_on_column(connection, through_table, "MACSEMPLOYEE_ID") == 1
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Owner)


@isolate_apps("infohr_firebird")
def test_retarget_from_macs_stub_to_hr_table_creates_constraint(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]
    macs = _macs_employee_stub()

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_RPARENT"

    child = _make_child(macs, "IHR_T_RCHILD")
    new_ref: Any = models.ForeignKey(Parent, on_delete=models.DO_NOTHING, db_constraint=True)
    new_ref.set_attributes_from_name("ref")

    with connection.schema_editor() as editor:
        editor.create_model(Parent)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(child)
        try:
            assert _fk_count(connection, "IHR_T_RCHILD") == 0
            with connection.schema_editor() as editor:
                editor.alter_field(child, child._meta.get_field("ref"), new_ref)
            assert _fk_count(connection, "IHR_T_RCHILD") == 1
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(child)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Parent)


@isolate_apps("infohr_firebird")
def test_retarget_from_hr_table_to_macs_stub_drops_constraint(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]
    macs = _macs_employee_stub()

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_SPARENT"

    child = _make_child(Parent, "IHR_T_SCHILD")
    new_ref: Any = models.ForeignKey(macs, on_delete=models.DO_NOTHING, db_constraint=True)
    new_ref.set_attributes_from_name("ref")

    with connection.schema_editor() as editor:
        editor.create_model(Parent)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(child)
        try:
            assert _fk_count(connection, "IHR_T_SCHILD") == 1
            with connection.schema_editor() as editor:
                editor.alter_field(child, child._meta.get_field("ref"), new_ref)
            assert _fk_count(connection, "IHR_T_SCHILD") == 0
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(child)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Parent)


@isolate_apps("infohr_firebird")
def test_rename_table_keeps_incoming_hr_fk(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_RNPARENT"

    child = _make_child(Parent, "IHR_T_RNCHILD")
    renamed = "IHR_T_RNPARENT2"

    with connection.schema_editor() as editor:
        editor.create_model(Parent)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(child)
        try:
            parent_model: Any = Parent
            parent = parent_model.objects.using(fb_alias).create(name="родитель")
            child.objects.using(fb_alias).create(ref_id=parent.pk)
            with connection.schema_editor() as editor:
                editor.alter_db_table(Parent, "IHR_T_RNPARENT", renamed)
            Parent._meta.db_table = renamed
            assert _fk_count(connection, "IHR_T_RNCHILD") == 1
            with connection.cursor() as cursor:
                with pytest.raises(IntegrityError):
                    cursor.execute("delete from IHR_T_RNPARENT2 where id = %s", [parent.pk])
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(child)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Parent)


@isolate_apps("infohr_firebird")
def test_rename_table_does_not_touch_non_hr_incoming_fk(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        name = models.CharField(max_length=20)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_QPARENT"

    # With the prefix empty the receiver leaves the MYT_ name alone (it would add IHR_ otherwise).
    settings.HR_TABLE_PREFIX = ""
    kid = _make_child(Parent, "MYT_T_QKID")
    settings.HR_TABLE_PREFIX = "IHR_"
    renamed = "IHR_T_QPARENT2"

    with connection.schema_editor() as editor:
        editor.create_model(Parent)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(kid)
        try:
            names_before = _fk_identities(connection, "MYT_T_QKID")
            assert len(names_before) == 1
            try:
                with CaptureQueriesContext(connection) as ctx:
                    with connection.schema_editor() as editor:
                        editor.alter_db_table(Parent, "IHR_T_QPARENT", renamed)
            except FbDatabaseError:
                # Firebird refuses to drop the referenced parent while the MYT_ constraint exists.
                pass
            else:
                Parent._meta.db_table = renamed
            assert _constraint_ddl_on(ctx.captured_queries, "MYT_T_QKID") == []
            assert _fk_identities(connection, "MYT_T_QKID") == names_before
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(kid)
            _drop_table_if_exists(connection, renamed)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Parent)


@isolate_apps("infohr_firebird")
def test_alter_field_does_not_touch_non_hr_incoming_fk(fb_alias: str, settings: SettingsWrapper) -> None:
    settings.HR_TABLE_PREFIX = "IHR_"
    connection = connections[fb_alias]

    class Parent(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        code = models.CharField(max_length=10, unique=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_APARENT"

    # With the prefix empty the receiver leaves the MYT_ name alone (it would add IHR_ otherwise).
    settings.HR_TABLE_PREFIX = ""

    class Kid(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        parent = models.ForeignKey(Parent, to_field="code", on_delete=models.DO_NOTHING, db_constraint=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "MYT_T_AKID"

    settings.HR_TABLE_PREFIX = "IHR_"

    old_code = Parent._meta.get_field("code")
    new_code: Any = models.CharField(max_length=20, unique=True)
    new_code.set_attributes_from_name("code")
    new_code.model = Parent  # what contribute_to_class would set; alter_field reads it

    with connection.schema_editor() as editor:
        editor.create_model(Parent)
    try:
        with connection.schema_editor() as editor:
            editor.create_model(Kid)
        try:
            names_before = _fk_identities(connection, "MYT_T_AKID")
            assert len(names_before) == 1
            with CaptureQueriesContext(connection) as ctx:
                try:
                    with connection.schema_editor() as editor:
                        editor.alter_field(Parent, old_code, new_code)
                except FbDatabaseError:
                    # Firebird refuses to change the referenced column while the MYT_ constraint uses it.
                    pass
            # The MYT_ constraint must be neither dropped nor recreated.
            assert _constraint_ddl_on(ctx.captured_queries, "MYT_T_AKID") == []
            assert _fk_identities(connection, "MYT_T_AKID") == names_before
        finally:
            with connection.schema_editor() as editor:
                editor.delete_model(Kid)
    finally:
        with connection.schema_editor() as editor:
            editor.delete_model(Parent)
