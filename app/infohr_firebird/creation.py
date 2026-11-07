import base64
import datetime
import decimal
import json
import sys
from typing import Any

import firebird.driver as Database
from django.apps import apps
from django.db import transaction
from django.db.backends.base.creation import BaseDatabaseCreation

TEST_MODE = 0

# Version of the raw snapshot written by serialize_db_to_string. A snapshot of another version is refused.
SNAPSHOT_FORMAT = 1


def _encode_value(value: Any) -> Any:
    """One cell of the snapshot. Text, numbers, booleans and None are plain JSON; the other types carry a tag."""
    if hasattr(value, "read") and not isinstance(value, (str, bytes, bytearray, memoryview)):
        value = value.read()  # a BLOB is streamed by the driver; the whole value is read here
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, datetime.datetime):
        return {"$": "datetime", "v": value.isoformat()}
    if isinstance(value, datetime.date):
        return {"$": "date", "v": value.isoformat()}
    if isinstance(value, datetime.time):
        return {"$": "time", "v": value.isoformat()}
    if isinstance(value, decimal.Decimal):
        return {"$": "decimal", "v": str(value)}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$": "bytes", "v": base64.b64encode(bytes(value)).decode("ascii")}
    raise TypeError(f"the Firebird test snapshot cannot store a {type(value).__name__} value")


def _decode_value(value: Any) -> Any:
    """The inverse of _encode_value: a tagged cell becomes the exact Python value it was read from."""
    if not isinstance(value, dict):
        return value
    kind, text = value["$"], value["v"]
    if kind == "datetime":
        return datetime.datetime.fromisoformat(text)
    if kind == "date":
        return datetime.date.fromisoformat(text)
    if kind == "time":
        return datetime.time.fromisoformat(text)
    if kind == "decimal":
        return decimal.Decimal(text)
    if kind == "bytes":
        return base64.b64decode(text)
    raise ValueError(f"unknown snapshot tag: {kind!r}")


class DatabaseCreation(BaseDatabaseCreation):

    def _snapshot_tables(self) -> list[tuple[str, Any]]:
        """(table, model) for every managed HR table, children before the tables they reference (the flush order).

        The same list the flush deletes, so a snapshot holds exactly the tables a flush empties. Unmanaged MACS tables
        are never in it.
        """
        ops = self.connection.ops
        models = {
            model._meta.db_table: model
            for model in apps.get_models(include_auto_created=True)
            if model._meta.managed and model._meta.app_label != "macs"
        }
        names = ops._flush_table_order(
            ops._flush_tables(self.connection.introspection.django_table_names(only_existing=True, include_views=False))
        )
        return [(name, models[name]) for name in names]

    def serialize_db_to_string(self) -> str:
        """Every row of every managed HR table as JSON, read with plain SQL (not the ORM serializer).

        Django's serializer streams rows through a cursor that a second read can interrupt, and Firebird then refuses
        the fetch. Here each table is read in one fetchall, parents first, with its column names and exact values.
        """
        ops = self.connection.ops
        tables = []
        with self.connection.cursor() as cursor:
            for name, model in reversed(self._snapshot_tables()):  # parents first: the restore inserts in this order
                columns = [field.column for field in model._meta.local_concrete_fields]
                select_list = ", ".join(ops.quote_name(column) for column in columns)
                pk_column = ops.quote_name(model._meta.pk.column)
                cursor.execute(f"SELECT {select_list} FROM {ops.quote_name(name)} ORDER BY {pk_column}")  # noqa: S608
                rows = [[_encode_value(value) for value in row] for row in cursor.fetchall()]
                tables.append({"table": name, "columns": columns, "rows": rows})
        return json.dumps({"format": SNAPSHOT_FORMAT, "tables": tables}, ensure_ascii=False, separators=(",", ":"))

    def deserialize_db_from_string(self, data: str) -> None:
        """Empty the managed HR tables, then insert the snapshot's rows with their ids, in one transaction.

        Children are deleted before parents and inserted after them (the flush order). Each generator is then set to
        the largest restored id, so the next new row gets an id above it.
        """
        snapshot = json.loads(data)
        if snapshot.get("format") != SNAPSHOT_FORMAT:
            raise ValueError(f"unknown snapshot format: {snapshot.get('format')!r}")
        ops = self.connection.ops
        current = self._snapshot_tables()
        if {entry["table"] for entry in snapshot["tables"]} != {name for name, _ in current}:
            raise ValueError("the snapshot holds different tables from this database")
        with transaction.atomic(using=self.connection.alias), self.connection.cursor() as cursor:
            for name, _ in current:  # children first
                cursor.execute(f"DELETE FROM {ops.quote_name(name)}")  # noqa: S608 (quoted names)
            for entry in snapshot["tables"]:  # parents first
                columns = entry["columns"]
                names = ", ".join(ops.quote_name(column) for column in columns)
                marks = ", ".join(["%s"] * len(columns))
                sql = f"INSERT INTO {ops.quote_name(entry['table'])} ({names}) VALUES ({marks})"  # noqa: S608
                for row in entry["rows"]:
                    cursor.execute(sql, [_decode_value(value) for value in row])
            self._restore_generators(cursor, current)

    def _restore_generators(self, cursor: Any, tables: list[tuple[str, Any]]) -> None:
        """Set each table's generator to its largest id (0 for an empty table); the next value is then above it.

        Only a table with an automatic key has a generator (schema.py creates it), so the others are skipped, as the
        flush skips them.
        """
        ops = self.connection.ops
        generators = ops._generator_names()
        for name, model in tables:
            sequence_name = ops.get_sequence_name(name)
            if sequence_name not in generators:
                continue
            pk_column = ops.quote_name(model._meta.pk.column)
            cursor.execute(f"SELECT MAX({pk_column}) FROM {ops.quote_name(name)}")  # noqa: S608 (quoted names)
            top = int(cursor.fetchone()[0] or 0)
            cursor.execute(f"ALTER SEQUENCE {sequence_name} RESTART WITH {top}")  # noqa: S608 (quoted name)


    def sql_for_inline_foreign_key_references(self, model, field, known_models, style):
        # Always pending
        return [], TEST_MODE < 2

    def sql_for_pending_references(self, model, style, pending_references):
        if TEST_MODE < 2:
            final_output = super(DatabaseCreation, self).sql_for_pending_references(model, style, pending_references)
            return ['%s ON DELETE CASCADE;' % s[:-1] for s in final_output]
        return []

    def sql_remove_table_constraints(self, model, references_to_delete, style):
        if TEST_MODE < 2:
            return super(DatabaseCreation, self).sql_remove_table_constraints(model, references_to_delete, style)
        return []

    def _check_active_connection(self, verbosity):
        if self.connection:
            if verbosity >= 1:
                print("Closing active connection")
            self.connection.close()

    def _build_dsn(self, database, default_host=None):
        # firebird-driver has no host/port arguments; the server location
        # must be embedded in the DSN as host[/port]:database.
        settings_dict = self.connection.settings_dict
        host = settings_dict.get('HOST') or default_host
        port = settings_dict.get('PORT')
        if not host:
            return database
        if port:
            return '%s/%s:%s' % (host, port, database)
        return '%s:%s' % (host, database)

    def _get_connection_params(self, **overrides):
        settings_dict = self.connection.settings_dict
        conn_params = {'charset': 'UTF8'}
        database = overrides.pop('database', settings_dict['NAME'])
        conn_params['database'] = self._build_dsn(database)
        if settings_dict['USER']:
            conn_params['user'] = settings_dict['USER']
        if settings_dict['PASSWORD']:
            conn_params['password'] = settings_dict['PASSWORD']
        if 'ROLE' in settings_dict:
            conn_params['role'] = settings_dict['ROLE']
        options = settings_dict['OPTIONS'].copy()
        options.pop('lock_timeout', None)  # backend-only option, not a connect() argument
        conn_params.update(options)
        conn_params.update(overrides)
        return conn_params

    def _get_creation_params(self, **overrides):
        settings_dict = self.connection.settings_dict
        params = {}
        if settings_dict.get('USER'):
            params['user'] = settings_dict['USER']
        if settings_dict.get('PASSWORD'):
            params['password'] = settings_dict['PASSWORD']
        params['charset'] = settings_dict.get('CHARSET') or 'UTF8'
        params['page_size'] = 8192

        test_settings = settings_dict.get('TEST')
        if test_settings:
            params['charset'] = test_settings.get('CHARSET') or params['charset']
            params['page_size'] = test_settings.get('PAGE_SIZE') or params['page_size']
        params.update(overrides)
        return params

    def _create_database(self, test_database_name, verbosity):
        self._check_active_connection(verbosity)
        params = self._get_creation_params(database=test_database_name)
        # Database creation attributes are taken from the driver configuration,
        # not from create_database() arguments.
        db_defaults = Database.driver_config.db_defaults
        db_defaults.page_size.value = params['page_size']
        db_defaults.db_charset.value = params['charset']
        connection = Database.create_database(
            self._build_dsn(params['database'], default_host='localhost'),
            user=params.get('user'),
            password=params.get('password'),
            charset=params['charset'],
        )
        connection.execute_immediate("CREATE EXCEPTION teste '';")
        connection.commit()
        connection.close()

    def _create_test_db(self, verbosity, autoclobber, keepdb=False):
        """"
        Internal implementation - creates the test db tables.
        """
        test_database_name = self._get_test_db_name()

        try:
            self._create_database(test_database_name, verbosity)
            if verbosity >= 1:
                print("Database %s created..." % test_database_name)
        except Exception as e:
            # if we want to keep the db, then no need to do any of the below,
            # just return and skip it all.
            if keepdb:
                return test_database_name

            sys.stderr.write("Got an error creating the test database: %s\n" % e)
            if not autoclobber:
                confirm = input("Type 'yes' if you would like to try deleting the test database '%s', or 'no' to cancel: " % test_database_name)
            if autoclobber or confirm == 'yes':
                try:
                    if verbosity >= 1:
                        print("Destroying old test database...")
                    self._destroy_test_db(test_database_name, verbosity)
                    if verbosity >= 1:
                        print("Creating test database...")
                    self._create_database(test_database_name, verbosity)
                    if verbosity >= 1:
                        print("Database %s created..." % test_database_name)
                except Exception as e:
                    sys.stderr.write("Got an error recreating the test database: %s\n" % e)
                    sys.exit(2)
            else:
                print("Tests cancelled.")
                sys.exit(1)

        return test_database_name

    def _destroy_test_db(self, test_database_name, verbosity):
        """
        Internal implementation - remove the test db tables.
        """
        self._check_active_connection(verbosity)
        connection = Database.connect(**self._get_connection_params(database=test_database_name))
        connection.drop_database()
        connection.close()
