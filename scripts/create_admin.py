"""Cree le premier compte admin (aucune inscription admin en libre-service
par design). Usage : python -m scripts.create_admin
"""

import getpass

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import AdminUser


def main() -> None:
    email = input("Email admin: ").strip()
    firstname = input("Prenom: ").strip()
    lastname = input("Nom: ").strip()
    password = getpass.getpass("Mot de passe: ")

    db = SessionLocal()
    try:
        if db.query(AdminUser).filter(AdminUser.email == email).first():
            print("Un admin existe deja avec cet email.")
            return
        admin = AdminUser(
            email=email,
            firstname=firstname,
            lastname=lastname,
            hashed_password=hash_password(password),
        )
        db.add(admin)
        db.commit()
        print(f"Admin cree : {email}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
