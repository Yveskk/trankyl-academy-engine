#!/bin/bash
set -e

cd "$(dirname "$0")/.."

VERSION=${1:-"latest"}
PUSH=false
[[ "$2" == "--push" ]] && PUSH=true

IMAGE="trankyldev/trankyl_academy_engine_prod"

echo "Building $IMAGE:$VERSION..."
docker build -t "$IMAGE:$VERSION" -t "$IMAGE:latest" -f Dockerfile .

if $PUSH; then
  echo "Pushing $IMAGE:$VERSION..."
  docker push "$IMAGE:$VERSION"
  echo "Pushing $IMAGE:latest..."
  docker push "$IMAGE:latest"

  echo ""
  echo "Pour déployer sur le serveur :"
  echo "  cd deploy && ./deploy-server.sh redeploy"
fi

echo "Done."
