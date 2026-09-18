from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Module(Base):
    """Un module de formation court (2-3h) avec une evaluation a la fin.
    Table `academy_modules` (base partagee Trankyl)."""

    __tablename__ = "academy_modules"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    competence_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_competences.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    contenu: Mapped[str | None] = mapped_column(Text, nullable=True)
    titre_en: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contenu_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    duree_heures: Mapped[float] = mapped_column(default=2)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    competence: Mapped["Competence"] = relationship(back_populates="modules")  # type: ignore[name-defined]
    quiz: Mapped["Quiz | None"] = relationship(back_populates="module", cascade="all, delete-orphan", uselist=False)
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="module")  # type: ignore[name-defined]

    @property
    def has_quiz(self) -> bool:
        return self.quiz is not None


class Quiz(Base):
    """Evaluation de fin de module. Table `academy_quizzes`."""

    __tablename__ = "academy_quizzes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    module_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_modules.id", ondelete="CASCADE"), unique=True, nullable=False)
    titre: Mapped[str] = mapped_column(String(255), nullable=False)
    seuil_reussite_pct: Mapped[int] = mapped_column(Integer, default=70)

    module: Mapped["Module"] = relationship(back_populates="quiz")
    questions: Mapped[list["QuizQuestion"]] = relationship(back_populates="quiz", cascade="all, delete-orphan", order_by="QuizQuestion.ordre")
    attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="quiz")  # type: ignore[name-defined]


class QuizQuestion(Base):
    __tablename__ = "academy_quiz_questions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    quiz_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_quizzes.id", ondelete="CASCADE"), nullable=False)
    texte: Mapped[str] = mapped_column(Text, nullable=False)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    quiz: Mapped["Quiz"] = relationship(back_populates="questions")
    choix: Mapped[list["QuizChoice"]] = relationship(back_populates="question", cascade="all, delete-orphan", order_by="QuizChoice.ordre")


class QuizChoice(Base):
    __tablename__ = "academy_quiz_choices"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    question_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("academy_quiz_questions.id", ondelete="CASCADE"), nullable=False)
    texte: Mapped[str] = mapped_column(String(500), nullable=False)
    est_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    ordre: Mapped[int] = mapped_column(Integer, default=0)

    question: Mapped["QuizQuestion"] = relationship(back_populates="choix")
