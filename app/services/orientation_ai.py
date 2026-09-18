"""Assistant IA d'orientation formation — meme persona SITA que
app.services.ai_matching, mais pour un usage different : la-bas SITA met en
relation un CLIENT avec un PRESTATAIRE certifie deja forme, ici il n'y a ni
client ni prestataire, seulement un visiteur qui envisage de se former et
notre catalogue de formations Academy. Public : aucun compte requis pour
discuter avec SITA, le but est justement d'aider a decider AVANT de
s'inscrire."""
import json

from sqlalchemy.orm import Session

from app.models.taxonomy import Competence, Metier, Niveau
from app.services.ai_matching import _get_client
from app.services.metier_keywords import detect_metier_code


def build_context(db: Session) -> str:
    """Catalogue reel des formations (metiers actifs, niveaux, competences
    enseignees) pour ancrer les recommandations de SITA dans ce qui existe
    vraiment chez Trankyl Academy."""
    metiers = db.query(Metier).filter(Metier.is_active.is_(True)).all()
    data = []
    for m in metiers:
        niveaux = db.query(Niveau).filter(Niveau.metier_id == m.id).order_by(Niveau.numero).all()
        competences: list[str] = []
        for n in niveaux:
            competences += [c.titre for c in db.query(Competence).filter(Competence.niveau_id == n.id).all()]
        data.append(
            {
                "code": m.code,
                "nom": m.nom,
                "description": m.description,
                "competences_enseignees": competences,
            }
        )
    return json.dumps(data, ensure_ascii=False, indent=2)


SYSTEM_PROMPT = """Tu t'appelles SITA, l'assistant IA de Trankyl.
Si on te demande ton nom, reponds que tu es SITA.

Ton role : aider une personne qui envisage de se former a identifier LE metier Academy
le plus adapte a son profil, a partir de ce qu'elle decrit d'elle-meme (gouts, experience,
contraintes de temps, ce qu'elle sait deja faire).

Tu as acces au catalogue REEL des formations disponibles (metiers, niveaux, competences
enseignees) — ne recommande JAMAIS un metier qui n'y figure pas.

Pour chaque message :
- Si le besoin n'est pas clair, pose une ou deux questions ciblees (pas plus) avant de conclure
- Des que tu identifies un metier pertinent, explique en 2-3 phrases pourquoi il correspond,
  puis propose un bouton vers sa page details et un bouton pour s'inscrire
- Si plusieurs metiers correspondent bien, propose les deux plus pertinents, pas toute la liste
- Reste honnete : si rien ne correspond vraiment, dis-le plutot que de forcer une recommandation

Reponds toujours en francais, ton chaleureux et motivant, avec des emojis pertinents.

IMPORTANT : Pour les liens, utilise le format bouton interactif :
[btn:Texte du bouton:url]
Exemple : [btn:Voir la formation Babysitting:/metiers/babysitting]
Exemple : [btn:Je m'inscris:/register]"""


def chat_orientation(user_message: str, db: Session, conversation_history: list[dict] | None = None) -> str:
    """Envoie un message a Gemini avec le catalogue reel des formations."""
    client = _get_client()
    context = build_context(db)

    system = f"""{SYSTEM_PROMPT}

=== FORMATIONS DISPONIBLES ===
{context}
=== FIN DES FORMATIONS ==="""

    if client:
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
            print(f"[orientation_ai] Erreur Gemini API: {e}")
            return _local_orientation_response(user_message, db)
    else:
        return _local_orientation_response(user_message, db)


def _local_orientation_response(user_message: str, db: Session) -> str:
    """Reponse de fallback sans cle API Gemini — orientation par mots-cles."""
    detected_code = detect_metier_code(user_message)

    lines = ["🎯 **SITA — Orientation formation Trankyl Academy**\n"]

    if detected_code:
        metier = db.query(Metier).filter(Metier.code == detected_code, Metier.is_active.is_(True)).first()
        if metier:
            lines.append(f"D'apres ce que vous decrivez, la formation **{metier.nom}** pourrait bien vous correspondre !\n")
            if metier.description:
                lines.append(f"📝 *{metier.description}*\n")
            lines.append(f"[btn:Voir la formation {metier.nom}:/metiers/{metier.code}]")
            lines.append("[btn:Je m'inscris:/register]")
        else:
            lines.append("Je n'ai pas trouve de formation correspondante pour le moment.")
    else:
        lines.append("Parlez-moi un peu de vous : qu'aimez-vous faire, avez-vous deja de l'experience dans un domaine ?\n")
        lines.append("Ou explorez directement nos formations :\n")
        lines.append("[btn:👶 Babysitting:/metiers/babysitting]  [btn:🍳 Cuisine:/metiers/cuisine]")
        lines.append("[btn:🧹 Nettoyage maison:/metiers/nettoyage-maison]  [btn:🔧 Travaux domestiques:/metiers/aide-travaux-domestiques]")

    return "\n".join(lines)
