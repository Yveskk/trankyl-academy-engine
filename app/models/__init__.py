# Regroupe tous les modeles pour qu'un simple `import app.models` suffise a
# peupler Base.metadata (utilise par Alembic pour l'autogenerate).
from app.models.banner import Banner
from app.models.blog import BlogArticle
from app.models.certification import Certification
from app.models.chat_history import ChatMessageRecord, ChatSession
from app.models.client import Client
from app.models.contact_request import ContactMessage, ContactRequest
from app.models.content import ContentSection
from app.models.curriculum import Module, Quiz, QuizChoice, QuizQuestion
from app.models.matching import Match, MatchingRequest, Message
from app.models.progress import Enrollment, NiveauEnrollment, QuizAttempt
from app.models.otp import OtpCode
from app.models.review import Review
from app.models.taxonomy import Competence, Metier, Niveau
from app.models.trust import TrustScore
from app.models.user import AdminUser, Apprenant

__all__ = [
    "AdminUser",
    "Apprenant",
    "Metier",
    "Niveau",
    "Competence",
    "Module",
    "Quiz",
    "QuizQuestion",
    "QuizChoice",
    "Enrollment",
    "NiveauEnrollment",
    "QuizAttempt",
    "Certification",
    "ContentSection",
    "MatchingRequest",
    "Match",
    "Message",
    "ChatSession",
    "ChatMessageRecord",
    "TrustScore",
    "BlogArticle",
    "Banner",
    "Client",
    "OtpCode",
    "Review",
    "ContactRequest",
    "ContactMessage",
]
