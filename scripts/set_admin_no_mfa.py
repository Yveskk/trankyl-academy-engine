"""Cree (ou met a jour) un compte SUPER-ADMIN dispense de 2FA : mot de passe seul.

Reserve aux bases de developpement (`*_dev_db`). Le drapeau n'agit que si le serveur est lance avec
ALLOW_MFA_EXEMPT=true. Ne touche a aucun autre compte.

Usage : PYTHONPATH=. python3 scripts/set_admin_no_mfa.py email@exemple.com 'MotDePasse'"""
import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"), override=True)
if not os.environ["DATABASE_URL"].rsplit("/", 1)[-1].split("?")[0].endswith("_dev_db"):
    sys.exit("Refus : ce script est reserve aux bases de developpement (*_dev_db).")
if len(sys.argv) != 3:
    sys.exit(__doc__)

from datetime import datetime  # noqa: E402

from sqlalchemy import text  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402

email, password = sys.argv[1].strip().lower(), sys.argv[2]
db = SessionLocal()
if not db.execute(text("SELECT 1 FROM user_types WHERE ust_id=1")).first():
    db.execute(text("INSERT INTO user_types (ust_id, ust_wording, ust_description, ust_roles) VALUES (1,'Admin','Administrateur','[\"ADMIN\"]')"))
row = db.execute(text("SELECT us_id FROM users WHERE LOWER(email)=:e"), {"e": email}).first()
now = datetime.utcnow()
if row:
    uid = row[0]
    db.execute(text("UPDATE users SET password=:p, us_user_type_id=1, us_updated_at=:n WHERE us_id=:i"), {"p": hash_password(password), "n": now, "i": uid})
    print(f"Compte existant #{uid} : mot de passe remis, role super-admin.")
else:
    db.execute(text("INSERT INTO users (us_firstname, us_lastname, email, password, us_user_type_id, us_created_at, us_updated_at) VALUES ('Yves','K',:e,:p,1,:n,:n)"), {"e": email, "p": hash_password(password), "n": now})
    uid = db.execute(text("SELECT us_id FROM users WHERE LOWER(email)=:e"), {"e": email}).scalar()
    print(f"Compte cree #{uid}.")
if db.execute(text("SELECT 1 FROM academy_admin_profiles WHERE user_id=:i"), {"i": uid}).first():
    db.execute(text("UPDATE academy_admin_profiles SET mfa_exempt=1, status='active', must_change_password=0, all_countries=1 WHERE user_id=:i"), {"i": uid})
else:
    db.execute(text("INSERT INTO academy_admin_profiles (user_id, status, must_change_password, mfa_exempt, all_countries) VALUES (:i,'active',0,1,1)"), {"i": uid})
db.execute(text("DELETE FROM academy_account_security WHERE role='admin' AND account_id=:i"), {"i": uid})  # repart sans verrouillage
db.commit()
print("2FA dispensee pour ce compte (si ALLOW_MFA_EXEMPT=true cote serveur).")
