"""create unified deal tables (Phase 0)

Revision ID: g6h7i8j9k0l1
Revises: f5a6b7c8d9e0
Create Date: 2026-06-15

Phase 0 of the unified deal schema migration:
  - Renames legacy 'deals' and 'deal_incentives' tables to 'legacy_*'
    so the new architecture can claim those names.
  - Creates 7 new tables:
      deal_statements → deals → deal_incentives → deal_incentive_slabs
                                                 → deal_incentive_slab_values
                                → deal_rules → deal_rule_conditions
  - Old tables remain fully operational (dual-write phase comes later).

NOTE: The 'deals' table is created as a regular table here.
      Hash partitioning (PARTITION BY HASH (tenant_id)) should be applied
      in a separate migration after data has been migrated, because
      PostgreSQL requires recreating the table to add partitioning.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = 'g6h7i8j9k0l1'
down_revision = 'f5a6b7c8d9e0'
branch_labels = None
depends_on = None


def upgrade():
    # ── Step 1: Free up 'deals' and 'deal_incentives' table names ────────────
    # Rename the old tables to legacy_* so the new architecture can use the
    # canonical names. PostgreSQL FKs reference by OID, so renaming doesn't
    # break existing FK relationships in the database.
    op.rename_table('deals', 'legacy_deals')
    op.execute("ALTER SEQUENCE IF EXISTS deals_id_seq RENAME TO legacy_deals_id_seq;")

    op.rename_table('deal_incentives', 'legacy_deal_incentives')
    op.execute("ALTER SEQUENCE IF EXISTS deal_incentives_id_seq RENAME TO legacy_deal_incentives_id_seq;")

    # ── Step 2: deal_statements ──────────────────────────────────────────────
    op.create_table(
        'deal_statements',
        sa.Column('id',            sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('tenant_id',     sa.Integer(),    sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_type',   sa.String(10),   nullable=False, server_default='manual'),   # manual | upload
        sa.Column('deal_type',     sa.String(10),   nullable=False, server_default='airline'),  # airline | b2b
        sa.Column('deal_tag',      sa.String(20),   nullable=False, server_default='standard'), # standard | adhoc
        sa.Column('deal_category', sa.String(20),   nullable=False, server_default='enterprise'), # enterprise | proprietary
        sa.Column('file_name',     sa.String(500),  nullable=True),
        sa.Column('file_type',     sa.String(20),   nullable=True),    # pdf / excel / word / image / manual
        sa.Column('file_url',      sa.String(1000), nullable=True),    # GCS path
        sa.Column('batch_id',      sa.String(36),   nullable=True),    # UUID string grouping upload session
        sa.Column('ai_confidence', sa.Numeric(5, 4), nullable=True),   # 0.0000–1.0000, NULL for manual
        sa.Column('column_map',    JSONB(),          nullable=True),   # {our_col: doc_col} extraction audit
        sa.Column('supplier_name', sa.String(300),  nullable=True),    # B2B batch supplier
        sa.Column('legacy_table',  sa.String(50),   nullable=True),    # migration audit: 'airline_deals'|'b2b_deals'|'legacy_deals'
        sa.Column('legacy_id',     sa.BigInteger(), nullable=True),    # migration audit: old PK value
        sa.Column('created_by_id', sa.Integer(),    sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at',    sa.DateTime(),   nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_deal_statements_tenant_created', 'deal_statements', ['tenant_id', sa.text('created_at DESC')])
    op.create_index('ix_deal_statements_batch',          'deal_statements', ['batch_id'])

    # ── Step 3: deals (unified — replaces airline_deals, b2b_deals, legacy_deals) ──
    op.create_table(
        'deals',
        sa.Column('id',           sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('statement_id', sa.BigInteger(), sa.ForeignKey('deal_statements.id', ondelete='CASCADE'), nullable=False),
        sa.Column('tenant_id',    sa.Integer(),    sa.ForeignKey('tenants.id', ondelete='CASCADE'), nullable=False),
        sa.Column('deal_type',    sa.String(10),   nullable=False, server_default='airline'),  # airline | b2b

        # Shared header
        sa.Column('source_agent',    sa.String(255), nullable=False, server_default='manual'),
        sa.Column('deal_maker_name', sa.String(255), nullable=True),
        sa.Column('remark',          sa.Text(),      nullable=True),
        sa.Column('airline_type',    sa.String(20),  nullable=True),   # GDS | LCC
        sa.Column('airline_name',    sa.String(255), nullable=True),
        sa.Column('valid_from',      sa.Date(),      nullable=True),
        sa.Column('valid_to',        sa.Date(),      nullable=True),
        sa.Column('entity',          sa.String(50),  nullable=True),

        # Airline-only
        sa.Column('contract_year', sa.String(50), nullable=True),   # FY | CY
        sa.Column('trigger_type',  sa.String(50), nullable=True),
        sa.Column('payout_type',   sa.String(50), nullable=True),
        sa.Column('iata_number',   sa.String(50), nullable=True),

        # B2B-only
        sa.Column('supplier_name', sa.String(255), nullable=True),

        # LCC fields (airline or B2B can be LCC)
        sa.Column('business_type',   sa.String(50),  nullable=True),
        sa.Column('entity_lcc',      sa.String(50),  nullable=True),
        sa.Column('login_id',        sa.String(100), nullable=True),
        sa.Column('variant',         sa.String(100), nullable=True),
        sa.Column('eco_commission',  sa.String(50),  nullable=True),
        sa.Column('peco_commission', sa.String(50),  nullable=True),
        sa.Column('bus_commission',  sa.String(50),  nullable=True),
        sa.Column('base_type',       sa.String(20),  nullable=True),
        sa.Column('valid_on',        sa.String(20),  nullable=True),

        # Approval & lifecycle
        sa.Column('status',                sa.String(20), nullable=False, server_default='pending_approval'),
        sa.Column('deal_lifecycle_status', sa.String(10), nullable=False, server_default='draft'),

        sa.Column('created_by_id', sa.Integer(),  sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at',    sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at',    sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    # Hot path 2: repository list (tenant + lifecycle + time)
    op.create_index('ix_deals_tenant_lifecycle_created', 'deals', ['tenant_id', 'deal_lifecycle_status', sa.text('created_at DESC')])
    # Hot path 5: closing preview — active deals by airline + type + tenant
    op.create_index(
        'ix_deals_tenant_airline_active', 'deals',
        ['tenant_id', 'airline_name', 'airline_type'],
        postgresql_where="deal_lifecycle_status = 'active'",
    )
    op.create_index('ix_deals_statement_id',  'deals', ['statement_id'])
    op.create_index(
        'ix_deals_tenant_status', 'deals',
        ['tenant_id', 'status'],
        postgresql_where="status = 'pending_approval'",
    )

    # ── Step 4: deal_incentives (normalized — replaces JSON blobs) ───────────
    op.create_table(
        'deal_incentives',
        sa.Column('id',             sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('deal_id',        sa.BigInteger(), sa.ForeignKey('deals.id', ondelete='CASCADE'), nullable=False),
        sa.Column('incentive_type', sa.String(100),  nullable=False),
        sa.Column('incentive_order', sa.SmallInteger(), nullable=False, server_default='0'),

        # Common header (PLB / Super PLB / Transaction Fee / Frontend / Backend / Push Action / Marketing Fund)
        sa.Column('contract_valid_from', sa.Date(),      nullable=True),
        sa.Column('contract_valid_to',   sa.Date(),      nullable=True),
        sa.Column('frequency',           sa.String(50),  nullable=True),
        sa.Column('flight_type',         sa.String(30),  nullable=True),
        sa.Column('class',               sa.String(30),  nullable=True),
        sa.Column('route_type',          sa.String(30),  nullable=True),
        sa.Column('trigger_based',       sa.String(50),  nullable=True),
        sa.Column('target_based',        sa.String(50),  nullable=True),   # Fixed | Slab
        sa.Column('target_calc_cols',    sa.String(100), nullable=True),
        sa.Column('payout_calc_cols',    sa.String(100), nullable=True),

        # Fixed-path payout
        sa.Column('amount_based_type',  sa.String(50),        nullable=True),
        sa.Column('base_target_amount', sa.Numeric(18, 4),    nullable=True),
        sa.Column('incentive_num_pct',  sa.String(50),        nullable=True),  # Number | Percentage
        sa.Column('incentive_amt_pct',  sa.Numeric(10, 4),    nullable=True),
        sa.Column('capped_incentive',   sa.Numeric(18, 4),    nullable=True),

        # Marketing Fund
        sa.Column('market_fund_type', sa.String(100),    nullable=True),
        sa.Column('exchange_rate',    sa.Numeric(12, 6), nullable=True),

        # Cashback
        sa.Column('cashback_period_from',  sa.Date(),         nullable=True),
        sa.Column('cashback_period_to',    sa.Date(),         nullable=True),
        sa.Column('cashback_target_type',  sa.String(100),    nullable=True),
        sa.Column('cashback_target_value', sa.Numeric(18, 4), nullable=True),

        # Deposit Incentive
        sa.Column('di_type',     sa.String(20), nullable=True),  # Bulk | Normal
        sa.Column('di_currency', sa.String(10), nullable=True),

        # Bulk → Single
        sa.Column('bulk_deposit_type',   sa.String(20),     nullable=True),  # Single | Tranches
        sa.Column('bulk_single_num_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('bulk_single_amt',     sa.Numeric(18, 4), nullable=True),
        sa.Column('bulk_single_capped',  sa.Numeric(18, 4), nullable=True),
        # Bulk → Tranches: [{from, to, num_pct, amt, capped}]
        sa.Column('bulk_tranches',       JSONB(),            nullable=True),

        # Normal → Bank Transfer
        sa.Column('normal_deposit_type',   sa.String(30),     nullable=True),  # Bank Transfer | Credit Card
        sa.Column('bank_transfer_num_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('bank_transfer_amt',     sa.Numeric(18, 4), nullable=True),

        # Normal → Credit Card
        sa.Column('credit_card_type',    sa.String(50),     nullable=True),
        sa.Column('bank_name',           sa.String(200),    nullable=True),
        sa.Column('credit_card_num_pct', sa.Numeric(10, 4), nullable=True),
        sa.Column('credit_card_amt',     sa.Numeric(18, 4), nullable=True),

        # Ancillary: {"Baggage": {"withType": "...", "numPct": "...", "amount": 0}, ...}
        sa.Column('ancillary_items', JSONB(), nullable=True),

        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),

        sa.UniqueConstraint('deal_id', 'incentive_type', name='uq_deal_incentives_deal_type'),
    )
    # Hot path 3: load incentives for a deal
    op.create_index('ix_deal_incentives_deal_id', 'deal_incentives', ['deal_id', 'incentive_order'])

    # ── Step 5: deal_incentive_slabs ─────────────────────────────────────────
    op.create_table(
        'deal_incentive_slabs',
        sa.Column('id',           sa.BigInteger(),   primary_key=True, autoincrement=True),
        sa.Column('incentive_id', sa.BigInteger(),   sa.ForeignKey('deal_incentives.id', ondelete='CASCADE'), nullable=False),
        sa.Column('slab_type',    sa.String(10),     nullable=False),   # amount | segment | si
        sa.Column('slab_order',   sa.SmallInteger(), nullable=False, server_default='0'),

        # Frequency qualifiers (amount slabs)
        sa.Column('quarterly_freq',   sa.String(20), nullable=True),  # Q1 | Q2 | Q3 | Q4
        sa.Column('half_yearly_freq', sa.String(20), nullable=True),  # H1 | H2

        # Amount-slab fields
        sa.Column('base_target_amt_num_pct', sa.String(50),     nullable=True),  # Percentage | Amount
        sa.Column('base_target_amount',      sa.Numeric(18, 4), nullable=True),

        # SI slab date range
        sa.Column('target_from', sa.Date(), nullable=True),
        sa.Column('target_to',   sa.Date(), nullable=True),

        # Segment / class qualifiers
        sa.Column('segment', sa.String(30), nullable=True),  # Domestic | International | Both
        sa.Column('class',   sa.String(30), nullable=True),  # Economy | Premium | Business | All

        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_deal_incentive_slabs_incentive_id', 'deal_incentive_slabs', ['incentive_id', 'slab_order'])
    # Enables query: "all deals where PLB slab quarterly_freq = Q1"
    op.create_index(
        'ix_deal_incentive_slabs_quarterly', 'deal_incentive_slabs',
        ['quarterly_freq'],
        postgresql_where='quarterly_freq IS NOT NULL',
    )

    # ── Step 6: deal_incentive_slab_values ───────────────────────────────────
    op.create_table(
        'deal_incentive_slab_values',
        sa.Column('id',         sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('slab_id',    sa.BigInteger(), sa.ForeignKey('deal_incentive_slabs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('value_key',  sa.String(100),  nullable=False),   # e.g. 'domestic_economy', 'capped'
        sa.Column('value_type', sa.String(20),   nullable=False, server_default='number'),  # number | percentage
        sa.Column('value',      sa.Numeric(18, 4), nullable=True),

        sa.UniqueConstraint('slab_id', 'value_key', name='uq_slab_value_key'),
    )
    op.create_index('ix_deal_incentive_slab_values_slab_id', 'deal_incentive_slab_values', ['slab_id'])

    # ── Step 7: deal_rules ───────────────────────────────────────────────────
    # Per-incentive-type rule — CRITICAL fix: PLB and Transaction Fee each get
    # their own rule set, unlike legacy deal_incl_excl_rules (deal-level, shared).
    op.create_table(
        'deal_rules',
        sa.Column('id',            sa.BigInteger(),   primary_key=True, autoincrement=True),
        sa.Column('incentive_id',  sa.BigInteger(),   sa.ForeignKey('deal_incentives.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rule_category', sa.String(60),     nullable=False),
        # trigger_inclusion | trigger_exclusion | payout_inclusion | payout_exclusion
        sa.Column('vice_versa',    sa.Boolean(),      nullable=False, server_default='false'),
        sa.Column('rule_order',    sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('created_at',    sa.DateTime(),     nullable=False, server_default=sa.text('now()')),
    )
    # Hot path 4: load rules for an incentive type
    op.create_index('ix_deal_rules_incentive_id', 'deal_rules', ['incentive_id', 'rule_order'])

    # ── Step 8: deal_rule_conditions ─────────────────────────────────────────
    op.create_table(
        'deal_rule_conditions',
        sa.Column('id',              sa.BigInteger(),   primary_key=True, autoincrement=True),
        sa.Column('rule_id',         sa.BigInteger(),   sa.ForeignKey('deal_rules.id', ondelete='CASCADE'), nullable=False),
        sa.Column('condition_field', sa.String(100),    nullable=False),
        # Maps to exclusion_evaluator.py field names:
        # continent, originAirport, destCountry, class, segment,
        # tourCode, fareTypeCategory, validFrom, validTo, dateExclusionTicket, etc.
        sa.Column('operator',        sa.String(20),     nullable=False, server_default='in'),
        # in | not_in | between | equals | starts_with
        sa.Column('value_list',      JSONB(),            nullable=True),   # for 'in' / 'not_in'
        sa.Column('value_from',      sa.String(100),    nullable=True),   # for 'between'
        sa.Column('value_to',        sa.String(100),    nullable=True),   # for 'between'
        sa.Column('value_text',      sa.String(500),    nullable=True),   # for 'equals' / 'starts_with'
        sa.Column('condition_order', sa.SmallInteger(), nullable=False, server_default='0'),
    )
    op.create_index('ix_deal_rule_conditions_rule_id', 'deal_rule_conditions', ['rule_id', 'condition_order'])

    # ── Covering indexes for approval inbox (Hot Path 1) ─────────────────────
    # Partial index on pending steps — inbox query becomes index-only on deal_approval_steps
    op.create_index(
        'ix_deal_approval_steps_inbox',
        'deal_approval_steps',
        ['assigned_user_id', 'status', 'step_order', 'deal_approval_id'],
        postgresql_where="status = 'pending'",
    )


def downgrade():
    # Remove the approval inbox index
    op.drop_index('ix_deal_approval_steps_inbox', table_name='deal_approval_steps')

    # Drop new tables in reverse dependency order
    op.drop_table('deal_rule_conditions')
    op.drop_table('deal_rules')
    op.drop_table('deal_incentive_slab_values')
    op.drop_table('deal_incentive_slabs')
    op.drop_table('deal_incentives')
    op.drop_table('deals')
    op.drop_table('deal_statements')

    # Restore original table names
    op.execute("ALTER SEQUENCE IF EXISTS legacy_deal_incentives_id_seq RENAME TO deal_incentives_id_seq;")
    op.rename_table('legacy_deal_incentives', 'deal_incentives')

    op.execute("ALTER SEQUENCE IF EXISTS legacy_deals_id_seq RENAME TO deals_id_seq;")
    op.rename_table('legacy_deals', 'deals')
