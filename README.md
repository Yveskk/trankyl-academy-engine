# trankyl-academy-engine

Backend FastAPI de Trankyl Academy — licence MIT.

C'est un service **independant** de `trankyl_backend_nodejs` : base MySQL dediee (`trankyl_academy`),
authentification propre, aucun lien avec les `vendor_id` de Trankyl pour l'instant. Les apprenants ne
deviennent des prestataires Trankyl (et donc lies a un `vendor_id`) qu'apres leur certification, via une
etape d'activation geree plus tard.

## Modele

- **Taxonomie** (gere via l'admin du site `trankyl-academy-content`) : `Metier` -> `Niveau` -> `Competence`
- **Curriculum** : chaque `Competence` se traduit en un ou plusieurs `Module` (2-3h), avec un `Quiz` optionnel
- **Progression** : `Enrollment` (inscription + statut) et `QuizAttempt` (tentatives corrigees automatiquement)
- **Certification** : delivree automatiquement quand tous les modules d'un niveau sont termines
  (code du type `nounou_niveau_2`)

## Prerequis

- Python 3.11+
- Une base MySQL nommee `trankyl_academy` (distincte de la base de `trankyl_backend_nodejs`)

## Lancer l'API

```bash
yarn start        # sans rechargement auto
yarn dev          # avec rechargement auto (developpement)
```

`yarn start`/`yarn dev` installent seuls les dependances Python au premier lancement (voir
"Comment ca marche" ci-dessous) et creent `.env` depuis `.env.example` s'il n'existe pas encore —
pensez alors a renseigner `DATABASE_URL` et `SECRET_KEY` puis relancer.

Documentation interactive (Swagger) : http://localhost:8000/docs — Redoc : http://localhost:8000/redoc

Pour tester les routes protegees depuis Swagger : "Try it out" sur `POST /auth/login` (ou `/auth/admin/login`),
copier `access_token` de la reponse, puis cliquer sur le bouton **Authorize** en haut de la page et coller le
token (sans le prefixe `Bearer`, Swagger l'ajoute tout seul).

### Comment ca marche

`yarn start`/`yarn dev` appellent `scripts/start.sh`, qui installe les dependances avec
`pip install --break-system-packages` (cette machine n'a pas `python3-venv`, donc pas d'environnement
virtuel possible sans `sudo apt install python3.12-venv` au prealable). Si vous installez `python3-venv`
et preferez un environnement virtuel isole, utilisez plutot l'installation manuelle :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # puis renseigner DATABASE_URL et SECRET_KEY
uvicorn app.main:app --reload
```

## Migrations

```bash
alembic revision --autogenerate -m "init"
alembic upgrade head
```

## Creer le premier compte admin

Il n'y a pas d'inscription admin en libre-service (par design) :

```bash
yarn create-admin
```
