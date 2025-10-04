import sqlite3
from pathlib import Path


def execute_init_sql(db_path: str, sql_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        with Path(sql_path).open("r", encoding="utf-8") as f:
            sql_script = f.read()
        conn.executescript(sql_script)


if __name__ == "__main__":
    execute_init_sql("tasukuya.db", "lib/init.sql")
