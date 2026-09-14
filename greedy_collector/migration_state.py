"""Recognize shipped revision ancestry; schema and trigger guards remain separate."""
from pathlib import Path
from alembic.script import ScriptDirectory
from alembic.script.revision import ResolutionError
from alembic.util.exc import CommandError
from sqlalchemy import inspect,text


def migration_scripts():
    return ScriptDirectory(str(Path(__file__).resolve().parents[1]/'migrations'))


def supports_revision(connection,required,*,scripts=None):
    if 'alembic_version' not in inspect(connection).get_table_names():return False
    current=connection.execute(text('SELECT version_num FROM alembic_version')).scalars().all()
    if not current:return False
    scripts=scripts or migration_scripts()
    def contains(identifier,seen):
        if identifier in seen:return False
        seen.add(identifier)
        revision=scripts.get_revision(identifier)
        if revision is None or revision.revision!=identifier:return False
        if identifier==required:return True
        parents=revision.down_revision
        if parents is None:return False
        if isinstance(parents,str):parents=(parents,)
        return any(contains(parent,seen.copy()) for parent in parents)
    try:return all(contains(identifier,set()) for identifier in current)
    except (ResolutionError,CommandError,KeyError):return False
