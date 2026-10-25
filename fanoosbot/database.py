import os
import re

import psycopg


def connect():
    required = ("PGHOST", "PGDATABASE", "PGUSER", "PGPASSWORD")
    if not all(os.environ.get(key) for key in required):
        raise RuntimeError("Set PGHOST, PGDATABASE, PGUSER and PGPASSWORD")
    return psycopg.connect(connect_timeout=10, options="-c statement_timeout=60000")


def postgres_sql(statement):
    statement = statement.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    statement = re.sub(r"\bchat_id INTEGER\b", "chat_id BIGINT", statement)
    statement = statement.replace(" IS ?", " IS NOT DISTINCT FROM ?")
    if "INSERT OR IGNORE" in statement:
        statement = statement.replace("INSERT OR IGNORE", "INSERT") + " ON CONFLICT DO NOTHING"
    return statement.replace("?", "%s")


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, statement, params=()):
        self.cursor.execute(postgres_sql(statement), params)
        return self

    def executescript(self, script):
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class Connection:
    def __init__(self):
        self.connection = connect()

    def cursor(self):
        return Cursor(self.connection.cursor())

    def execute(self, statement, params=()):
        return self.cursor().execute(statement, params)

    def commit(self):
        self.connection.commit()

    def close(self):
        self.connection.close()
