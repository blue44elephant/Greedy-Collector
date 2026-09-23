"""MC-1 structural chain IDs; all existing rows and unrelated constraints retained."""
from alembic import op

revision='20260923_01'
down_revision='20260922_02'
branch_labels=None
depends_on=None
CHANGES=(
    ('attribution_claims','ck_attribution_claims_2',"chain IN ('bitcoin','ethereum')","length(chain) BETWEEN 1 AND 32 AND substr(chain,1,1) GLOB '[a-z]' AND chain NOT GLOB '*[^a-z0-9_]*'"),
    ('discovery_subjects','ck_discovery_subjects_6',"kind != 'blockchain_address' OR namespace IN ('bitcoin','ethereum')","kind != 'blockchain_address' OR (length(namespace) BETWEEN 1 AND 32 AND substr(namespace,1,1) GLOB '[a-z]' AND namespace NOT GLOB '*[^a-z0-9_]*')"))

def change(up):
    c=op.get_bind()
    if c.dialect.name!='sqlite' or c.exec_driver_sql('PRAGMA foreign_keys').scalar_one():
        raise RuntimeError('Use the dedicated SQLite Alembic connection for MC-1')
    if not c.connection.driver_connection.in_transaction:c.exec_driver_sql('BEGIN IMMEDIATE')
    if not up:
        for table,field,where in [('attribution_claims','chain','1=1'),('discovery_subjects','namespace',"kind='blockchain_address'")]:
            if c.exec_driver_sql(f"SELECT 1 FROM {table} WHERE {where} AND {field} NOT IN ('bitcoin','ethereum') LIMIT 1").first():
                raise RuntimeError('Cannot downgrade while additional chain records are retained')
    # SQLite table rebuilds invalidate triggers on other tables referencing these
    # parents. Preserve exact SQL and reinstall within the same transaction.
    triggers=c.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='trigger'").all()
    for name,sql in triggers:c.exec_driver_sql('DROP TRIGGER "'+name.replace('"','""')+'"')
    for table,name,old,new in CHANGES:
        with op.batch_alter_table(table,recreate='always') as batch:
            batch.drop_constraint(name,type_='check')
            batch.create_check_constraint(name,new if up else old)
    for name,sql in triggers:c.exec_driver_sql(sql)
    if c.exec_driver_sql('PRAGMA foreign_key_check').all():raise RuntimeError('MC-1 foreign-key validation failed')

def upgrade():change(True)
def downgrade():change(False)
