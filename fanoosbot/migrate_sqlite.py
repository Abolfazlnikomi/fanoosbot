import argparse
import sqlite3
from pathlib import Path

from psycopg import sql

import bot
from database import connect

TABLES = (
    "users", "admins", "settings", "sections", "events", "resources", "faqs",
    "polls", "poll_options", "poll_votes", "quiz_questions", "quiz_options",
    "quiz_results", "tickets",
)


def migrate(source):
    source_path = Path(source).resolve(strict=True)
    with connect() as connection:
        existing = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname=current_schema() AND tablename=ANY(%s)",
            (list(TABLES),),
        ).fetchall()
        if existing:
            raise RuntimeError("Migration requires a new empty PostgreSQL database")
    source_connection = sqlite3.connect(source_path.as_uri() + "?mode=ro", uri=True)
    try:
        source_connection.execute("BEGIN")
        bot.init_db()
        with connect() as destination:
            destination.execute(sql.SQL("TRUNCATE {} RESTART IDENTITY").format(
                sql.SQL(", ").join(map(sql.Identifier, TABLES))))
            for table in TABLES:
                cursor = source_connection.execute(f'SELECT * FROM "{table}"')
                columns = [description[0] for description in cursor.description]
                statement = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table), sql.SQL(", ").join(map(sql.Identifier, columns)),
                    sql.SQL(", ").join(sql.Placeholder() for column in columns))
                count = 0
                with destination.cursor() as target:
                    while True:
                        rows = cursor.fetchmany(1000)
                        if not rows:
                            break
                        target.executemany(statement, rows)
                        count += len(rows)
                if destination.execute(sql.SQL("SELECT count(*) FROM {}").format(
                        sql.Identifier(table))).fetchone()[0] != count:
                    raise RuntimeError("Migration row count mismatch")
                if "id" in columns:
                    destination.execute(sql.SQL("""SELECT setval(pg_get_serial_sequence(%s, 'id'),
                        COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM {}""").format(sql.Identifier(table)),
                        (table,))
                print(f"{table}: {count}")
            destination.execute("""INSERT INTO admins(chat_id, name, added_at) VALUES (%s,%s,%s)
                ON CONFLICT DO NOTHING""", (bot.OWNER_ID, "مالک", bot.now_str()))
            for key, value in bot.DEFAULT_SETTINGS.items():
                destination.execute("INSERT INTO settings(key,value) VALUES (%s,%s) ON CONFLICT DO NOTHING",
                                    (key, value))
    finally:
        source_connection.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Offline SQLite to empty PostgreSQL migration")
    parser.add_argument("source", help="Path to the stopped bot's SQLite database")
    arguments = parser.parse_args()
    if bot.OWNER_ID <= 0:
        parser.error("Set OWNER_ID before migration")
    try:
        migrate(arguments.source)
    except Exception:
        raise SystemExit("Migration failed; data transaction rolled back. Check configuration and schema privately.") from None
    print("Migration committed successfully. SQLite source was not modified.")
