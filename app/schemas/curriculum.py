from pydantic import BaseModel


class ModuleCreate(BaseModel):
    competence_id: int
    code: str
    titre: str
    contenu: str | None = None
    duree_heures: float = 2
    ordre: int = 0


class ModuleOut(BaseModel):
    id: int
    competence_id: int
    code: str
    titre: str
    contenu: str | None
    duree_heures: float
    ordre: int
    has_quiz: bool = False

    class Config:
        from_attributes = True


class QuizChoiceCreate(BaseModel):
    texte: str
    est_correct: bool = False
    ordre: int = 0


class QuizChoiceOut(BaseModel):
    id: int
    texte: str
    ordre: int
    # est_correct volontairement absent : ne doit pas fuiter vers l'apprenant
    # avant qu'il n'ait soumis sa tentative.

    class Config:
        from_attributes = True


class QuizQuestionCreate(BaseModel):
    texte: str
    ordre: int = 0
    choix: list[QuizChoiceCreate] = []


class QuizQuestionOut(BaseModel):
    id: int
    texte: str
    ordre: int
    choix: list[QuizChoiceOut] = []

    class Config:
        from_attributes = True


class QuizCreate(BaseModel):
    module_id: int
    titre: str
    seuil_reussite_pct: int = 70
    questions: list[QuizQuestionCreate] = []


class QuizOut(BaseModel):
    id: int
    module_id: int
    titre: str
    seuil_reussite_pct: int
    questions: list[QuizQuestionOut] = []

    class Config:
        from_attributes = True


class QuizAnswerSubmit(BaseModel):
    question_id: int
    choice_id: int


class QuizSubmission(BaseModel):
    answers: list[QuizAnswerSubmit]


class QuizResult(BaseModel):
    score_pct: float
    reussi: bool
    seuil_reussite_pct: int
