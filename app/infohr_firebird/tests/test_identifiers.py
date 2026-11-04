from typing import Any, cast

from django.db import connections, models
from django.test.utils import CaptureQueriesContext, isolate_apps


def test_quote_name(fb_alias: str) -> None:
    ops = connections[fb_alias].ops
    assert ops.quote_name('"abc"') == "ABC"
    assert ops.quote_name("abc") == "ABC"
    assert ops.quote_name("RDB$DB_KEY") == "RDB$DB_KEY"
    first = ops.quote_name("a" * 40)
    assert len(first) == 31
    assert first == ops.quote_name("a" * 40)


@isolate_apps("infohr_firebird")
def test_ddl_round_trip_has_no_quotes(fb_alias: str) -> None:
    class Probe(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        name = models.CharField(max_length=50)
        qty = models.IntegerField(null=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_PROBE"

    note: models.Field[Any, Any] = models.CharField(max_length=20, null=True)
    note.set_attributes_from_name("note")
    new_qty: models.Field[Any, Any] = models.IntegerField(default=0)
    new_qty.set_attributes_from_name("qty")

    connection = connections[fb_alias]
    with CaptureQueriesContext(connection) as ctx:
        with connection.schema_editor() as editor:
            editor.create_model(Probe)
            editor.add_field(Probe, note)
            editor.alter_field(Probe, Probe._meta.get_field("qty"), new_qty)
            editor.remove_field(Probe, note)
            editor.delete_model(Probe)

    assert ctx.captured_queries, "the schema editor ran no statements"
    for query in ctx.captured_queries:
        assert '"' not in query["sql"], query["sql"]


@isolate_apps("infohr_firebird")
def test_trigger_and_sequence_lookups(fb_alias: str) -> None:
    # The lookups derive <table>_PK (trigger) and <table>_SQ (generator) from the table
    # name, so they are checked against objects Django creates for an AutoField.
    class Probe(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_LOOKUP"

    connection = connections[fb_alias]
    with connection.schema_editor() as base_editor:
        editor = cast(Any, base_editor)  # backend methods are untyped
        assert not editor.trigger_exist("IHR_T_LOOKUP")
        assert not editor.sequence_exist("IHR_T_LOOKUP")
        editor.create_model(Probe)
        try:
            assert editor.trigger_exist("IHR_T_LOOKUP")
            assert editor.sequence_exist("IHR_T_LOOKUP")
            assert editor.trigger_exist("ihr_t_lookup")  # table name case is ignored
            assert editor.sequence_exist("ihr_t_lookup")
            assert not editor.trigger_exist("IHR_T_NO_SUCH")
            assert not editor.sequence_exist("IHR_T_NO_SUCH")
        finally:
            editor.delete_model(Probe)


@isolate_apps("infohr_firebird")
def test_long_generated_names_are_unique(fb_alias: str) -> None:
    class LongOne(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        very_long_indexed_column_name_number_one = models.CharField(max_length=10, db_index=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_AAAAAAAAAAAAAAAAAAAA"

    class LongTwo(models.Model):  # noqa: DJ008 - throwaway model, no __str__ needed
        id = models.AutoField(primary_key=True)
        very_long_indexed_column_name_number_one = models.CharField(max_length=10, db_index=True)

        class Meta:
            app_label = "infohr_firebird"
            db_table = "IHR_T_AAAAAAAAAAAAAAAAAAAB"

    connection = connections[fb_alias]
    with connection.schema_editor() as editor:
        editor.create_model(LongOne)
        editor.create_model(LongTwo)
    with connection.schema_editor() as editor:
        editor.delete_model(LongTwo)
        editor.delete_model(LongOne)
