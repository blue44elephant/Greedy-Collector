"""Create Greedy Collector tables (immutable baseline).

Revision ID: 20260630_01
Revises:
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

# revision identifiers, used by Alembic.
revision = "20260630_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all Greedy Collector tables with explicit Alembic operations."""
    # Create tables in dependency order (parents before children)
    
    # Table: cases (no FK dependencies)
    op.create_table(
        'cases',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('status', sa.String(16), nullable=False, server_default='Open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: addresses (no FK dependencies)
    op.create_table(
        'addresses',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('chain', sa.String(32), nullable=False),
        sa.Column('address', sa.String(128), nullable=False),
        sa.Column('balance_native', sa.String(80), nullable=False, server_default='0'),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('risk_level', sa.String(16), nullable=False, server_default='Low'),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_activity', sa.DateTime(timezone=True), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'address', name='uq_address_chain')
    )
    
    # Table: labels (no FK dependencies)
    op.create_table(
        'labels',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('address', sa.String(128), nullable=False),
        sa.Column('chain', sa.String(32), nullable=False, server_default='any'),
        sa.Column('label', sa.String(255), nullable=False),
        sa.Column('type', sa.String(32), nullable=False, server_default='Unknown'),
        sa.Column('source', sa.String(255), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('last_updated', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'address', 'label', 'source', name='uq_label_source')
    )
    
    # Table: risk_rules (no FK dependencies)
    op.create_table(
        'risk_rules',
        sa.Column('id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('weight', sa.Integer(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('parameters', sa.JSON(), nullable=False, server_default='{}'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: risk_results (no FK dependencies)
    op.create_table(
        'risk_results',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('chain', sa.String(32), nullable=False),
        sa.Column('address', sa.String(128), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('level', sa.String(16), nullable=False),
        sa.Column('findings', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('calculated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: transactions (no FK dependencies)
    op.create_table(
        'transactions',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('tx_hash', sa.String(128), nullable=False),
        sa.Column('chain', sa.String(32), nullable=False),
        sa.Column('from_address', sa.String(128), nullable=False, server_default=''),
        sa.Column('to_address', sa.String(128), nullable=False, server_default=''),
        sa.Column('value_native', sa.String(80), nullable=False, server_default='0'),
        sa.Column('value_usd', sa.String(80), nullable=True),
        sa.Column('token_symbol', sa.String(32), nullable=False, server_default=''),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=True),
        sa.Column('block_number', sa.String(80), nullable=False, server_default=''),
        sa.Column('fee', sa.String(80), nullable=False, server_default='0'),
        sa.Column('direction', sa.String(16), nullable=False, server_default='unknown'),
        sa.Column('source_api', sa.String(64), nullable=False, server_default=''),
        sa.Column('raw_payload', sa.JSON(), nullable=False, server_default='{}'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'tx_hash', 'from_address', 'to_address', 'value_native', 'token_symbol', name='uq_transaction_transfer')
    )
    
    # Table: notification_settings (no FK dependencies)
    op.create_table(
        'notification_settings',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('channel', sa.String(32), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('configuration', sa.JSON(), nullable=False, server_default='{}'),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: kyc_screening_runs (no FK dependencies)
    op.create_table(
        'kyc_screening_runs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('query', sa.JSON(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='completed'),
        sa.Column('checked_sources', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('unavailable_sources', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('manual_sources', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: api_fetch_logs (no FK dependencies)
    op.create_table(
        'api_fetch_logs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('source', sa.String(128), nullable=False),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('detail', sa.Text(), nullable=False, server_default=''),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: watchlist_wallets (FK: case_id -> cases.id)
    op.create_table(
        'watchlist_wallets',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('chain', sa.String(32), nullable=False),
        sa.Column('address', sa.String(128), nullable=False),
        sa.Column('label', sa.String(255), nullable=False, server_default=''),
        sa.Column('case_id', sa.String(36), nullable=True),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('priority', sa.String(16), nullable=False, server_default='normal'),
        sa.Column('last_checked', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_seen_block', sa.String(80), nullable=True),
        sa.Column('last_seen_tx', sa.String(128), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chain', 'address', name='uq_watchlist_wallet')
    )
    
    # Table: wallet_alerts (FK: case_id -> cases.id)
    op.create_table(
        'wallet_alerts',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('wallet', sa.String(128), nullable=False),
        sa.Column('chain', sa.String(32), nullable=False),
        sa.Column('tx_hash', sa.String(128), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False),
        sa.Column('trigger_type', sa.String(64), nullable=False),
        sa.Column('severity', sa.String(16), nullable=False),
        sa.Column('risk_score', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('explanation', sa.Text(), nullable=False),
        sa.Column('counterparty', sa.String(128), nullable=True),
        sa.Column('amount', sa.String(80), nullable=True),
        sa.Column('token', sa.String(32), nullable=True),
        sa.Column('case_id', sa.String(36), nullable=True),
        sa.Column('status', sa.String(16), nullable=False, server_default='New'),
        sa.Column('notes', sa.Text(), nullable=False, server_default=''),
        sa.Column('dedupe_key', sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('dedupe_key')
    )
    
    # Table: case_entities (FK: case_id -> cases.id)
    op.create_table(
        'case_entities',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('case_id', sa.String(36), nullable=False),
        sa.Column('entity_type', sa.String(32), nullable=False),
        sa.Column('entity_ref', sa.String(255), nullable=False),
        sa.Column('metadata_json', sa.JSON(), nullable=False, server_default='{}'),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: analyst_notes (FK: case_id -> cases.id)
    op.create_table(
        'analyst_notes',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('case_id', sa.String(36), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('author', sa.String(128), nullable=False, server_default='analyst'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: monitoring_runs (FK: wallet_id -> watchlist_wallets.id)
    op.create_table(
        'monitoring_runs',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('wallet_id', sa.String(36), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(32), nullable=False, server_default='running'),
        sa.Column('new_transactions', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['wallet_id'], ['watchlist_wallets.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Table: kyc_matches (FK: run_id -> kyc_screening_runs.id)
    op.create_table(
        'kyc_matches',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('run_id', sa.String(36), nullable=False),
        sa.Column('source', sa.String(128), nullable=False),
        sa.Column('subject_name', sa.String(255), nullable=False),
        sa.Column('match_score', sa.Float(), nullable=False),
        sa.Column('match_rationale', sa.Text(), nullable=False),
        sa.Column('source_url', sa.Text(), nullable=False),
        sa.Column('categories', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('source_data', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('review_status', sa.String(32), nullable=False, server_default='Unreviewed'),
        sa.ForeignKeyConstraint(['run_id'], ['kyc_screening_runs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Create indexes in order
    op.create_index('ix_addresses_address', 'addresses', ['address'], unique=False)
    op.create_index('ix_addresses_chain', 'addresses', ['chain'], unique=False)
    op.create_index('ix_analyst_notes_case_id', 'analyst_notes', ['case_id'], unique=False)
    op.create_index('ix_api_fetch_logs_source', 'api_fetch_logs', ['source'], unique=False)
    op.create_index('ix_case_entities_case_id', 'case_entities', ['case_id'], unique=False)
    op.create_index('ix_kyc_matches_run_id', 'kyc_matches', ['run_id'], unique=False)
    op.create_index('ix_labels_address', 'labels', ['address'], unique=False)
    op.create_index('ix_risk_results_address', 'risk_results', ['address'], unique=False)
    op.create_index('ix_risk_results_chain', 'risk_results', ['chain'], unique=False)
    op.create_index('ix_transactions_chain', 'transactions', ['chain'], unique=False)
    op.create_index('ix_transactions_from_address', 'transactions', ['from_address'], unique=False)
    op.create_index('ix_transactions_timestamp', 'transactions', ['timestamp'], unique=False)
    op.create_index('ix_transactions_to_address', 'transactions', ['to_address'], unique=False)
    op.create_index('ix_transactions_tx_hash', 'transactions', ['tx_hash'], unique=False)
    op.create_index('ix_wallet_alerts_wallet', 'wallet_alerts', ['wallet'], unique=False)
    op.create_index('ix_watchlist_wallets_address', 'watchlist_wallets', ['address'], unique=False)
    op.create_index('ix_watchlist_wallets_chain', 'watchlist_wallets', ['chain'], unique=False)


def downgrade() -> None:
    """Drop all Greedy Collector tables in reverse dependency order."""
    # Drop indexes first
    op.drop_index('ix_watchlist_wallets_chain', 'watchlist_wallets')
    op.drop_index('ix_watchlist_wallets_address', 'watchlist_wallets')
    op.drop_index('ix_wallet_alerts_wallet', 'wallet_alerts')
    op.drop_index('ix_transactions_tx_hash', 'transactions')
    op.drop_index('ix_transactions_to_address', 'transactions')
    op.drop_index('ix_transactions_timestamp', 'transactions')
    op.drop_index('ix_transactions_from_address', 'transactions')
    op.drop_index('ix_transactions_chain', 'transactions')
    op.drop_index('ix_risk_results_chain', 'risk_results')
    op.drop_index('ix_risk_results_address', 'risk_results')
    op.drop_index('ix_labels_address', 'labels')
    op.drop_index('ix_kyc_matches_run_id', 'kyc_matches')
    op.drop_index('ix_case_entities_case_id', 'case_entities')
    op.drop_index('ix_api_fetch_logs_source', 'api_fetch_logs')
    op.drop_index('ix_analyst_notes_case_id', 'analyst_notes')
    op.drop_index('ix_addresses_chain', 'addresses')
    op.drop_index('ix_addresses_address', 'addresses')
    
    # Drop tables in reverse dependency order (children before parents)
    op.drop_table('kyc_matches')
    op.drop_table('monitoring_runs')
    op.drop_table('analyst_notes')
    op.drop_table('case_entities')
    op.drop_table('wallet_alerts')
    op.drop_table('watchlist_wallets')
    op.drop_table('api_fetch_logs')
    op.drop_table('kyc_screening_runs')
    op.drop_table('notification_settings')
    op.drop_table('transactions')
    op.drop_table('risk_results')
    op.drop_table('risk_rules')
    op.drop_table('labels')
    op.drop_table('addresses')
    op.drop_table('cases')
