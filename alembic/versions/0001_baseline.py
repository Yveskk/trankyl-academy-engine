"""Baseline Academy : cree les tables academy_* manquantes (instance neuve, base
dev) et ajoute les colonnes Academy de `vendors`.

Sur la base de PRODUCTION ces tables existent deja (creees hors Alembic) :
ne PAS rejouer, faire `alembic stamp 0001_baseline`. Rejouer ne casserait
rien non plus (CREATE TABLE IF NOT EXISTS + colonnes gardees), mais le
stamp est la voie prevue.

Le DDL ci-dessous est un instantane fige des modeles au moment de cette
migration (ne pas le regenerer : les migrations suivantes ajoutent leurs
colonnes elles-memes).

Revision ID: 0001_baseline
Revises:
"""
import sqlalchemy as sa
from alembic import op

from app.db.migration_utils import add_column_if_missing, create_index_if_missing, has_table

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

TABLES_DDL = [
    """CREATE TABLE IF NOT EXISTS academy_banners (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	ordre INTEGER NOT NULL, 
	image_url VARCHAR(500) NOT NULL, 
	image_url_mobile VARCHAR(500), 
	is_active BOOL NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS academy_content_sections (
	`key` VARCHAR(100) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	subtitle TEXT, 
	title_en VARCHAR(255), 
	subtitle_en TEXT, 
	is_active BOOL NOT NULL, 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (`key`)
)""",
    """CREATE TABLE IF NOT EXISTS academy_metiers (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	code VARCHAR(100) NOT NULL, 
	nom VARCHAR(255) NOT NULL, 
	description TEXT, 
	nom_en VARCHAR(255), 
	description_en TEXT, 
	is_active BOOL NOT NULL, 
	PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS academy_otp_codes (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	identifier VARCHAR(255) NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	purpose VARCHAR(50) NOT NULL, 
	code VARCHAR(10) NOT NULL, 
	attempts INTEGER NOT NULL, 
	used BOOL NOT NULL, 
	expires_at DATETIME NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id)
)""",
    """CREATE TABLE IF NOT EXISTS academy_chat_sessions (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	client_id BIGINT UNSIGNED NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	updated_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (client_id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_contact_requests (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	client_id BIGINT UNSIGNED NOT NULL, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	initial_message TEXT, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	reviewed_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_academy_contact_request_client_vendor UNIQUE (client_id, vendor_id), 
	FOREIGN KEY(client_id) REFERENCES clients (client_id) ON DELETE CASCADE, 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_matching_requests (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	client_id BIGINT UNSIGNED NOT NULL, 
	metier_code VARCHAR(100) NOT NULL, 
	description TEXT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (client_id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_niveaux (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	metier_id BIGINT UNSIGNED NOT NULL, 
	numero INTEGER NOT NULL, 
	nom VARCHAR(255) NOT NULL, 
	description TEXT, 
	nom_en VARCHAR(255), 
	description_en TEXT, 
	date_debut DATE, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_academy_niveau_metier_numero UNIQUE (metier_id, numero), 
	FOREIGN KEY(metier_id) REFERENCES academy_metiers (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_reviews (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	client_id BIGINT UNSIGNED NOT NULL, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	rating INTEGER NOT NULL, 
	comment TEXT, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_academy_review_rating_range CHECK (rating >= 1 AND rating <= 5), 
	FOREIGN KEY(client_id) REFERENCES clients (client_id) ON DELETE CASCADE, 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_trust_scores (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	score_pct FLOAT NOT NULL, 
	rules_score FLOAT NOT NULL, 
	rules_breakdown_json TEXT NOT NULL, 
	llm_score FLOAT, 
	justification TEXT NOT NULL, 
	computed_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	UNIQUE (vendor_id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_certifications (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	niveau_id BIGINT UNSIGNED NOT NULL, 
	code VARCHAR(150) NOT NULL, 
	taxonomy_version INTEGER NOT NULL, 
	delivree_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_academy_certification_vendor_niveau UNIQUE (vendor_id, niveau_id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE, 
	FOREIGN KEY(niveau_id) REFERENCES academy_niveaux (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_chat_messages (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	session_id BIGINT UNSIGNED NOT NULL, 
	`role` VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES academy_chat_sessions (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_competences (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	niveau_id BIGINT UNSIGNED NOT NULL, 
	code VARCHAR(150) NOT NULL, 
	titre VARCHAR(255) NOT NULL, 
	description TEXT, 
	titre_en VARCHAR(255), 
	description_en TEXT, 
	ordre INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(niveau_id) REFERENCES academy_niveaux (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_contact_messages (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	contact_request_id BIGINT UNSIGNED NOT NULL, 
	sender_role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	`read` BOOL NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(contact_request_id) REFERENCES academy_contact_requests (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_matches (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	request_id BIGINT UNSIGNED NOT NULL, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	score INTEGER NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(request_id) REFERENCES academy_matching_requests (id) ON DELETE CASCADE, 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_niveau_enrollments (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	niveau_id BIGINT UNSIGNED NOT NULL, 
	metier_id BIGINT UNSIGNED NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	CONSTRAINT uq_academy_niveau_enrollment_vendor_niveau UNIQUE (vendor_id, niveau_id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE, 
	FOREIGN KEY(niveau_id) REFERENCES academy_niveaux (id) ON DELETE CASCADE, 
	FOREIGN KEY(metier_id) REFERENCES academy_metiers (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_messages (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	sender_id BIGINT UNSIGNED NOT NULL, 
	receiver_id BIGINT UNSIGNED NOT NULL, 
	match_id BIGINT UNSIGNED, 
	content TEXT NOT NULL, 
	`read` BOOL NOT NULL, 
	created_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(sender_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE, 
	FOREIGN KEY(receiver_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE, 
	FOREIGN KEY(match_id) REFERENCES academy_matches (id) ON DELETE SET NULL
)""",
    """CREATE TABLE IF NOT EXISTS academy_modules (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	competence_id BIGINT UNSIGNED NOT NULL, 
	code VARCHAR(150) NOT NULL, 
	titre VARCHAR(255) NOT NULL, 
	contenu TEXT, 
	titre_en VARCHAR(255), 
	contenu_en TEXT, 
	duree_heures FLOAT NOT NULL, 
	ordre INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(competence_id) REFERENCES academy_competences (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_enrollments (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	module_id BIGINT UNSIGNED NOT NULL, 
	statut VARCHAR(20) NOT NULL, 
	started_at DATETIME NOT NULL DEFAULT now(), 
	completed_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_academy_enrollment_vendor_module UNIQUE (vendor_id, module_id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE, 
	FOREIGN KEY(module_id) REFERENCES academy_modules (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_quizzes (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	module_id BIGINT UNSIGNED NOT NULL, 
	titre VARCHAR(255) NOT NULL, 
	seuil_reussite_pct INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (module_id), 
	FOREIGN KEY(module_id) REFERENCES academy_modules (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_quiz_attempts (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	vendor_id BIGINT UNSIGNED NOT NULL, 
	quiz_id BIGINT UNSIGNED NOT NULL, 
	score_pct FLOAT NOT NULL, 
	reussi BOOL NOT NULL, 
	submitted_at DATETIME NOT NULL DEFAULT now(), 
	PRIMARY KEY (id), 
	FOREIGN KEY(vendor_id) REFERENCES vendors (vendor_id) ON DELETE CASCADE, 
	FOREIGN KEY(quiz_id) REFERENCES academy_quizzes (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_quiz_questions (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	quiz_id BIGINT UNSIGNED NOT NULL, 
	texte TEXT NOT NULL, 
	ordre INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(quiz_id) REFERENCES academy_quizzes (id) ON DELETE CASCADE
)""",
    """CREATE TABLE IF NOT EXISTS academy_quiz_choices (
	id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT, 
	question_id BIGINT UNSIGNED NOT NULL, 
	texte VARCHAR(500) NOT NULL, 
	est_correct BOOL NOT NULL, 
	ordre INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(question_id) REFERENCES academy_quiz_questions (id) ON DELETE CASCADE
)""",
]

INDEXES = [
    ('ix_academy_metiers_code', 'academy_metiers', ['code'], True),
    ('ix_academy_otp_codes_identifier', 'academy_otp_codes', ['identifier'], False),
    ('ix_academy_certifications_code', 'academy_certifications', ['code'], False),
    ('ix_academy_competences_code', 'academy_competences', ['code'], True),
    ('ix_academy_modules_code', 'academy_modules', ['code'], True),
]


def upgrade() -> None:
    bind = op.get_bind()

    # Colonnes Academy ajoutees a la table partagee `vendors`.
    add_column_if_missing("vendors", sa.Column("vendor_academy_status", sa.String(20), nullable=True))
    add_column_if_missing("vendors", sa.Column("vendor_academy_verified", sa.Boolean(), nullable=False, server_default=sa.text("0")))
    add_column_if_missing("vendors", sa.Column("vendor_academy_verified_at", sa.DateTime(), nullable=True))
    add_column_if_missing("vendors", sa.Column("vendor_academy_reference_notes", sa.Text(), nullable=True))

    for ddl in TABLES_DDL:
        bind.exec_driver_sql(ddl)

    # Index declares sur les modeles (index=True / unique=True) : emis a part
    # par SQLAlchemy, donc crees ici (gardes si deja presents).
    for name, table, columns, unique in INDEXES:
        create_index_if_missing(name, table, columns, unique=unique)

    create_index_if_missing("ix_vendors_academy_status", "vendors", ["vendor_academy_status", "vendor_academy_verified"])


def downgrade() -> None:
    # Volontairement vide : on ne supprime jamais de donnees de production.
    pass
