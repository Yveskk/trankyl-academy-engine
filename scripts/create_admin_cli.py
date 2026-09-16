"""Cree un compte admin en mode CLI (non-interactif).
Usage : python -m scripts.create_admin_cli email prenom nom mot_de_passe
"""
import sys

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import AdminUser


def main() -> None:
    if len(sys.argv) != 5:
        print("Usage: python -m scripts.create_admin_cli <email> <prenom> <nom> <mot_de_passe>")
        sys.exit(1)

    email, firstname, lastname, password = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.email == email).first():
            print(f"Un admin existe deja avec cet email: {email}")
            return
        admin = AdminUser(
            email=email,
            firstname=firstname,
            lastname=lastname,
            hashed_password=hash_password(password),
        )
        db.add(admin)
        db.commit()
        print(f"Admin cree avec succes : {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
