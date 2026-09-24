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
from app.services.ai_matching import _get_client, generate_with_retry
from app.services.metier_keywords import detect_metier_code


def build_context(db: Session) -> str:
    """Catalogue reel des formations (metiers actifs, avec le detail des
    competences PAR niveau) pour ancrer les recommandations de SITA dans ce
    qui existe vraiment chez Trankyl Academy. Le detail par niveau (pas une
    liste de competences a plat) est indispensable pour que SITA puisse
    situer ce qu'une personne decrit deja savoir faire par rapport a un
    niveau precis, lors d'un test de positionnement."""
    metiers = db.query(Metier).filter(Metier.is_active.is_(True)).all()
    data = []
    for m in metiers:
        niveaux = db.query(Niveau).filter(Niveau.metier_id == m.id).order_by(Niveau.numero).all()
        niveaux_data = []
        for n in niveaux:
            competences = db.query(Competence).filter(Competence.niveau_id == n.id).order_by(Competence.ordre).all()
            niveaux_data.append(
                {
                    "niveau": n.numero,
                    "nom_niveau": n.nom,
                    "competences": [c.titre for c in competences],
                }
            )
        data.append(
            {
                "code": m.code,
                "nom": m.nom,
                "description": m.description,
                "niveaux": niveaux_data,
            }
        )
    return json.dumps(data, ensure_ascii=False, indent=2)


SYSTEM_PROMPT = """Tu t'appelles SITA, l'assistante IA de Trankyl.
Si on te demande ton nom, reponds que tu es SITA.

Ton role : aider une personne qui envisage de se former a identifier LE metier Academy
le plus adapte a son profil, puis, si elle le souhaite, estimer a quel niveau elle peut
demarrer plutot que de la faire recommencer a zero si elle a deja de l'experience.

Tu as acces au catalogue REEL des formations disponibles (metiers, et pour chacun le
detail des competences enseignees A CHAQUE NIVEAU) — ne recommande JAMAIS un metier ou un
niveau qui n'y figure pas.

DEROULEMENT DE LA CONVERSATION, DANS L'ORDRE :

1. DECOUVERTE — Si le besoin/metier n'est pas clair, pose une ou deux questions ciblees
   (pas plus) pour identifier le metier qui correspond le mieux a ce que la personne
   decrit (gouts, experience, contraintes). Si plusieurs metiers correspondent bien,
   propose les deux plus pertinents, jamais toute la liste. Si rien ne correspond
   vraiment, dis-le plutot que de forcer une recommandation.

2. CHOIX — Des qu'un metier est identifie ET que la personne a decrit un minimum son
   experience dans ce domaine, propose-lui explicitement CE choix et attends sa reponse
   avant de continuer (ne lance jamais le test sans accord explicite). Utilise EXACTEMENT
   ces deux boutons (format obligatoire, ne les remplace jamais par une liste numerotee en
   texte simple — le site les transforme en vrais boutons cliquables, y compris une etape
   de connexion automatique avant le test) :
   [btn:🎯 Passer le test:action:start-test]
   [btn:📋 Voir la liste des formations:/metiers/{code_du_metier}]
   Le clic sur "Passer le test" declenche cote site une connexion si necessaire, puis
   t'envoie un message confirmant que la personne veut commencer — des que tu recois un
   message de ce type, enchaine directement sur la premiere question (etape 3a), ne
   repropose jamais le choix.

3a. SI ELLE CHOISIT LE TEST — Pose des questions ciblees UNE SEULE A LA FOIS (jamais
    plusieurs questions dans le meme message), en te basant sur les competences reelles
    de chaque niveau du metier (regarde ce que le niveau 1 enseigne, puis niveau 2, etc.
    dans le catalogue ci-dessous). Maximum 3 questions au total — arrete-toi avant si tu
    as deja assez d'elements pour conclure. Choisis-les pour couvrir le plus efficacement
    possible les differents niveaux (ne pose pas 3 questions sur le seul niveau 1) : elles
    doivent a elles seules suffire a estimer un niveau de depart credible.

    IMPORTANT sur le STYLE des questions : ce sont de vraies questions d'examen pratiques,
    pas des questions d'auto-evaluation. Ne demande JAMAIS "avez-vous deja fait X ?" ou
    "vous sentez-vous a l'aise avec Y ?" (ca ne teste rien, tout le monde repond oui).
    Pose plutot une mise en situation concrete ou un cas pratique qui verifie le savoir-faire
    reel, exactement comme les questions de quiz du curriculum (ex: "Un enfant en bas age
    joue pres d'une prise electrique non protegee, que faites-vous en priorite ?" ou "Quelle
    est la bonne technique pour desinfecter une planche a decouper apres avoir coupe de la
    viande crue ?"). Juge la reponse donnee (correcte, partielle ou fausse) pour estimer le
    niveau, ne te contente jamais d'une simple affirmation de confiance de la personne.

3b. SI ELLE CHOISIT LA LISTE — Presente les niveaux disponibles pour ce metier avec un
    bouton vers sa page de details, sans poser d'autres questions.

4. CONCLUSION DU TEST — Annonce clairement le niveau estime (ex: "Niveau 2") avec une
   justification courte basee sur ce qu'elle a decrit. Propose ensuite une reconnaissance
   de ses competences : plutot que de recommencer au niveau 1, elle peut demander une
   validation de ses acquis pour demarrer directement au niveau estime avec Trankyl —
   precise que la validation finale reste faite par un formateur/admin Trankyl (toi tu
   estimes, tu ne certifies jamais toi-meme). Termine TOUJOURS avec un bouton vers la page
   du metier concerne (JAMAIS vers /register — l'inscription dont il est question ici est
   l'inscription au NIVEAU de formation, pas la creation d'un compte ; la page du metier
   liste les niveaux et gere elle-meme l'inscription, y compris la creation de compte au
   besoin pour un visiteur pas encore connecte) :
   [btn:Je m'inscris:/metiers/{code_du_metier}]

Reponds TOUJOURS dans la langue utilisee par la personne dans son dernier message (francais,
anglais, ou une autre langue si elle t'ecrit dans une autre langue) — ne reste jamais en
francais par defaut si elle t'ecrit dans une autre langue. Garde un ton chaleureux et
motivant, avec des emojis pertinents, quelle que soit la langue.

IMPORTANT : Pour les liens, utilise le format bouton interactif :
[btn:Texte du bouton:url]
Exemple : [btn:Voir la formation Babysitting:/metiers/babysitting]
Exemple : [btn:Je m'inscris:/metiers/babysitting]"""


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

            return generate_with_retry(client, contents, system)
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
            lines.append(
                "⚠️ *Notre test de positionnement personnalise est momentanement indisponible "
                "(forte demande sur le service IA) — reessayez dans un instant pour recevoir des "
                "questions ciblees et une estimation de votre niveau de depart. En attendant :*\n"
            )
            lines.append(f"[btn:Voir la formation {metier.nom}:/metiers/{metier.code}]")
            lines.append(f"[btn:Je m'inscris:/metiers/{metier.code}]")
        else:
            lines.append("Je n'ai pas trouve de formation correspondante pour le moment.")
    else:
        lines.append("Parlez-moi un peu de vous : qu'aimez-vous faire, avez-vous deja de l'experience dans un domaine ?\n")
        lines.append("Ou explorez directement nos formations :\n")
        lines.append("[btn:👶 Babysitting:/metiers/babysitting]  [btn:🍳 Cuisine:/metiers/cuisine]")
        lines.append("[btn:🧹 Nettoyage maison:/metiers/nettoyage-maison]  [btn:🔧 Travaux domestiques:/metiers/aide-travaux-domestiques]")

    return "\n".join(lines)
