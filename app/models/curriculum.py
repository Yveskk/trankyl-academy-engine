from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Module(Base):
    """Traduction pedagogique d'une competence : un module de formation
    court (2-3h) avec une evaluation a la fin."""

    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    competence_id: Mapped[int] = mapped_column(ForeignKey("competences.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    contenu: Mapped[str | None] = mapped_column(Text, nullable=True)
    titre_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contenu_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    duree_heures: Mapped[float] = mapped_column(default=2)
    ordre: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    competence: Mapped["Competence"] = relationship(back_populates="modules")
    quiz: Mapped["Quiz | None"] = relationship(back_populates="module", cascade="all, delete-orphan", uselist=False)
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="module")

    @property
    def has_quiz(self) -> bool:
        return self.quiz is not None


class Quiz(Base):
    """Evaluation de fin de module. Reussir le quiz valide le module."""

    __tablename__ = "quizzes"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), unique=True, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    seuil_reussite_pct: Mapped[int] = mapped_column(Integer, default=70)

    module: Mapped["Module"] = relationship(back_populates="quiz")
    questions: Mapped[list["QuizQuestion"]] = relationship(back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.ordre")
    attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="quiz")


class QuizQuestion(Base):
    __tablename__ = "quiz_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    quiz_id: Mapped[int] = mapped_column(ForeignKey("quizzes.id", ondelete="CASCADE"), nullable=False)
    texte: Mapped[str] = mapped_column(Text, nullable=False)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")
    choix: Mapped[list["QuizChoice"]] = relationship(back_populates="question", cascade="all, delete-orphan", order_by="QuizChoice.ordre")


class QuizChoice(Base):
    __tablename__ = "quiz_choices"

    id: Mapped[int] = mapped_column(primary_key=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("quiz_questions.id", ondelete="CASCADE"), nullable=False)
    texte: Mapped[str] = mapped_column(String(500), nullable=False)
    est_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped["QuizQuestion"] = relationship(back_populates="choix")
