import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from backend.app.core.config import settings

# Engine configuration (PostgreSQL on AWS RDS, or SQLite for local runs and tests)
database_url = settings.DATABASE_URL
# The live server never falls back to a local file: it would start empty and lose uploads on the next rebuild
if settings.ENVIRONMENT == "production" and (not database_url or database_url.startswith("sqlite")):
    raise RuntimeError("DATABASE_URL is missing (or points to a local SQLite file) in backend/.env.production: "
                       "set it to the database before starting the server")
if not database_url:
    database_url = "sqlite:///./finance_platform.db"     # local runs and tests only
# Off the live server, the hosted database is never used by chance: a test or check started without its local
# database would read and write the firms' real data.
# A script that means to use it (a law library search) says so with ALLOW_LIVE_DB=1. The live server runs in a
# container (/.dockerenv), where this never applies.
if (settings.ENVIRONMENT != "production" and not os.path.exists("/.dockerenv")
        and not database_url.startswith("sqlite") and os.environ.get("ALLOW_LIVE_DB") != "1"):
    raise RuntimeError("DATABASE_URL points to a hosted database outside the live server: set DATABASE_URL to a "
                       "local sqlite file first, or ALLOW_LIVE_DB=1 for a script that means to use it")

# Handle sslmode in postgresql URLs if needed
engine_kwargs = {"pool_pre_ping": True}
if "sqlite" not in database_url:
    engine_kwargs.update({
        "pool_size": 10,
        "max_overflow": 20,
        "pool_recycle": 300,
        # TCP keep-alive pings, so the hosted database doesn't drop a connection that sits quiet in the middle of
        # a long request (e.g. a large upload while the AI maps accounts)
        "connect_args": {"keepalives": 1, "keepalives_idle": 30, "keepalives_interval": 10, "keepalives_count": 5},
    })

engine = create_engine(database_url, **engine_kwargs)


# AWS RDS keeps its password in Secrets Manager (DATABASE_SECRET_ARN) and changes it every 7 days: DATABASE_URL then
# has no password, and each new connection takes it from the secret, fetched again when the database refuses it
if settings.DATABASE_SECRET_ARN:
    import json
    from sqlalchemy import event

    _secret = {}

    def _db_password(fresh: bool = False) -> str:
        if fresh or "password" not in _secret:
            from backend.app.core.s3 import aws_client
            region = settings.DATABASE_SECRET_ARN.split(":")[3]
            value = aws_client("secretsmanager", region).get_secret_value(SecretId=settings.DATABASE_SECRET_ARN)
            _secret["password"] = json.loads(value["SecretString"])["password"]
        return _secret["password"]

    @event.listens_for(engine, "do_connect")
    def _connect_with_secret(dialect, conn_rec, cargs, cparams):
        cparams["password"] = _db_password()
        try:
            return dialect.connect(*cargs, **cparams)
        except Exception as e:
            if "password authentication failed" not in str(e):
                raise
            cparams["password"] = _db_password(fresh=True)       # the password was changed since it was read
            return dialect.connect(*cargs, **cparams)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def create_table(table) -> None:
    """A new table only, made on first use, leaving every existing table as it is. Each server worker imports the models
    at start-up: the worker that loses the race to create it finds it made and carries on."""
    try:
        table.create(bind=engine, checkfirst=True)
    except Exception:
        table.create(bind=engine, checkfirst=True)

def add_columns(table_name: str, columns: dict) -> None:
    """New nullable columns on an existing table, added only when missing (nothing else in the table changes): the
    column name -> its SQL type ("VARCHAR(40)", "DATE", "FLOAT"). Each server worker runs it at start-up; a worker
    that loses the race finds the column there and carries on."""
    from sqlalchemy import inspect, text
    try:
        have = {c["name"] for c in inspect(engine).get_columns(table_name)}
    except Exception:
        return                                      # the table is not made yet: create_table makes it whole
    for name, sql_type in columns.items():
        if name in have:
            continue
        try:
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE {table_name} ADD COLUMN {name} {sql_type}'))
        except Exception:
            if name not in {c["name"] for c in inspect(engine).get_columns(table_name)}:
                raise


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
