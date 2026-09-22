"""ED-9B wallet-to-public-annotation predicate; no new tables or seed data."""
from alembic import op

revision='20260922_02'
down_revision='20260922_01'
branch_labels=None
depends_on=None
OLD="predicate IN ('mentioned_at', 'repository_contains', 'explorer_labeled_as', 'locally_labeled_as', 'publicly_listed_by', 'reverse_name_record', 'resolves_to', 'registration_record_for', 'certificate_names', 'observed_at', 'archived_at', 'uses_tracking_id', 'advertises_at', 'mentions_wallet')"
NEW=OLD[:-1]+", 'publicly_labeled_as')"

def change(up):
    connection=op.get_bind()
    if connection.dialect.name!='sqlite' or connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one():
        raise RuntimeError('Use the dedicated SQLite Alembic connection for ED-9B')
    if not connection.connection.driver_connection.in_transaction:connection.exec_driver_sql('BEGIN IMMEDIATE')
    if not up and connection.exec_driver_sql("SELECT 1 FROM discovery_results WHERE predicate='publicly_labeled_as' LIMIT 1").first():
        raise RuntimeError('Cannot downgrade while public GraphSense annotations are retained')
    # Results own no SQL immutability triggers. Referencing history stays intact.
    with op.batch_alter_table('discovery_results',recreate='always') as batch:
        batch.drop_constraint('ck_discovery_results_2',type_='check')
        batch.create_check_constraint('ck_discovery_results_2',NEW if up else OLD)
    if connection.exec_driver_sql('PRAGMA foreign_key_check').all():raise RuntimeError('ED-9B foreign-key validation failed')

def upgrade():change(True)
def downgrade():change(False)
