from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_admin
from app.db.session import get_db
from app.models.curriculum import Module, Quiz, QuizChoice, QuizQuestion
from app.models.taxonomy import Competence
from app.schemas.curriculum import ModuleCreate, ModuleOut, QuizCreate, QuizOut

router = APIRouter()


# --- Lecture publique ---


@router.get("/modules", response_model=list[ModuleOut])
def list_modules(competence_id: int | None = None, db: Session = Depends(get_db)):
    query = db.query(Module)
    if competence_id is not None:
        query = query.filter(Module.competence_id == competence_id)
    return query.order_by(Module.ordre).all()


@router.get("/modules/{module_id}", response_model=ModuleOut)
def get_module(module_id: int, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable")
    return module


@router.get("/modules/{module_id}/quiz", response_model=QuizOut)
def get_module_quiz(module_id: int, db: Session = Depends(get_db)):
    quiz = (
        db.query(Quiz)
        .options(joinedload(Quiz.questions).joinedload(QuizQuestion.choix))
        .filter(Quiz.module_id == module_id)
        .first()
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="Ce module n'a pas de quiz")
    return quiz


# --- Ecriture reservee aux admins ---


@router.post("/modules", response_model=ModuleOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_module(payload: ModuleCreate, db: Session = Depends(get_db)):
    competence = db.get(Competence, payload.competence_id)
    if not competence:
        raise HTTPException(status_code=404, detail="Competence introuvable")
    if db.query(Module).filter(Module.code == payload.code).first():
        raise HTTPException(status_code=400, detail="Ce code module existe deja")
    module = Module(**payload.model_dump())
    db.add(module)
    db.commit()
    db.refresh(module)
    return module


@router.post("/quizzes", response_model=QuizOut, status_code=201, dependencies=[Depends(get_current_admin)])
def create_quiz(payload: QuizCreate, db: Session = Depends(get_db)):
    module = db.get(Module, payload.module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable")
    if module.quiz is not None:
        raise HTTPException(status_code=400, detail="Ce module a deja un quiz")

    quiz = Quiz(module_id=payload.module_id, titre=payload.titre, seuil_reussite_pct=payload.seuil_reussite_pct)
    for q in payload.questions:
        question = QuizQuestion(texte=q.texte, ordre=q.ordre)
        for c in q.choix:
            question.choix.append(QuizChoice(texte=c.texte, est_correct=c.est_correct, ordre=c.ordre))
        quiz.questions.append(question)

    db.add(quiz)
    db.commit()
    db.refresh(quiz)
    return quiz


@router.delete("/modules/{module_id}", status_code=204, dependencies=[Depends(get_current_admin)])
def delete_module(module_id: int, db: Session = Depends(get_db)):
    module = db.get(Module, module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module introuvable")
    db.delete(module)
    db.commit()
