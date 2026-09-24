"""Build-time checks for SQL translated by the PostgreSQL compatibility layer."""

from database_backend import _qmark_to_pyformat, _translate_sql


def main():
    assert _qmark_to_pyformat("SELECT '?' AS literal, ? AS value") == (
        "SELECT '?' AS literal, %s AS value"
    )
    assert _translate_sql(
        "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)"
    ).endswith("ON CONFLICT DO NOTHING")
    assert "ON CONFLICT (key) DO UPDATE" in _translate_sql(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)"
    )
    assert _translate_sql(
        "SELECT date(created_at) = date('now', 'localtime')"
    ) == "SELECT (created_at)::date = CURRENT_DATE"
    assert _translate_sql(
        "SELECT lesson_date <= date(schedule_date, '+14 days')"
    ) == "SELECT lesson_date <= ((schedule_date)::date + 14)"
    assert _qmark_to_pyformat("SELECT name LIKE '%piano%' AND id = ?") == (
        "SELECT name LIKE '%%piano%%' AND id = %s"
    )
    assert "BIGSERIAL PRIMARY KEY" in _translate_sql(
        "CREATE TABLE sample (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)"
    )
    assert _translate_sql(
        "ALTER TABLE parent_students ADD COLUMN IF NOT EXISTS can_pay INTEGER DEFAULT 1"
    ) == "ALTER TABLE parent_students ADD COLUMN IF NOT EXISTS can_pay INTEGER DEFAULT 1"
    group_concat = _translate_sql(
        "SELECT COALESCE(GROUP_CONCAT(DISTINCT COALESCE(s.name, ps.student_name)), '')"
    )
    assert "STRING_AGG(DISTINCT COALESCE(s.name, ps.student_name)::text, ',')" in group_concat
    print("PostgreSQL compatibility checks passed.")


if __name__ == "__main__":
    main()
