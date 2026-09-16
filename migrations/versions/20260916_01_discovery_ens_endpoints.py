"""ED-8A0 output-only ENS endpoints. Frozen schema; no network or seed data."""
from alembic import op

revision = '20260916_01'
down_revision = '20260915_01'
branch_labels = None
depends_on = None

OLD_KIND = "kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation')"
NEW_KIND = "kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation', 'ens_name')"
ENS_NAMESPACE = "kind != 'ens_name' OR namespace = 'ethereum'"


def _begin():
    connection = op.get_bind()
    if connection.dialect.name != 'sqlite':
        raise RuntimeError('ED-8A0 currently requires SQLite')
    # As in ED-6, use the dedicated offline deployment connection. Application
    # connections keep foreign keys enabled; never toggle their integrity mode.
    if connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one():
        raise RuntimeError('Use the dedicated Alembic migration connection for ED-8A0')
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    return connection


def _subjects(up):
    # Reflection preserves columns, defaults, PK, unique constraint and index.
    # There are no triggers owned by discovery_subjects. Child tables, their
    # RESTRICT references and immutable-history triggers are not rebuilt.
    with op.batch_alter_table('discovery_subjects', recreate='always') as batch:
        batch.drop_constraint('ck_discovery_subjects_1', type_='check')
        batch.create_check_constraint('ck_discovery_subjects_1', NEW_KIND if up else OLD_KIND)
        if up:
            batch.create_check_constraint('ck_discovery_subjects_8', ENS_NAMESPACE)
        else:
            batch.drop_constraint('ck_discovery_subjects_8', type_='check')


def _validate(connection):
    if connection.exec_driver_sql('PRAGMA foreign_key_check').all():
        raise RuntimeError('ED-8A0 migration failed foreign-key validation')


def upgrade():
    connection = _begin()
    _subjects(True)
    _validate(connection)


def downgrade():
    connection = _begin()
    if connection.exec_driver_sql("SELECT 1 FROM discovery_subjects WHERE kind = 'ens_name' LIMIT 1").first():
        raise RuntimeError('Cannot downgrade while typed ENS endpoints exist; retained history is protected')
    _subjects(False)
    _validate(connection)
