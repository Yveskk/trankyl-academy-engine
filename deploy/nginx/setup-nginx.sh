#!/bin/bash
set -e

# =========================================================
# Script d'activation de la conf Nginx pour trankyl-academy-engine (PROD)
# (a executer sur la meme instance que trankyl_backend_nodejs,
# Nginx doit deja etre installe par son propre setup-nginx.sh)
# Usage: ./setup-nginx.sh
# =========================================================

echo ">>> Activation de la configuration Nginx PROD (api.academy.trankyl.com)..."
sudo cp api.academy.trankyl.com.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/api.academy.trankyl.com.conf /etc/nginx/sites-enabled/

echo ">>> Test de la configuration Nginx..."
sudo nginx -t

echo ">>> Redémarrage de Nginx..."
sudo systemctl restart nginx

echo ""
echo "============================================"
echo "✅ Nginx configuré avec succès !"
echo "============================================"
echo ""
echo "Prod: http://api.academy.trankyl.com -> port 9002"
echo ""
echo "⚠️  N'oublie pas de configurer le DNS du sous-domaine pour pointer"
echo "   vers l'IP de ce serveur (la meme IP que app-api.trankyl.me) !"
echo ""
echo "📌 Pour activer SSL (HTTPS) avec Certbot :"
echo "   sudo certbot --nginx -d api.academy.trankyl.com"
