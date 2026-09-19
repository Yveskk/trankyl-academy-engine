# Documentation de Déploiement — trankyl-academy-engine (GCP, PROD)

Ce service est déployé sur la **même instance** que `trankyl_backend_nodejs` (GCP), sur le **même réseau
Docker** `e_global`, avec un port dédié pour ne pas rentrer en conflit :

- **Production** : `api.academy.trankyl.com` → port hôte **9002** (conteneur 8000).

Contrairement à `trankyl_backend_nodejs`, ce service n'a pas de base MySQL/Redis locale dans le
`docker-compose` : il se connecte à une base MySQL distante (`DATABASE_URL` dans `.env.prod`), comme en
développement local.

---

## 📁 Structure du dossier `deploy`

- `trankyl-academy-engine-prod.yml` : Docker Compose de production.
- `deploy-server.sh` : Script de gestion sur le serveur (`redeploy`, `up`, `down`, `logs`, `status`).
- `deploy-service.sh` : Script local de Build & Push de l'image Docker Hub.
- `.env.prod.example` : Modèle de variables d'environnement.
- `nginx/` : Configuration Nginx (`setup-nginx.sh`).

---

## 🚀 Mise en service (sur l'instance qui héberge déjà `trankyl_backend_nodejs`)

### 1. Build & push de l'image (en local)

```bash
./deploy/deploy-service.sh 0.2.1 --push
```

### 2. DNS

Ajoutez une entrée **A** pour `api.academy.trankyl.com` pointant vers **la même IP** que
`app-api.trankyl.me` (c'est la même VM).

### 3. Copie des fichiers sur le serveur

Dans `~/trankyl/` sur le serveur (le même dossier que celui utilisé pour `trankyl_backend_nodejs`) :

```bash
scp trankyl-academy-engine-prod.yml deploy-server.sh .env.prod user@<IP>:~/trankyl/academy-engine/
scp -r nginx user@<IP>:~/trankyl/academy-engine/
```

> Utilisez un sous-dossier dédié (ex. `~/trankyl/academy-engine/`) pour ne pas écraser les fichiers du
> backend Node qui portent des noms différents mais vivent dans le même `~/trankyl/`.

Remplissez `.env.prod` à partir de `.env.prod.example` : `DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS` (doit
pointer vers l'URL du site `trankyl-academy-content`), et les identifiants Cloudinary/Gemini si utilisés.

### 4. Lancer le conteneur

```bash
cd ~/trankyl/academy-engine
chmod +x deploy-server.sh
./deploy-server.sh redeploy
```

Le script rejoint automatiquement le réseau `e_global` déjà créé par le backend Node (`ensure_network`), et
exécute les migrations Alembic (`alembic upgrade head`) au démarrage du conteneur avant de lancer `uvicorn`
(voir `docker-entrypoint.sh` à la racine du projet).

Vérifier :
```bash
docker ps                    # trankyl_academy_engine_prod actif sur le port 9002
curl http://localhost:9002/health
```

### 5. Nginx & SSL

```bash
cd ~/trankyl/academy-engine/nginx
chmod +x setup-nginx.sh
sudo ./setup-nginx.sh
sudo certbot --nginx -d api.academy.trankyl.com
```

---

## 🛠️ Commandes de gestion courantes

```bash
./deploy-server.sh redeploy
./deploy-server.sh logs
./deploy-server.sh status
./deploy-server.sh down
```

---

## ⚠️ Points d'attention

- **CORS_ORIGINS** doit être mis à jour avec le vrai domaine du site `trankyl-academy-content` une fois
  celui-ci déployé (par défaut dans `.env.prod.example` : `https://academy.trankyl.com`).
- Les migrations Alembic tournent automatiquement à chaque démarrage du conteneur (`docker-entrypoint.sh`) —
  c'est voulu pour ne pas avoir d'étape manuelle, mais soyez prudent avec des migrations non réversibles.
- L'identifiant Docker Hub (`trankyldev/trankyl_academy_engine_prod`) doit être créé au préalable sur
  Docker Hub, comme pour `trankyl_server_prod`.
