#!/bin/bash

# Script de gestion du serveur de déploiement (Prod / GCP)
# Usage: ./deploy-server.sh [redeploy|up|down|pull|logs|status]
#
# Tourne sur la même instance (et le même réseau Docker e_global) que
# trankyl_backend_nodejs. Ce script ne touche pas au conteneur du backend.

set -e

CMD=${1:-"help"}

cd "$(dirname "$0")"

COMPOSE_FILE="trankyl-academy-engine-prod.yml"
PROJECT_NAME="trankyl-academy-engine-prod"
SERVICE_NAME="trankyl_academy_engine_prod"
IMAGE_NAME="trankyldev/trankyl_academy_engine_prod:latest"

show_help() {
    echo "Usage: ./deploy-server.sh [COMMAND]"
    echo ""
    echo "Commands:"
    echo "  redeploy : Arrête, supprime l'ancienne image, pull la plus récente et relance"
    echo "  up       : Démarrer le conteneur"
    echo "  down     : Arrêter le conteneur"
    echo "  pull     : Télécharger la dernière image Docker Hub"
    echo "  logs     : Afficher les logs en direct"
    echo "  status   : Afficher l'état du service"
    echo "  help     : Afficher ce menu d'aide"
}

ensure_network() {
    docker network inspect e_global >/dev/null 2>&1 || docker network create e_global
}

redeploy_service() {
    echo "🚀 Redéploiement du service $SERVICE_NAME..."
    ensure_network
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" stop "$SERVICE_NAME" || true
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" rm -f "$SERVICE_NAME" || true
    echo "🧹 Suppression de l'ancienne image $IMAGE_NAME..."
    docker rmi -f "$IMAGE_NAME" 2>/dev/null || true
    echo "📥 Récupération de la nouvelle image $IMAGE_NAME..."
    docker pull "$IMAGE_NAME"
    echo "🏗️  Démarrage du service $SERVICE_NAME..."
    docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d "$SERVICE_NAME"
}

case $CMD in
    "redeploy")
        redeploy_service
        ;;
    "up")
        ensure_network
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up -d
        ;;
    "down")
        echo "🛑 Arrêt du service..."
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down
        ;;
    "pull")
        docker pull "$IMAGE_NAME"
        ;;
    "logs")
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" logs -f "$SERVICE_NAME"
        ;;
    "status")
        docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" ps
        ;;
    "help")
        show_help
        ;;
    *)
        echo "❌ Commande inconnue: $CMD"
        show_help
        exit 1
        ;;
esac

echo "🧹 Nettoyage des images Docker inutilisées..."
docker image prune -f
echo "✅ Opération terminée ! ($CMD)"
