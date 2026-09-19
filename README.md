# trankyl-academy-engine

Backend FastAPI de Trankyl Academy — MIT license.


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
