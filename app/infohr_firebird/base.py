"""
Firebird database backend for Django.
"""
import decimal

try:
    import firebird.driver as Database
except ImportError as e:
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Error loading firebird driver: %s" % e)

from firebird.driver import CHARSET_MAP, tpb, TPB, Isolation, TraAccessMode, TableShareMode, TableAccessMode

from django.conf import settings
from django.db import utils
from django.db.backends.base.base import BaseDatabaseWrapper

from django.utils.asyncio import async_unsafe
from django.utils.encoding import smart_str
from django.utils.functional import cached_property

from . import expressions  # NOQA: registers as_firebird() on Django expressions
from .errors import busy_error_for
from .operations import DatabaseOperations
from .features import DatabaseFeatures
from .client import DatabaseClient
from .creation import DatabaseCreation
from .introspection import DatabaseIntrospection
from .schema import DatabaseSchemaEditor
from .validation import DatabaseValidation

DEFAULT_FB_CLIENT_LIBRARY = r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll"

DatabaseError = Database.DatabaseError
IntegrityError = Database.IntegrityError
InterfaceError = Database.InterfaceError
OperationalError = Database.OperationalError


class DatabaseWrapper(BaseDatabaseWrapper):
    vendor = 'firebird'
    display_name = "Firebird"

    # This dictionary maps Field objects to their associated Firebird column
    # types, as strings. Column-type strings can contain format strings; they'll
    # be interpolated against the values of Field.__dict__ before being output.
    # If a column type is set to None, it won't be included in the output.
    #
    # Any format strings starting with "qn_" are quoted before being used in the
    # output (the "qn_" prefix is stripped before the lookup is performed.

    data_types = {
        'AutoField': 'integer',
        'BigAutoField': 'integer',  # dialect 1 has no BIGINT
        'BinaryField': 'blob sub_type 0',
        'BooleanField': 'boolean',
        'CharField': 'varchar(%(max_length)s)',
        'CommaSeparatedIntegerField': 'varchar(%(max_length)s)',
        'DateField': 'timestamp',  # dialect 1 has no DATE type
        'DateTimeField': 'timestamp',
        'DecimalField': 'decimal(%(max_digits)s, %(decimal_places)s)',
        'DurationField': 'bigint',
        'FileField': 'varchar(%(max_length)s)',
        'FilePathField': 'varchar(%(max_length)s)',
        'FloatField': 'double precision',
        'IntegerField': 'integer',
        'BigIntegerField': 'integer',  # dialect 1 has no BIGINT
        'IPAddressField': 'char(15)',
        'JSONField': 'blob sub_type text',  # no native JSON in Firebird; Django stores a JSON string
        'GenericIPAddressField': 'char(39)',
        'OneToOneField': 'integer',
        'PositiveBigIntegerField': 'integer',
        'PositiveIntegerField': 'integer',
        'PositiveSmallIntegerField': 'smallint',
        'SlugField': 'varchar(%(max_length)s)',
        'SmallAutoField': 'smallint',
        'SmallIntegerField': 'smallint',
        'TextField': 'blob sub_type 1',
        'TimeField': 'time',
        'UUIDField': 'char(32)',
    }

    # Firebird 3+ has a native BOOLEAN type, so no check constraint is needed
    # to emulate it. It also avoids a Firebird 3.0.x bug when dropping columns
    # that have a check constraint (#154).
    data_type_check_constraints = {
        'PositiveIntegerField': '%(qn_column)s >= 0',
        'PositiveSmallIntegerField': '%(qn_column)s >= 0',
    }

    operators = {
        'exact': '= %s',
        'iexact': '= UPPER(%s)',
        'contains': "LIKE %s ESCAPE'\\'",
        'icontains': "LIKE UPPER(%s) ESCAPE'\\'",  # 'CONTAINING %s', #case is ignored
        'gt': '> %s',
        'gte': '>= %s',
        'lt': '< %s',
        'lte': '<= %s',
        'startswith': "LIKE %s ESCAPE'\\'",  # 'STARTING WITH %s', #looks to be faster than LIKE
        'endswith': "LIKE %s ESCAPE'\\'",
        'istartswith': "LIKE UPPER(%s) ESCAPE'\\'",  # 'STARTING WITH UPPER(%s)',
        'iendswith': "LIKE UPPER(%s) ESCAPE'\\'",
        # Firebird has no regular expression support; SIMILAR TO implements
        # SQL-standard patterns (full-match, no ^/$ anchors).
        'regex': "SIMILAR TO %s",
        'iregex': "SIMILAR TO UPPER(%s)",
    }

    # The patterns below are used to generate SQL pattern lookup clauses when
    # the right-hand side of the lookup isn't a raw string (it might be an expression
    # or the result of a bilateral transformation).
    # In those cases, special characters for LIKE operators (e.g. \, *, _) should be
    # escaped on database side.
    #
    # Note: we use str.format() here for readability as '%' is used as a wildcard for
    # the LIKE operator.
    pattern_esc = r"REPLACE(REPLACE(REPLACE({}, '\', '\\'), '%%', '\%%'), '_', '\_')"
    # Firebird's LIKE has no default escape character, so the ESCAPE clause is
    # required for the pattern_esc escaping to be effective.
    pattern_ops = {
        'contains': "LIKE '%%' || {} || '%%' ESCAPE '\\'",
        'icontains': "LIKE '%%' || UPPER({}) || '%%' ESCAPE '\\'",
        'startswith': "LIKE {} || '%%' ESCAPE '\\'",
        'istartswith': "LIKE UPPER({}) || '%%' ESCAPE '\\'",
        'endswith': "LIKE '%%' || {} ESCAPE '\\'",
        'iendswith': "LIKE '%%' || UPPER({}) ESCAPE '\\'",
    }

    @staticmethod
    def binary(value):
        return bytes(value)

    Database.Binary = staticmethod(binary)

    Database = Database
    SchemaEditorClass = DatabaseSchemaEditor

    # Classes instantiated in __init__().
    client_class = DatabaseClient
    creation_class = DatabaseCreation
    features_class = DatabaseFeatures
    introspection_class = DatabaseIntrospection
    ops_class = DatabaseOperations

    connections = []

    def __init__(self, *args, **kwargs):
        super(DatabaseWrapper, self).__init__(*args, **kwargs)

        self._server_version = None
        self._db_charset = None
        self.encoding = None

        opts = self.settings_dict["OPTIONS"]
        RC = Database.core.TraIsolation.READ_COMMITTED
        self.isolation_level = opts.get('isolation_level', RC)

        self.features = DatabaseFeatures(self)
        self.ops = DatabaseOperations(self)
        self.client = DatabaseClient(self)
        self.creation = DatabaseCreation(self)
        self.introspection = DatabaseIntrospection(self)
        self.validation = DatabaseValidation(self)

    # #### Backend-specific methods for creating connections and cursors #####

    def get_connection_params(self):
        """Returns a dict of parameters suitable for get_new_connection."""
        settings_dict = self.settings_dict
        if settings_dict['NAME'] == '':
            from django.core.exceptions import ImproperlyConfigured
            raise ImproperlyConfigured(
                "settings.DATABASES is improperly configured. "
                "Please supply the NAME value.")

        # The port param is not used by fdb. It must be setting by database string.
        # An empty HOST means an embedded (local file) database: NAME alone.
        if not settings_dict['HOST']:
            database = '%(NAME)s'
        elif settings_dict['PORT']:
            database = '%(HOST)s/%(PORT)s:%(NAME)s'
        else:
            database = '%(HOST)s:%(NAME)s'
        conn_params = {'charset': 'UTF8'}
        conn_params['database'] = database % settings_dict
        if settings_dict['USER']:
            conn_params['user'] = settings_dict['USER']
        if settings_dict['PASSWORD']:
            conn_params['password'] = settings_dict['PASSWORD']
        if 'ROLE' in settings_dict:
            conn_params['role'] = settings_dict['ROLE']
        # TIME_ZONE is read by Django itself (connection.timezone); it is not passed to the driver,
        # because session_time_zone is a Firebird 4 feature and this backend targets Firebird 3.
        options = settings_dict['OPTIONS'].copy()
        # Backend-only option: transaction lock wait timeout in seconds. A transaction that
        # meets a row another user holds waits this long, then fails with RecordBusy.
        # -1 waits forever (the Firebird default); never set it that way for HR.
        self._lock_timeout = options.pop('lock_timeout', 3)
        # Backend-only options: the SQL dialect this client uses (MACS databases
        # are dialect 1) and the Firebird client library to load. Both are global
        # driver settings, not connect() arguments, and must be set before the
        # first connection.
        sql_dialect = options.pop('sql_dialect', 1)
        fb_client_library = options.pop('fb_client_library', DEFAULT_FB_CLIENT_LIBRARY)
        Database.driver_config.fb_client_library.value = fb_client_library
        Database.driver_config.db_defaults.sql_dialect.value = sql_dialect
        conn_params.update(options)

        self._db_charset = conn_params.get('charset')
        self.encoding = CHARSET_MAP.get(self._db_charset, 'utf_8')

        return conn_params

    @async_unsafe
    def get_new_connection(self, conn_params):
        """Opens a connection to the database."""
        connection = Database.connect(**conn_params)
        # Django's atomic blocks run in the driver's main transaction, which starts with
        # the connection's default TPB (no lock timeout by default). Give the main
        # transaction and new transaction managers the lock timeout too.
        lock_tpb = tpb(Isolation.SNAPSHOT, lock_timeout=self._lock_timeout)
        connection.default_tpb = lock_tpb
        connection.main_transaction.default_tpb = lock_tpb
        self.connections.append(connection)
        for cc in self.connections:
            if cc.is_closed():
                self.connections.remove(cc)
        return connection

    def init_connection_state(self):
        """Initializes the database connection settings."""
        if self.ops.firebird_main_version < 4:
            self.data_types = dict(
                self.data_types,
                DecimalField=ClampedDecimalType(self.data_types['DecimalField']),
            )
        if self.ops.firebird_main_version >= 4:
            self.features.supports_over_clause = True
            self.features.supports_timezones = True
        if self.ops.firebird_main_version >= 5:
            # Partial indices were introduced in Firebird 5.
            self.features.supports_partial_indexes = True
            if settings.USE_TZ:
                # Only store time zones when Django uses aware datetimes;
                # WITH TIME ZONE columns return aware values, which must not
                # happen when USE_TZ is off.
                self.data_types['DateTimeField'] = 'timestamp with time zone'
                self.data_types['TimeField'] = 'time with time zone'

    @async_unsafe
    def close(self):
        for cc in self.connections:
            if cc.is_closed():
                self.connections.remove(cc)
        BaseDatabaseWrapper.close(self)

    def is_usable(self):
        """
        Check whether the attachment is still alive, so Django can discard
        broken connections (e.g. after the database was shut down).
        """
        if self.connection is None or self.connection.is_closed():
            return False
        try:
            # A cheap info request that requires a server round trip.
            self.connection.info.attachment_id
        except Database.Error:
            return False
        return True

    def create_cursor(self, name=None):
        """Creates a cursor. Assumes that a connection is established."""
        if self.connection.is_closed():
            raise InterfaceError("Cannot create cursor for closed connection")
        tpb = TPB(isolation=Isolation.READ_COMMITTED,
                  access_mode=TraAccessMode.WRITE,
                  auto_commit=False,
                  lock_timeout=getattr(self, '_lock_timeout', 3),
                  ignore_limbo=True).get_buffer()
        if self.get_autocommit():
            try:
                self.connection.begin(tpb)
            except Database.DatabaseError as e:
                # The attachment is dead (e.g. the database was shut down and
                # brought back online). Outside of an atomic block no state
                # can be lost, so reconnect instead of failing every
                # subsequent operation.
                if 'shutdown' in str(e) and not self.in_atomic_block:
                    self.connect()
                    self.connection.begin(tpb)
                else:
                    raise

        cursor = self.connection.cursor()
        return FirebirdCursorWrapper(cursor, self.encoding, self.get_autocommit(), db=self)

    # Driver connections whose attachment died are parked here instead of
    # being closed: any interface release on a dead attachment goes over the
    # wire and may hang, so their finalizers must never run.
    _dead_connection_graveyard = []

    @staticmethod
    def _neutralize_interfaces(obj, _depth=0, _seen=None):
        """Best effort: zero the refcount of driver interface wrappers
        reachable from `obj` so their __del__ skips the wire call."""
        if _seen is None:
            _seen = set()
        if id(obj) in _seen or _depth > 4 or obj is None:
            return
        _seen.add(id(obj))
        if hasattr(obj, '_refcnt'):
            try:
                obj._refcnt = 0
            except Exception:
                pass
        values = []
        try:
            values.extend(vars(obj).values())
        except TypeError:
            pass
        if isinstance(obj, (list, tuple, set)):
            values.extend(obj)
        for value in values:
            if callable(getattr(value, '__call__', None)) and value.__class__.__name__ == 'weakref':
                continue
            module = getattr(type(value), '__module__', '')
            if module.startswith('firebird.') or isinstance(value, (list, tuple, set)):
                DatabaseWrapper._neutralize_interfaces(value, _depth + 1, _seen)

    def _discard_dead_connection(self, exc):
        """
        If `exc` signals that the attachment is gone (e.g. the database was
        shut down), park this wrapper's connection so the next operation
        opens a fresh one instead of failing forever.
        """
        if 'shutdown' in str(exc):
            self._connection_is_dead = True
            try:
                self.close()
            except Exception:
                pass

    def _close(self):
        if self.connection is not None:
            if getattr(self, '_connection_is_dead', False):
                self._connection_is_dead = False
                self._neutralize_interfaces(self.connection)
                self._dead_connection_graveyard.append(self.connection)
                self.connections = [c for c in self.connections if c is not self.connection]
                return
            with self.wrap_database_errors:
                try:
                    return self.connection.close()
                except Database.DatabaseError as e:
                    # Closing a dead attachment fails; there is nothing left
                    # to release on the server anyway.
                    if 'shutdown' not in str(e):
                        raise

    def _commit(self):
        if self.connection is not None:
            with self.wrap_database_errors:
                if self.connection.main_transaction.is_active():
                    try:
                        return self.connection.commit()
                    except Database.DatabaseError as e:
                        self._discard_dead_connection(e)
                        raise

    def _rollback(self):
        if self.connection is not None:
            with self.wrap_database_errors:
                if self.connection.main_transaction.is_active():
                    try:
                        return self.connection.rollback()
                    except Database.DatabaseError as e:
                        self._discard_dead_connection(e)
                        raise

    # ##### Foreign key constraints checks handling #####

    def disable_constraint_checking(self):
        """
        Never disables constraints. HR shares the database with MACS, and the
        original django-firebird code dropped every constraint in the database
        (MACS's included) to do this. Returning False tells Django there is
        nothing to re-enable, so constraint_checks_disabled() does nothing
        (loaddata and TransactionTestCase flushes call it).
        """
        return False

    def enable_constraint_checking(self):
        """
        Nothing was disabled, so there is nothing to re-enable.
        """

    def disable_constraints(self):
        """
        Not supported: constraints are never disabled on the shared database.
        """
        raise utils.NotSupportedError(
            "Firebird constraints are never disabled: HR shares the database with MACS"
        )

    def enable_constraints(self):
        """
        Not supported: constraints are never disabled on the shared database.
        """
        raise utils.NotSupportedError(
            "Firebird constraints are never disabled: HR shares the database with MACS"
        )

    def table_exists(self, table_name):
        """
        Checks whether a table with a specified name exists.

        Args:
            table_name (str): Table name for checking
        """
        sql = """
            select null from rdb$relations where rdb$system_flag=0 and rdb$view_blr is null and rdb$relation_name='%s'
        """ % self.ops.quote_name(str(table_name))  # same truncated name the DDL uses (Task 3 / Task 6)
        value = None
        with self.cursor() as cursor:
            cursor.execute(sql)
            value = cursor.fetchone()
        return True if value else False

    def get_drop_constraints(self, query):
        """
        Returns objects that should be dropped when restrictions are disabled.

        Args:
            query (str): SQL query to execute

        .. important::

           The server does not support explicit disabling of restrictions,
           therefore, implementation is made using additional tables.

        Note:
           If there is an error when execute query an exception is thrown.
        """
        value = []
        with self.cursor() as cursor:
            cursor.execute(query)
            for row in cursor.fetchall():
                map = {}
                for i, desc in enumerate(cursor.cursor.cursor.description):
                    map[desc[0]] = row[i]
                value.append(map)
        return value

    def _savepoint_allowed(self):
        # Savepoints cannot be created outside a transaction
        return self.features.uses_savepoints and not self.get_autocommit()

    # #### Backend-specific transaction management methods #####

    def _set_autocommit(self, autocommit):
        """
        Backend-specific implementation to enable or disable autocommit.

        FDB doesn't support auto-commit feature directly, but developers may
        achieve the similar result using explicit transaction start, taking
        advantage of default_action and its default value (commit).
        See:
        http://www.firebirdsql.org/file/documentation/drivers_documentation/python/fdb/usage-guide.html#auto-commit

        Pay attention at _close() method below
        """
        self.autocommit = autocommit
        with self.wrap_database_errors:
            self.connection.autocommit = autocommit

    # #### Backend-specific wrappers for PEP-249 connection methods #####

    def _close(self):
        if self.connection is not None:
            with self.wrap_database_errors:
                if self.autocommit and self.connection.main_transaction.is_active():
                    self.connection.commit()
                return self.connection.close()

    # #### Connection termination handling #####

    def is_usable(self):
        """
        Tests if the database connection is usable.
        This function may assume that self.connection is not None.
        """
        try:
            cur = self.connection.cursor()
            cur.execute('SELECT 1 FROM RDB$DATABASE')
        except DatabaseError:
            return False
        else:
            return True

    @cached_property
    def server_version(self):
        """
        Access method for engine_version property.
        engine_version return a full version in string format
        (ie: 'WI-V6.3.5.4926 Firebird 1.5' )
        """
        if not self._server_version:
            if not self.connection:
                self.cursor()
            self._server_version = self.connection.info.server_version
        return self._server_version


class ClampedDecimalType(str):
    """
    Column type format that caps NUMERIC/DECIMAL precision at Firebird 3's
    limit of 18 digits while keeping the field's integer digits.
    """
    def __mod__(self, params):
        params = dict(params)
        digits = int(params['max_digits'])
        places = int(params['decimal_places'])
        if digits > 18:
            params['max_digits'] = 18
            params['decimal_places'] = max(18 - (digits - places), 0)
        return str.__mod__(str(self), params)


class FirebirdCursorWrapper(object):
    """
    Django uses "format" style placeholders, but firebird uses "qmark" style.
    This fixes it -- but note that if you want to use a literal "%s" in a query,
    you'll need to use "%%s".
    """
    # -803: unique/PK violation, -625: validation error, -530: FK violation,
    # -297: CHECK constraint violation.
    codes_for_integrityerror = (-803, -625, -530, -297)

    def close(self, *args, **kwargs): # real signature unknown
        """ Closes the cursor. """
        self.cursor.close()

    def __init__(self, cursor, encoding, autocommit, db=None):
        self.cursor = cursor
        self.encoding = encoding
        self.autocommit = autocommit
        self.db = db

    def execute(self, query, params=None):
        if params is None:
            # Like other backends: no placeholder processing at all, the query
            # is passed through verbatim (a literal % stays a literal %).
            params = []
            q = smart_str(query, self.encoding)
        else:
            q = self.convert_query(query, len(params))
            params = [int(p) if isinstance(p, decimal.Decimal) and p == p.to_integral_value() else p
                      for p in params]
        try:
            return self.cursor.execute(q, params)
        except Database.IntegrityError as e:
            raise utils.IntegrityError(*self.error_info(e, query, params))
        except Database.DatabaseError as e:
            # Map some error codes to IntegrityError, since they seem to be
            # misclassified and Django would prefer the more logical place.
            # fdb: raise exception as tuple with (error_msg, sqlcode, error_code)
            code = self.get_sql_code(e)
            if code in self.codes_for_integrityerror:
                raise utils.IntegrityError(*self.error_info(e, query, params))
            busy = busy_error_for(e)
            if busy is not None:
                raise busy from e
            if self.db is not None:
                self.db._discard_dead_connection(e)
            raise

    def executemany(self, query, param_list):
        try:
            q = self.convert_query(query, len(param_list[0]))
            return self.cursor.executemany(q, param_list)
        except Database.IntegrityError as e:
            raise utils.IntegrityError(*self.error_info(e, query, param_list[0]))
        except Database.DatabaseError as e:
            # Map some error codes to IntegrityError, since they seem to be
            # misclassified and Django would prefer the more logical place.
            # fdb: raise exception as tuple with (error_msg, sqlcode, error_code)
            code = self.get_sql_code(e)
            if code in self.codes_for_integrityerror:
                raise utils.IntegrityError(*self.error_info(e, query, param_list[0]))
            busy = busy_error_for(e)
            if busy is not None:
                raise busy from e
            if self.db is not None:
                self.db._discard_dead_connection(e)
            raise

    def convert_query(self, query, num_params):
        # kinterbasdb tries to convert the passed SQL to string.
        # But if the connection charset is NONE, ASCII or OCTETS it will fail.
        # So we convert it to string first.
        # %-format even with zero parameters so that '%%' escapes collapse to
        # a literal '%' exactly as they do in parameterized queries.
        return smart_str(query % tuple("?" * num_params), self.encoding)

    def get_sql_code(self, e):
        try:
            sql_code = e.sqlcode
        except IndexError:
            sql_code = None
        return sql_code

    def error_info(self, e, q, p):
        # fdb: raise exception as tuple with (error_msg, sqlcode, error_code)
        # just when it uses exception_from_status function. Ticket #44.
        try:
            error_msg = e.args[0]
        except IndexError:
            error_msg = ''

        try:
            sql_code = e.sqlcode
        except IndexError:
            sql_code = None

        try:
            error_code = e.sqlstate
        except IndexError:
            error_code = None

        if q:
            sql_text = q % tuple(p)
        else:
            sql_text = q
        return tuple([error_msg, sql_code, error_code, {'sql': sql_text, 'params': p}])

    def __getattr__(self, attr):
        if attr in self.__dict__:
            return self.__dict__[attr]
        else:
            return getattr(self.cursor, attr)

    def __iter__(self):
        return iter(self.cursor)
