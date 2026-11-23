"""0019 — Módulos autorizados individualmente; NULL conserva accesos del rol."""
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS modulos_habilitados JSONB")
    op.execute("""
      DO $$ BEGIN
      IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = 'usuarios'::regclass
                     AND conname = 'ck_usuarios_modulos_json') THEN
        ALTER TABLE usuarios ADD CONSTRAINT ck_usuarios_modulos_json
        CHECK (modulos_habilitados IS NULL OR jsonb_typeof(modulos_habilitados) = 'array');
      END IF;
      END $$;
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE usuarios DROP CONSTRAINT IF EXISTS ck_usuarios_modulos_json")
    op.execute("ALTER TABLE usuarios DROP COLUMN IF EXISTS modulos_habilitados")
