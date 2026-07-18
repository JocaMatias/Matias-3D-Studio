"""Add project types, primary images and reconstruction versions.

Revision ID: 0002_versions
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_versions"
down_revision = "0001_legacy"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("project_type", sa.String(30), nullable=False, server_default="real_photos"))
    op.add_column("projects", sa.Column("category", sa.String(40), nullable=False, server_default="generic"))
    op.add_column("projects", sa.Column("primary_version_id", sa.String(), nullable=True))
    op.add_column("project_images", sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("project_images", sa.Column("consistency_score", sa.Float(), nullable=True))
    op.create_table(
        "reconstruction_versions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("engine", sa.String(60), nullable=True),
        sa.Column("reconstruction_type", sa.String(30), nullable=False),
        sa.Column("image_ids", sa.JSON(), nullable=False),
        sa.Column("primary_image_id", sa.String(), nullable=True),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("warnings", sa.JSON(), nullable=False),
        sa.Column("logs_path", sa.String(), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("project_id", "number", name="uq_project_version_number"),
    )
    op.create_index("ix_reconstruction_versions_project_id", "reconstruction_versions", ["project_id"])
    op.add_column("reconstruction_jobs", sa.Column("version_id", sa.String(), nullable=True))
    op.add_column("reconstruction_jobs", sa.Column("queue_id", sa.String(), nullable=True))
    op.add_column("reconstruction_jobs", sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("artifacts", sa.Column("version_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("artifacts", "version_id")
    op.drop_column("reconstruction_jobs", "created_at")
    op.drop_column("reconstruction_jobs", "queue_id")
    op.drop_column("reconstruction_jobs", "version_id")
    op.drop_index("ix_reconstruction_versions_project_id", table_name="reconstruction_versions")
    op.drop_table("reconstruction_versions")
    op.drop_column("project_images", "consistency_score")
    op.drop_column("project_images", "is_primary")
    op.drop_column("projects", "primary_version_id")
    op.drop_column("projects", "category")
    op.drop_column("projects", "project_type")
