# trankyl-academy-engine

Backend FastAPI de Trankyl Academy — MIT license.

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

## Score de confiance & moteur de matching

Le matching (recherche publique de prestataires `GET /matching/prestataires` et l'assistant IA SITA)
n'expose **jamais** un apprenant qui n'est pas explicitement verifie par un admin, quelles que soient ses
certifications. C'est un blocage automatique, applique au niveau service (`is_matching_eligible`), donc
impossible a contourner depuis le frontend.

### Score de confiance (`app/services/trust_score.py`)

Calcule via `POST .../verification` (admin) ou `GET /matching/prestataires/{id}/trust-score`, mis en cache
dans la table `trust_scores`. Deux composantes :

1. **Regles** (faits objectifs verifiables en base), ponderation documentee dans `RULES_WEIGHTS` :
   - Certifications obtenues / niveaux suivis — **40%**
   - Moyenne des scores de quiz — **30%**
   - Modules termines / modules commences — **15%**
   - Compte verifie manuellement par un admin — **15%**
2. **Analyse IA des references** (Gemini) : si l'apprenant a fourni un texte de references/temoignages
   (`Apprenant.reference_notes`), SITA l'analyse et produit une note 0-100 + une justification en francais.
   **Sans reference fournie, le score final repose a 100% sur les regles** — aucun avis IA n'est fabrique a
   partir de rien. Si des references existent, la note finale est `0.65 x regles + 0.35 x analyse IA`
   (`RULES_WEIGHT_WITH_REFERENCES` / `LLM_WEIGHT_WITH_REFERENCES`).

**Seuil de matching** (`TRUST_SCORE_THRESHOLD = 50.0`) : en plus d'etre verifie, le score doit atteindre ce
seuil pour que l'apprenant soit propose par le matching.

### Score de matching (`app/services/matching_score.py`)

Pour un besoin donne (`metier_code`), chaque candidat eligible recoit un score pondere et **entierement
detaille par critere** (jamais une boite noire) via `MATCH_WEIGHTS` :

- Couverture de certification pour le metier demande — **55%**
- Score de confiance — **30%**
- Experience (modules termines, plafonnee a 10) — **15%**

`GET /matching/prestataires?metier_code=nounou` retourne, pour chaque candidat, `match_score` et
`match_breakdown` (valeur + poids + detail de chaque critere), trie par score decroissant.

## License

- Code of this API: [MIT](./LICENSE)
- Skills taxonomy and training curriculum (managed via the `trankyl-academy-content` admin panel, served
  by this API): CC-BY-4.0 — see [LICENSE-CONTENT](https://github.com/trankyl-dev/trankyl-academy-content/blob/main/LICENSE-CONTENT)
  in `trankyl-academy-content`.

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
