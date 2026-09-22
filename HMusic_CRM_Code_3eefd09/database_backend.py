"""Database compatibility helpers for the SQLite to PostgreSQL migration.

SQLite remains the default backend. PostgreSQL is enabled only when DATABASE_URL
starts with postgres:// or postgresql://.
"""

import os
import re
import sqlite3


DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()


def using_postgres():
    return DATABASE_URL.startswith(("postgres://", "postgresql://"))


def _qmark_to_pyformat(sql):
    """Replace SQLite qmark parameters without touching quoted literals."""
    output = []
    quote = None
    index = 0
    while index < len(sql):
        char = sql[index]
        if quote:
            output.append("%%" if char == "%" else char)
            if char == quote:
                if index + 1 < len(sql) and sql[index + 1] == quote:
                    output.append(sql[index + 1])
                    index += 1
                else:
                    quote = None
        elif char in ("'", '"'):
            quote = char
            output.append(char)
        elif char == "?":
            output.append("%s")
        elif char == "%":
            # psycopg parses percent signs even inside quoted SQL literals.
            # SQLite statements use qmark parameters, so every original percent
            # is literal and must be escaped for psycopg's pyformat parser.
            output.append("%%")
        else:
            output.append(char)
        index += 1
    return "".join(output)


def _translate_sql(sql):
    translated = _qmark_to_pyformat(sql)
    translated = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        translated,
        flags=re.IGNORECASE,
    )
    if re.search(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", sql, re.IGNORECASE):
        translated = translated.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"

    settings_replace = re.match(
        r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+settings\s*\(\s*key\s*,\s*value\s*\)\s*"
        r"VALUES\s*\(\s*%s\s*,\s*%s\s*\)\s*;?\s*$",
        translated,
        re.IGNORECASE | re.DOTALL,
    )
    if settings_replace:
        translated = (
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
        )

    translated = re.sub(
        r"date\(\s*([\w.]+)\s*,\s*'\+([0-9]+) days'\s*\)",
        r"((\1)::date + \2)",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"GROUP_CONCAT\(DISTINCT\s+COALESCE\(([^)]+)\)\)",
        r"STRING_AGG(DISTINCT COALESCE(\1)::text, ',')",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"date\(\s*'now'\s*,\s*'localtime'\s*\)",
        "CURRENT_DATE",
        translated,
        flags=re.IGNORECASE,
    )
    translated = re.sub(
        r"date\(\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\)",
        r"(\1)::date",
        translated,
        flags=re.IGNORECASE,
    )
    return translated


class HybridRow:
    """A small sqlite3.Row equivalent supporting index and name access."""

    def __init__(self, columns, values):
        self._columns = tuple(columns)
        self._values = tuple(values)
        self._mapping = dict(zip(self._columns, self._values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._mapping[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._mapping.keys()


class PostgresCursor:
    def __init__(self, connection):
        self.connection = connection
        self._cursor = connection._connection.cursor()
        self.lastrowid = None

    def _primary_key_for(self, table_name):
        cached = self.connection._primary_keys.get(table_name)
        if cached is not None:
            return cached
        with self.connection._connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                  ON tc.constraint_name = kcu.constraint_name
                 AND tc.table_schema = kcu.table_schema
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND tc.table_schema = current_schema()
                  AND tc.table_name = %s
                ORDER BY kcu.ordinal_position
                """,
                (table_name,),
            )
            rows = cursor.fetchall()
        key = rows[0][0] if len(rows) == 1 else ""
        self.connection._primary_keys[table_name] = key
        return key

    @property
    def description(self):
        return self._cursor.description

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def _execute_pragma_table_info(self, sql):
        match = re.match(r"\s*PRAGMA\s+table_info\(([^)]+)\)\s*", sql, re.IGNORECASE)
        if not match:
            return False
        table_name = match.group(1).strip().strip("'\"")
        self._cursor.execute(
            """
            SELECT
                ordinal_position - 1 AS cid,
                column_name AS name,
                data_type AS type,
                CASE WHEN is_nullable = 'NO' THEN 1 ELSE 0 END AS notnull,
                column_default AS dflt_value,
                CASE WHEN column_name IN (
                    SELECT kcu.column_name
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                      AND tc.table_schema = current_schema()
                      AND tc.table_name = %s
                ) THEN 1 ELSE 0 END AS pk
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = %s
            ORDER BY ordinal_position
            """,
            (table_name, table_name),
        )
        return True

    def _execute_sqlite_master_lookup(self, sql, params):
        if "sqlite_master" not in sql.lower():
            return False
        table_name = params[0] if params else ""
        self._cursor.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = current_schema() AND table_name = %s
            """,
            (table_name,),
        )
        return True

    def execute(self, sql, params=()):
        self.lastrowid = None
        try:
            if re.match(r"\s*BEGIN\s+IMMEDIATE\s*;?\s*$", sql, re.IGNORECASE):
                return self
            if self._execute_pragma_table_info(sql):
                return self
            if self._execute_sqlite_master_lookup(sql, params):
                return self
            translated = _translate_sql(sql)
            insert_match = re.match(
                r"\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)\b",
                translated,
                re.IGNORECASE,
            )
            primary_key = self._primary_key_for(insert_match.group(1)) if insert_match else ""
            wants_lastrowid = bool(primary_key and " RETURNING " not in translated.upper())
            if wants_lastrowid:
                translated = translated.rstrip().rstrip(";") + f' RETURNING "{primary_key}"'
            self._cursor.execute(translated, params or ())
            if wants_lastrowid and self._cursor.description:
                inserted = self._cursor.fetchone()
                self.lastrowid = inserted[0] if inserted else None
            return self
        except Exception as exc:
            self.connection._translate_exception(exc)

    def executemany(self, sql, parameter_rows):
        try:
            self._cursor.executemany(_translate_sql(sql), parameter_rows)
            return self
        except Exception as exc:
            self.connection._translate_exception(exc)

    def executescript(self, sql):
        try:
            self._cursor.execute(sql)
            return self
        except Exception as exc:
            self.connection._translate_exception(exc)

    def _convert_row(self, row):
        if row is None or self.connection.row_factory is None:
            return row
        columns = [item.name for item in self._cursor.description]
        return HybridRow(columns, row)

    def fetchone(self):
        return self._convert_row(self._cursor.fetchone())

    def fetchall(self):
        return [self._convert_row(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        while True:
            row = self.fetchone()
            if row is None:
                break
            yield row

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class PostgresConnection:
    def __init__(self, database_url):
        try:
            import psycopg
        except ImportError as exc:
            raise RuntimeError("psycopg is required when DATABASE_URL uses PostgreSQL") from exc
        self._psycopg = psycopg
        self._connection = psycopg.connect(database_url, autocommit=False)
        self._primary_keys = {}
        self.row_factory = None

    def _translate_exception(self, exc):
        if isinstance(exc, self._psycopg.IntegrityError):
            raise sqlite3.IntegrityError(str(exc)) from exc
        if isinstance(exc, self._psycopg.DatabaseError):
            raise sqlite3.OperationalError(str(exc)) from exc
        raise exc

    def cursor(self):
        return PostgresCursor(self)

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def executemany(self, sql, parameter_rows):
        return self.cursor().executemany(sql, parameter_rows)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()


def connect(sqlite_path, sqlite_connect, *args, **kwargs):
    if using_postgres():
        return PostgresConnection(DATABASE_URL)
    return sqlite_connect(sqlite_path, *args, **kwargs)
