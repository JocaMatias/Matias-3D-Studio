"""Add conservative object profiles used by reconstruction and repair.

Revision ID: 0004_quality_profiles
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_quality_profiles"
down_revision = "0003_generation_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.add_column(sa.Column("object_profile", sa.String(length=32), nullable=False, server_default="auto"))


def downgrade() -> None:
    with op.batch_alter_table("projects") as batch:
        batch.drop_column("object_profile")
