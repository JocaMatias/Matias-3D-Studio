"""Introduce local single-image AI generation after quality profiles.

Revision ID: 0004_local_ai_generation
"""
from alembic import op


revision = "0004_local_ai_generation"
down_revision = "0004_quality_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'ai_generation' "
        "WHERE project_type IN ('ai_references', 'ai_multiview', 'hybrid')"
    )
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'reality_scan' "
        "WHERE project_type IN ('real_photos', 'precision_scan')"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'ai_generation' "
        "WHERE reconstruction_type IN ('ai_references', 'ai_multiview', 'hybrid')"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'reality_scan' "
        "WHERE reconstruction_type IN ('real_photos', 'precision_scan')"
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'ai_multiview' "
        "WHERE project_type = 'ai_generation'"
    )
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'precision_scan' "
        "WHERE project_type = 'reality_scan'"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'ai_multiview' "
        "WHERE reconstruction_type = 'ai_generation'"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'precision_scan' "
        "WHERE reconstruction_type = 'reality_scan'"
    )