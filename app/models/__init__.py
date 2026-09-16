# Regroupe tous les modeles pour qu'un simple `import app.models` suffise a
# peupler Base.metadata (utilise par Alembic pour l'autogenerate).
from app.models.certification import Certification
from app.models.curriculum import Module, Quiz, QuizChoice, QuizQuestion
from app.models.progress import Enrollment, QuizAttempt
from app.models.taxonomy import Competence, Metier, Niveau
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
    "QuizAttempt",
    "Certification",
]
