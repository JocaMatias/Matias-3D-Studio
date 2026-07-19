"""Normalize projects to the three public generation modes.

Revision ID: 0003_generation_modes
"""
from alembic import op


revision = "0003_generation_modes"
down_revision = "0002_versions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'ai_multiview' WHERE project_type = 'ai_references'"
    )
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'hybrid' WHERE project_type = 'real_photos'"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'ai_multiview' "
        "WHERE reconstruction_type = 'ai_references'"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'hybrid' "
        "WHERE reconstruction_type = 'real_photos'"
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'ai_references' WHERE project_type = 'ai_multiview'"
    )
    connection.exec_driver_sql(
        "UPDATE projects SET project_type = 'real_photos' WHERE project_type = 'hybrid'"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'ai_references' "
        "WHERE reconstruction_type = 'ai_multiview'"
    )
    connection.exec_driver_sql(
        "UPDATE reconstruction_versions SET reconstruction_type = 'real_photos' "
        "WHERE reconstruction_type = 'hybrid'"
    )
