"""`android.database.sqlite` facade backed by CPython's sqlite3.

Plugins store their own data in SQLite; the Android API is small (open, exec,
rawQuery, query, insert/update/delete, transactions).  The file lives in the
plugin files directory and uses the same SQL dialect as Android's SQLite.
"""

import os
import sqlite3


def _files_dir():
    try:
        import extera_ios

        value = extera_ios.host("paths.dir", kind="files")
        if isinstance(value, str) and value:
            return value
    except Exception:
        pass
    return os.path.expanduser("~")


class Cursor:
    def __init__(self, connection, sql="", args=()):
        self._connection = connection
        self._rows = []
        self._index = 0
        self._closed = False
        self._columns = []
        try:
            cursor = connection.execute(str(sql or ""), tuple(args or ()))
            self._columns = [item[0] for item in (cursor.description or [])]
            self._rows = cursor.fetchall()
        except Exception:
            self._rows = []
            self._columns = []

    def getCount(self):
        return len(self._rows)

    def moveToFirst(self):
        self._index = 0
        return bool(self._rows)

    def moveToNext(self):
        if self._index + 1 >= len(self._rows):
            self._index = len(self._rows)
            return False
        self._index += 1
        return True

    def moveToPosition(self, position):
        self._index = max(0, min(int(position), len(self._rows)))
        return self._index < len(self._rows)

    def move(self, offset):
        return self.moveToPosition(self._index + int(offset))

    def getPosition(self):
        return self._index

    def isAfterLast(self):
        return self._index >= len(self._rows)

    def isBeforeFirst(self):
        return self._index == 0

    def isFirst(self):
        return self._index == 0 and bool(self._rows)

    def isLast(self):
        return bool(self._rows) and self._index == len(self._rows) - 1

    def _row(self):
        if 0 <= self._index < len(self._rows):
            return self._rows[self._index]
        return None

    def getColumnIndex(self, name):
        try:
            return self._columns.index(str(name))
        except ValueError:
            return -1

    def getColumnIndexOrThrow(self, name):
        index = self.getColumnIndex(name)
        if index < 0:
            raise ValueError("column '%s' does not exist" % name)
        return index

    def getColumnName(self, index):
        try:
            return self._columns[int(index)]
        except (IndexError, ValueError):
            return ""

    def getColumnNames(self):
        return list(self._columns)

    def getColumnCount(self):
        return len(self._columns)

    def _value(self, index):
        row = self._row()
        if row is None:
            return None
        try:
            return row[int(index)]
        except (IndexError, TypeError, ValueError):
            return None

    def getString(self, index):
        value = self._value(index)
        return None if value is None else str(value)

    def getInt(self, index):
        try:
            return int(self._value(index) or 0)
        except (TypeError, ValueError):
            return 0

    def getLong(self, index):
        return self.getInt(index)

    def getDouble(self, index):
        try:
            return float(self._value(index) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def getFloat(self, index):
        return self.getDouble(index)

    def getBlob(self, index):
        value = self._value(index)
        return bytes(value) if isinstance(value, (bytes, bytearray)) else b""

    def isNull(self, index):
        return self._value(index) is None

    def close(self):
        self._closed = True
        self._rows = []
        return None

    def isClosed(self):
        return self._closed


class SQLiteStatement:
    def __init__(self, database, sql=""):
        self._database = database
        self._sql = str(sql or "")
        self._args = []

    def bindString(self, index, value):
        self._set(index, value)

    def bindLong(self, index, value):
        self._set(index, value)

    def bindDouble(self, index, value):
        self._set(index, value)

    def bindBlob(self, index, value):
        self._set(index, bytes(value or b""))

    def bindNull(self, index):
        self._set(index, None)

    def _set(self, index, value):
        position = int(index) - 1
        while len(self._args) <= position:
            self._args.append(None)
        self._args[position] = value

    def clearBindings(self):
        self._args = []

    def execute(self):
        self._database._connection.execute(self._sql, tuple(self._args))
        self._database._connection.commit()

    def executeInsert(self):
        cursor = self._database._connection.execute(self._sql, tuple(self._args))
        self._database._connection.commit()
        return cursor.lastrowid or 0

    def executeUpdateDelete(self):
        cursor = self._database._connection.execute(self._sql, tuple(self._args))
        self._database._connection.commit()
        return cursor.rowcount if cursor.rowcount is not None else 0

    def close(self):
        return None


class SQLiteDatabase:
    CONFLICT_ROLLBACK = 1
    CONFLICT_ABORT = 2
    CONFLICT_FAIL = 3
    CONFLICT_IGNORE = 4
    CONFLICT_REPLACE = 5

    OPEN_READWRITE = 0
    OPEN_READONLY = 1
    CREATE_IF_NECESSARY = 0x10000000
    NO_LOCALIZED_COLLATORS = 0x00000010

    def __init__(self, path=":memory:", *args, **kwargs):
        self._path = str(path or ":memory:")
        self._connection = sqlite3.connect(self._path, check_same_thread=False)
        self._connection.row_factory = None
        self._in_transaction = False

    @classmethod
    def openDatabase(cls, path, factory=None, flags=0, *args, **kwargs):
        return cls(path)

    @classmethod
    def openOrCreateDatabase(cls, path, factory=None, *args, **kwargs):
        return cls(path)

    def getPath(self):
        return self._path

    def isOpen(self):
        return self._connection is not None

    def close(self):
        try:
            self._connection.close()
        except Exception:
            pass
        self._connection = None
        return None

    def execSQL(self, sql, args=()):
        self._connection.execute(str(sql or ""), tuple(args or ()))
        self._connection.commit()
        return None

    def rawQuery(self, sql, args=()):
        return Cursor(self._connection, sql, args)

    def query(self, table, columns=None, selection=None, selection_args=None,
              group_by=None, having=None, order_by=None, limit=None,
              distinct=False, *args, **kwargs):
        sql = "SELECT "
        if distinct:
            sql += "DISTINCT "
        sql += ", ".join(str(column) for column in columns) if columns else "*"
        sql += " FROM " + str(table)
        if selection:
            sql += " WHERE " + str(selection)
        if group_by:
            sql += " GROUP BY " + str(group_by)
        if having:
            sql += " HAVING " + str(having)
        if order_by:
            sql += " ORDER BY " + str(order_by)
        if limit is not None:
            sql += " LIMIT " + str(limit)
        return Cursor(self._connection, sql, selection_args or ())

    @staticmethod
    def _values(values):
        if values is None:
            return {}
        if isinstance(values, dict):
            return dict(values)
        if hasattr(values, "toMap"):
            return values.toMap()
        if hasattr(values, "keySet") and hasattr(values, "get"):
            return {key: values.get(key) for key in values.keySet()}
        return dict(values)

    def insert(self, table, null_column_hack=None, values=None):
        data = self._values(values)
        if not data:
            return -1
        columns = list(data.keys())
        placeholders = ", ".join("?" for _ in columns)
        sql = "INSERT INTO %s (%s) VALUES (%s)" % (
            table,
            ", ".join(columns),
            placeholders,
        )
        cursor = self._connection.execute(sql, tuple(data[column] for column in columns))
        self._connection.commit()
        return cursor.lastrowid or 0

    def insertOrThrow(self, table, null_column_hack=None, values=None):
        return self.insert(table, null_column_hack, values)

    def replace(self, table, null_column_hack=None, values=None):
        return self.insert(table, null_column_hack, values)

    def update(self, table, values, where_clause=None, where_args=None):
        data = self._values(values)
        if not data:
            return 0
        assignments = ", ".join("%s = ?" % column for column in data.keys())
        sql = "UPDATE %s SET %s" % (table, assignments)
        if where_clause:
            sql += " WHERE " + str(where_clause)
        cursor = self._connection.execute(
            sql, tuple(data.values()) + tuple(where_args or ())
        )
        self._connection.commit()
        return cursor.rowcount or 0

    def delete(self, table, where_clause=None, where_args=None):
        sql = "DELETE FROM %s" % table
        if where_clause:
            sql += " WHERE " + str(where_clause)
        cursor = self._connection.execute(sql, tuple(where_args or ()))
        self._connection.commit()
        return cursor.rowcount or 0

    def compileStatement(self, sql):
        return SQLiteStatement(self, sql)

    def beginTransaction(self):
        self._connection.execute("BEGIN")
        self._in_transaction = True
        return None

    def beginTransactionNonExclusive(self):
        return self.beginTransaction()

    def setTransactionSuccessful(self):
        self._transaction_success = True
        return None

    def endTransaction(self):
        try:
            if getattr(self, "_transaction_success", False):
                self._connection.commit()
            else:
                self._connection.rollback()
        finally:
            self._transaction_success = False
            self._in_transaction = False
        return None

    def inTransaction(self):
        return bool(self._in_transaction)

    def getVersion(self):
        cursor = self._connection.execute("PRAGMA user_version")
        row = cursor.fetchone()
        return int(row[0]) if row else 0

    def setVersion(self, version):
        self._connection.execute("PRAGMA user_version = %d" % int(version))
        self._connection.commit()
        return None

    def isReadOnly(self):
        try:
            return bool(self._connection.execute("PRAGMA query_only").fetchone()[0])
        except Exception:
            return False

    def setForeignKeyConstraintsEnabled(self, value):
        return None

    def enableWriteAheadLogging(self):
        return True

    def disableWriteAheadLogging(self):
        return None

    def setLocale(self, locale):
        return None


class SQLiteOpenHelper:
    def __init__(self, context=None, name=None, version=None, factory=None,
                 error_handler=None):
        self._context = context
        self._name = str(name or ":memory:")
        self._version = int(version or 1)
        self._database = None

    def _path(self):
        if self._name == ":memory:" or os.path.isabs(self._name):
            return self._name
        return os.path.join(_files_dir(), self._name)

    def getWritableDatabase(self):
        if self._database is not None and self._database.isOpen():
            return self._database
        database = SQLiteDatabase(self._path())
        current = database.getVersion()
        if current == 0:
            self.onCreate(database)
            database.setVersion(self._version)
        elif current < self._version:
            self.onUpgrade(database, current, self._version)
            database.setVersion(self._version)
        self._database = database
        return database

    def getReadableDatabase(self):
        return self.getWritableDatabase()

    def close(self):
        if self._database is not None:
            self._database.close()
            self._database = None
        return None

    def onCreate(self, database):
        return None

    def onUpgrade(self, database, old_version, new_version):
        return None

    def onDowngrade(self, database, old_version, new_version):
        return None

    def onOpen(self, database):
        return None

    def setWriteAheadLoggingEnabled(self, enabled):
        return None
