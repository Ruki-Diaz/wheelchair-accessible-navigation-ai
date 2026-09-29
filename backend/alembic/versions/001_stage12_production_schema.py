"""Stage 12 production database schema

Revision ID: 001_stage12
Revises: 
Create Date: 2026-09-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '001_stage12'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users
    op.create_table(
        'users',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('email', sa.String(255), nullable=False),
        sa.Column('hashed_password', sa.String(255), nullable=False),
        sa.Column('full_name', sa.String(255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_users_email', 'users', ['email'], unique=True)

    # 2. user_preferences
    op.create_table(
        'user_preferences',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('preset_name', sa.String(64), nullable=False, server_default='manual_wheelchair'),
        sa.Column('preferences_json', sa.Text(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_user_preferences_user_id', 'user_preferences', ['user_id'], unique=True)

    # 3. saved_places
    op.create_table(
        'saved_places',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(128), nullable=False),
        sa.Column('display_name', sa.String(512), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('place_type', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_saved_places_user_id', 'saved_places', ['user_id'])
    op.create_index('ix_saved_places_user_label', 'saved_places', ['user_id', 'label'])

    # 4. saved_routes
    op.create_table(
        'saved_routes',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('origin_label', sa.String(256), nullable=False),
        sa.Column('origin_lat', sa.Float(), nullable=False),
        sa.Column('origin_lon', sa.Float(), nullable=False),
        sa.Column('dest_label', sa.String(256), nullable=False),
        sa.Column('dest_lat', sa.Float(), nullable=False),
        sa.Column('dest_lon', sa.Float(), nullable=False),
        sa.Column('preferences_snapshot_json', sa.Text(), nullable=False),
        sa.Column('distance_m', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_saved_routes_user_id', 'saved_routes', ['user_id'])

    # 5. community_observations
    op.create_table(
        'community_observations',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('category', sa.String(64), nullable=False),
        sa.Column('value', sa.String(64), nullable=False),
        sa.Column('latitude', sa.Float(), nullable=False),
        sa.Column('longitude', sa.Float(), nullable=False),
        sa.Column('osm_element_type', sa.String(16), nullable=True),
        sa.Column('osm_element_id', sa.String(64), nullable=True),
        sa.Column('contributor_id', sa.String(64), nullable=False),
        sa.Column('source_type', sa.String(32), nullable=False, server_default='community_contributor'),
        sa.Column('is_temporary', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('verification_status', sa.String(32), nullable=False, server_default='unverified'),
        sa.Column('confirmations_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('disputes_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_community_observations_category', 'community_observations', ['category'])
    op.create_index('ix_community_observations_latitude', 'community_observations', ['latitude'])
    op.create_index('ix_community_observations_longitude', 'community_observations', ['longitude'])
    op.create_index('ix_community_observations_osm_element_id', 'community_observations', ['osm_element_id'])
    op.create_index('ix_community_observations_contributor_id', 'community_observations', ['contributor_id'])
    op.create_index('ix_community_observations_expires_at', 'community_observations', ['expires_at'])
    op.create_index('ix_community_observations_verification_status', 'community_observations', ['verification_status'])
    op.create_index('ix_obs_lat_lon', 'community_observations', ['latitude', 'longitude'])
    op.create_index('ix_obs_status_category', 'community_observations', ['verification_status', 'category'])

    # 6. community_interactions
    op.create_table(
        'community_interactions',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('community_observations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('contributor_id', sa.String(64), nullable=False),
        sa.Column('interaction_type', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('observation_id', 'contributor_id', name='uq_obs_contributor_interaction'),
    )
    op.create_index('ix_community_interactions_observation_id', 'community_interactions', ['observation_id'])
    op.create_index('ix_community_interactions_contributor_id', 'community_interactions', ['contributor_id'])

    # 7. verification_events
    op.create_table(
        'verification_events',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('community_observations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('event_type', sa.String(32), nullable=False),
        sa.Column('previous_status', sa.String(32), nullable=False),
        sa.Column('new_status', sa.String(32), nullable=False),
        sa.Column('details_json', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_verification_events_observation_id', 'verification_events', ['observation_id'])

    # 8. evidence_conflicts
    op.create_table(
        'evidence_conflicts',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('community_observations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('osm_element_type', sa.String(16), nullable=False),
        sa.Column('osm_element_id', sa.String(64), nullable=False),
        sa.Column('conflict_type', sa.String(64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(32), nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('ix_evidence_conflicts_observation_id', 'evidence_conflicts', ['observation_id'])
    op.create_index('ix_evidence_conflicts_osm_element_id', 'evidence_conflicts', ['osm_element_id'])


def downgrade() -> None:
    op.drop_table('evidence_conflicts')
    op.drop_table('verification_events')
    op.drop_table('community_interactions')
    op.drop_table('community_observations')
    op.drop_table('saved_routes')
    op.drop_table('saved_places')
    op.drop_table('user_preferences')
    op.drop_table('users')
