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

## Migrations (additives, sans perte de donnees)

La base est PARTAGEE avec le site et l'app Trankyl et contient des donnees de
production. Regle : une migration ne supprime, ne renomme et ne retype jamais
rien ; elle ne fait que creer ce qui manque, avec des gardes (`IF NOT EXISTS`
logique via `app/db/migration_utils.py`), donc elle est rejouable.

| Revision | Contenu |
|---|---|
| `0001_baseline` | Tables `academy_*` + colonnes Academy de `vendors`. **En production elles existent deja : ne pas l'executer, faire `alembic stamp 0001_baseline`.** |
| `0002_home_configuration` | Configuration de l'accueil : `academy_home_items`, colonnes sur `academy_content_sections` et `academy_banners` |
| `0003_provider_extras` | `academy_provider_profiles/media/availability`, moderation des avis (`academy_reviews`) |
| `0006_security_verification` | Verification par code (WhatsApp / SMS / email) : `academy_verifications` (codes HACHES), `academy_account_security`, `academy_trusted_devices`, `academy_security_events` |
| `0005_academy_countries` | Table `academy_countries` (vide a la creation) : pays geres dans Admin > Configuration > Pays |
| `0004_provider_profile_details` | Colonnes de profil public (frais de deplacement, experience, zone, note des prix) |
| `0007_admin_access` | Utilisateurs / roles / 2FA admin : colonnes `totp_*` sur `users`, `user_types.ust_roles` en TEXT, `academy_admin_profiles` |
| `0008_country_scope` | Multi-pays : `country_code` ('TG' pour l'existant) sur contenus d'accueil, bannieres, metiers, blocs de contenu (cle primaire `(key, country_code)`) ; `academy_admin_countries`, `academy_entity_countries` |
| `0009_role_countries` | Pays dans lesquels un role est proposable (`academy_role_countries`) |
| `0010_metier_code_per_country` | Le code d'un metier devient unique PAR PAYS |

**Multi-pays** : chaque requete porte `X-Country` / `X-Lang` (ou `?country=` / `?lang=`). Les ecrans admin travaillent
dans un pays auquel l'administrateur a acces (sinon 403). Tout l'existant est rattache au Togo, rien n'est supprime.
Tests de bout en bout (base `*_dev_db` uniquement) : `scripts/dev_access_test.py`, `dev_country_test.py`, `dev_country2_test.py`.

Deploiement sur une base existante (prod), dans cet ordre :

```bash
python -m scripts.data_guard snapshot avant.json   # empreinte de TOUTES les lignes
alembic stamp 0001_baseline                        # la base contient deja le baseline
alembic upgrade head                               # applique 0002 puis 0003
python -m scripts.data_guard verify avant.json     # doit afficher OK (code 0)
```

Tester d'abord sur la base dev (`*_dev_db`) :

```bash
python -m scripts.dev_bootstrap      # colonnes du coeur Trankyl presentes en prod, absentes en dev
alembic upgrade 0001_baseline
python -m scripts.dev_seed           # donnees FICTIVES "v1"
python -m scripts.data_guard snapshot avant.json
alembic upgrade head
python -m scripts.data_guard verify avant.json
python -m scripts.dev_smoke_test     # test de bout en bout de l'admin accueil (nettoie ce qu'il cree)
python -m scripts.dev_seed_demo      # 24 prestataires FICTIFS : certificats, services, dispos, avis (additif)
python -m scripts.dev_search_test    # recherche + profil public (lecture seule)
python -m scripts.dev_config_test    # Configuration > Pays (nettoie ce qu'il cree)
python -m scripts.dev_security_test  # inscription / connexion / mot de passe oublie avec codes (mode log, aucun envoi)
```

Ces scripts de dev refusent de tourner sur une base dont le nom ne finit pas par `_dev_db`.
`GET /api/v1/directory/search` (recherche en langage naturel + filtres), `/directory/locations` et
`/directory/providers/{slug|id}` (profil public) : lecture publique, uniquement des prestataires
certifies, verifies et au-dessus du seuil de confiance. Synonymes de recherche modifiables sans
deploiement via la section `search_synonyms` (`academy_content_sections`, `payload_json`
`{"groups": [{"targets": [...], "triggers": [...]}]}`).
`GET /api/v1/home` : reponse agregee (cache memoire `HOME_CACHE_TTL_SECONDS`, ETag), images
relatives du catalogue resolues avec `MEDIA_BASE_URL`.

## Creer le premier compte admin

Il n'y a pas d'inscription admin en libre-service (par design) :

```bash
yarn create-admin
```

## Verification par code (inscription, connexion, mot de passe oublie)

Canaux : **WhatsApp** (Cloud API, modele Meta `otp_verification`), **SMS** (AfrikSMS), **email** (Mailjet) — memes
identifiants que `trankyl_backend_nodejs` (`WHATSAPP_TOKEN`, `WHATSAPP_PHONE_ID`, `WHATSAPP_OTP_TEMPLATE`, `AFRIKSMS_*`,
`MAILJET_*`/`SENDER_EMAIL`).

- `OTP_DELIVERY_MODE=log` (defaut) : rien n'est envoye, le code s'ecrit dans la console du serveur. Passer a `live` en production.
- `ADMIN_EMAIL=a@x.com,b@x.com` : destinataires de l'alerte « Nouvelle reservation » (le client recoit aussi sa confirmation, dans sa langue). Les envois suivent `OTP_DELIVERY_MODE` ; un echec d'envoi n'empeche jamais la reservation. Si `NODE_API_URL` est defini, c'est Node qui envoie.
- `LOGIN_VERIFICATION_POLICY` : `off` (defaut : connexion directe avec le bon mot de passe ; `new_device` = code sur tout appareil non reconnu),
  `always`, ou `off` (coupe-circuit d'urgence). L'administration exige toujours un code par email.
- Les comptes existants ne sont jamais bloques : sans ligne de securite, ils sont verifies a leur prochaine connexion.
- Les codes sont stockes haches ; essais, delais et plafonds d'envoi (par contact et par IP) limitent les abus ;
  `OTP_ALLOWED_DIAL_CODES` borne les pays pour WhatsApp/SMS. Derriere nginx, activer `TRUST_PROXY_HEADERS=true`.
