"""Service de matching intelligent via Gemini (Google).
Enrichit les donnees de la base avec le raisonnement de l'IA pour recommander
des prestataires pertinents.
"""
import json
import os
import sys

# Le paquet `brotli` installe sur ce serveur (Brotli 1.1.0, via apt) expose une
# API (`.process()`) incompatible avec ce qu'attendent certains decodeurs
# brotli bases sur httpx2, ce qui peut faire planter une requete avec un
# `TypeError` masque en erreur de connexion generique. En marquant `brotli`
# comme non disponible ici, ces clients HTTP utilisent gzip/plain a la place :
# aucune perte fonctionnelle pour du JSON de chat, et les vraies erreurs
# remontent correctement. Precaution gardee au cas ou malgre le passage a
# Gemini (meme risque si son client HTTP interne partage ce decodeur).
sys.modules["brotli"] = None

from sqlalchemy.orm import Session

from app.models.certification import Certification
from app.models.curriculum import Module
from app.models.matching import Message
from app.models.progress import Enrollment
from app.models.taxonomy import Competence, Metier, Niveau
from app.models.user import Apprenant
from app.services.metier_keywords import detect_metier_code

# Client Gemini — clé depuis GEMINI_API_KEY ou None
_client = None


def _get_client():
    global _client
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    if _client is not None:
        return _client
    try:
        from google import genai
        _client = genai.Client(api_key=api_key)
        return _client
    except Exception as e:
        print(f"[ai_matching] Erreur init Gemini: {e}")
        _client = None
        return None


def build_context(db: Session) -> str:
    """Construit le contexte de la base de donnees pour SITA."""
    # --- Metiers & Taxonomie ---
    metiers = db.query(Metier).all()
    taxonomie = []
    for m in metiers:
        niveaux = db.query(Niveau).filter(Niveau.metier_id == m.id).order_by(Niveau.numero).all()
        niveaux_data = []
        for n in niveaux:
            comps = db.query(Competence).filter(Competence.niveau_id == n.id).order_by(Competence.ordre).all()
            niveaux_data.append({
                "niveau": n.numero,
                "nom": n.nom,
                "description": n.description,
                "competences": [{"code": c.code, "titre": c.titre, "description": c.description} for c in comps],
            })
        taxonomie.append({
            "code": m.code,
            "nom": m.nom,
            "description": m.description,
            "niveaux": niveaux_data,
        })

    # --- Modules ---
    modules = db.query(Module).all()
    modules_data = []
    for mod in modules:
        competence = db.get(Competence, mod.competence_id)
        modules_data.append({
            "titre": mod.titre,
            "code": mod.code,
            "duree_heures": mod.duree_heures,
            "competence": competence.titre if competence else "N/A",
            "has_quiz": mod.quiz is not None,
        })

    # --- Prestataires certifies ---
    # Blocage automatique : SITA ne doit JAMAIS suggerer un apprenant qui
    # n'est pas verifie par un admin ET au-dessus du seuil de confiance
    # (voir app.services.trust_score.is_matching_eligible). C'est verifie ici
    # pour chaque candidat, pas seulement cote frontend.
    from app.models.trust import TrustScore
    from app.services.trust_score import is_matching_eligible

    certifications = db.query(Certification).all()
    prestataires_map: dict[int, dict] = {}
    for cert in certifications:
        if cert.apprenant_id not in prestataires_map:
            apprenant = db.get(Apprenant, cert.apprenant_id)
            if not apprenant:
                continue
            trust = db.query(TrustScore).filter(TrustScore.apprenant_id == apprenant.id).first()
            if not is_matching_eligible(apprenant, trust):
                continue
            prestataires_map[cert.apprenant_id] = {
                "id": apprenant.id,
                "nom": f"{apprenant.firstname} {apprenant.lastname}",
                "certifications": [],
                "modules_completes": 0,
                "score_confiance": trust.score_pct,
            }
        if cert.apprenant_id in prestataires_map:
            prestataires_map[cert.apprenant_id]["certifications"].append(cert.code)

    # Ajouter le nombre de modules completes
    for pid in prestataires_map:
        count = db.query(Enrollment).filter(
            Enrollment.apprenant_id == pid, Enrollment.statut == "termine"
        ).count()
        prestataires_map[pid]["modules_completes"] = count

    context = {
        "taxonomie": taxonomie,
        "modules_disponibles": modules_data,
        "prestataires_certifies": list(prestataires_map.values()),
        "stats": {
            "nombre_metiers": len(metiers),
            "nombre_modules": len(modules),
            "nombre_prestataires_certifies": len(prestataires_map),
        },
    }
    return json.dumps(context, ensure_ascii=False, indent=2)


SYSTEM_PROMPT = """Tu t'appelles SITA, l'assistant intelligent de Trankyl Academy, une plateforme de
micro-certification pour les metiers du quotidien (babysitting, aide aux travaux domestiques, cuisine,
nettoyage maison/bureau/vehicules/piscine/meubles/jardin, courses/shopping).
Si on te demande ton nom, reponds que tu es SITA.

Ton role est d'aider les clients a trouver le bon prestataire en fonction de leurs besoins.
Tu as acces a la base de donnees complete de Trankyl Academy qui contient :

1. La TAXONOMIE : les metiers, niveaux de competences et competences
2. Les MODULES DE FORMATION disponibles (2-3h chacun)
3. Les PRESTATAIRES certifies avec leurs certifications obtenues

Pour chaque demande client :
- Analyse le besoin precise (type de metier, nombre d'enfants/personnes, frequence, etc.)
- Identifie les certifications pertinentes dans la taxonomie
- Propose les prestataires dont les certifications correspondent
- Explique POURQUOI chaque prestataire est pertinent (quel metier/quelles competences il a)
- Ne mentionne JAMAIS de numero de niveau precis a un client (ex: "niveau 2") — ce detail
  n'interesse pas quelqu'un qui cherche un prestataire. Mentionne plutot le metier/domaine
  et, si utile, le nombre total de certifications obtenues (ex: "3 certifications")
- Si aucun prestataire ne correspond parfaitement, suggere les plus proches
- Si le client semble etre lui-meme un futur prestataire, oriente-le vers les modules de formation

Reponds toujours en francais, de maniere chaleureuse et professionnelle.
Formate ta reponse de maniere lisible avec des emojis pertinents.

IMPORTANT : Pour les liens, utilise le format bouton interactif :
[btn:Texte du bouton:url]
Exemple : [btn:Voir le profil:/prestataires/2]
Exemple : [btn:Explorer la formation:/metiers/babysitting]

Si tu identifies un besoin de formation, cree un bouton vers /metiers/[code].
Si un prestataire correspond, cree un bouton vers /prestataires/[id] pour le contacter.
Propose toujours des boutons cliquables pour guider l'utilisateur."""


def chat_with_ai(user_message: str, db: Session, conversation_history: list[dict] | None = None) -> str:
    """Envoie un message a Gemini avec le contexte de la base de donnees."""
    client = _get_client()
    context = build_context(db)

    system = f"""{SYSTEM_PROMPT}

=== CONTEXTE DE LA BASE DE DONNEES ===
{context}
=== FIN DU CONTEXTE ==="""

    if client:
        # Appel reel a Gemini
        try:
            from google.genai import types

            contents = []
            for m in conversation_history or []:
                role = "model" if m["role"] == "assistant" else "user"
                contents.append(types.Content(role=role, parts=[types.Part(text=m["content"])]))
            contents.append(types.Content(role="user", parts=[types.Part(text=user_message)]))

            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    max_output_tokens=2048,
                ),
            )
            return response.text
        except Exception as e:
            print(f"[ai_matching] Erreur Gemini API: {e}")
            return _local_matching_response(user_message, db)
    else:
        # Mode degradé sans clé API — reponse analytique locale
        return _local_matching_response(user_message, db)


def _local_matching_response(user_message: str, db: Session) -> str:
    """Reponse de fallback sans cle API Gemini — matching par mots-cles."""
    detected_metier = detect_metier_code(user_message)

    # Reponse
    lines = ["🤖 **SITA — Assistant Trankyl Academy**\n"]

    if detected_metier:
        metier = db.query(Metier).filter(Metier.code == detected_metier).first()
        if metier:
            lines.append(f"J'ai detecte que vous cherchez un **{metier.nom}** !\n")
            lines.append(f"📝 *{metier.description}*\n")

            # Prestataires certifies pour ce metier
            niveaux = db.query(Niveau).filter(Niveau.metier_id == metier.id).all()
            niveau_ids = [n.id for n in niveaux]
            certs = db.query(Certification).filter(Certification.niveau_id.in_(niveau_ids)).all()

            prestataires_found: dict[int, dict] = {}
            for c in certs:
                if c.apprenant_id not in prestataires_found:
                    apprenant = db.get(Apprenant, c.apprenant_id)
                    if apprenant:
                        prestataires_found[c.apprenant_id] = {
                            "nom": f"{apprenant.firstname} {apprenant.lastname}",
                            "id": apprenant.id,
                            "certs": [],
                        }
                prestataires_found[c.apprenant_id]["certs"].append(c.code)

            if prestataires_found:
                lines.append(f"✅ **{len(prestataires_found)} prestataire(s) certifie(s)** disponible(s) :\n")
                for p in prestataires_found.values():
                    count = len(p["certs"])
                    lines.append(f"- 👤 **{p['nom']}** — {count} certification{'s' if count > 1 else ''} obtenue{'s' if count > 1 else ''}")
                    lines.append(f"  [btn:Voir le profil:/prestataires/{p['id']}]")
            else:
                lines.append("❌ Aucun prestataire certifie n'est disponible pour le moment.")
                lines.append(f"  [btn:Explorer la formation:/metiers/{metier.code}]")
    else:
        lines.append("Je peux vous aider a trouver le bon prestataire !\n")
        lines.append("Dites-moi simplement ou cliquez sur un bouton :\n")
        lines.append("  [btn:👶 Babysitting:/metiers/babysitting]  [btn:🍳 Cuisine:/metiers/cuisine]")
        lines.append("  [btn:🧹 Nettoyage maison:/metiers/nettoyage-maison]  [btn:🔧 Travaux domestiques:/metiers/aide-travaux-domestiques]")
        lines.append("\nOu decrivez votre besoin en details !")

    return "\n".join(lines)
