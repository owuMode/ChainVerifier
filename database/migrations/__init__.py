# database/migrations/__init__.py
from database.migrations.runner import run_migrations

__all__ = ["run_migrations"]