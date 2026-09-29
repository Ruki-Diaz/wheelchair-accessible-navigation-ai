"""Stage 13 destinations and venue entrances schema update

Revision ID: 002_stage13
Revises: 001_stage12
Create Date: 2026-09-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002_stage13'
down_revision: Union[str, None] = '001_stage12'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add preferred entrance columns to saved_places
    op.add_column('saved_places', sa.Column('preferred_entrance_id', sa.String(64), nullable=True))
    op.add_column('saved_places', sa.Column('preferred_entrance_name', sa.String(256), nullable=True))

    # 2. Create venue_entrances table
    op.create_table(
        'venue_entrances',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('venue_id', sa.String(64), nullable=False),
        sa.Column('name', sa.String(256), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('entrance_type', sa.String(32), nullable=False, server_default='main'),
        sa.Column('wheelchair', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('step_free', sa.Boolean(), nullable=True),
        sa.Column('steps_count', sa.Integer(), nullable=True),
        sa.Column('ramp', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('automatic_door', sa.Boolean(), nullable=True),
        sa.Column('door_type', sa.String(32), nullable=False, server_default='unknown'),
        sa.Column('door_width_m', sa.Float(), nullable=True),
        sa.Column('source', sa.String(64), nullable=False, server_default='openstreetmap'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_venue_entrances_venue_id', 'venue_entrances', ['venue_id'])


def downgrade() -> None:
    op.drop_index('ix_venue_entrances_venue_id', table_name='venue_entrances')
    op.drop_table('venue_entrances')
    op.drop_column('saved_places', 'preferred_entrance_name')
    op.drop_column('saved_places', 'preferred_entrance_id')
