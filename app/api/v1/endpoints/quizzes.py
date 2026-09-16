from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload

from app.api.deps import get_current_apprenant
from app.db.session import get_db
from app.models.curriculum import Quiz, QuizChoice, QuizQuestion
from app.models.progress import Enrollment, QuizAttempt
from app.models.user import Apprenant
from app.schemas.curriculum import QuizResult, QuizSubmission
from app.services.certification import maybe_issue_certification

router = APIRouter()


@router.post("/{quiz_id}/attempts", response_model=QuizResult, status_code=201)
def submit_quiz(
    quiz_id: int,
    payload: QuizSubmission,
    current: Apprenant = Depends(get_current_apprenant),
    db: Session = Depends(get_db),
):
    quiz = (
        db.query(Quiz)
        .options(joinedload(Quiz.questions).joinedload(QuizQuestion.choix))
        .filter(Quiz.id == quiz_id)
        .first()
    )
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz introuvable")

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.apprenant_id == current.id, Enrollment.module_id == quiz.module_id)
        .first()
    )
    if not enrollment:
        raise HTTPException(status_code=400, detail="Vous devez vous inscrire au module avant de passer le quiz")

    correct_choice_by_question: dict[int, int | None] = {}
    for question in quiz.questions:
        correct = next((c.id for c in question.choix if c.est_correct), None)
        correct_choice_by_question[question.id] = correct

    submitted_by_question = {a.question_id: a.choice_id for a in payload.answers}

    total = len(quiz.questions)
    if total == 0:
        raise HTTPException(status_code=400, detail="Ce quiz n'a pas de questions")

    correct_count = sum(
        1
        for question in quiz.questions
        if submitted_by_question.get(question.id) == correct_choice_by_question.get(question.id)
    )
    score_pct = round((correct_count / total) * 100, 2)
    reussi = score_pct >= quiz.seuil_reussite_pct

    attempt = QuizAttempt(apprenant_id=current.id, quiz_id=quiz_id, score_pct=score_pct, reussi=reussi)
    db.add(attempt)

    if reussi and enrollment.statut != "termine":
        enrollment.statut = "termine"
        enrollment.completed_at = datetime.now(timezone.utc)
        db.add(enrollment)

    db.commit()

    if reussi:
        niveau_id = quiz.module.competence.niveau_id
        maybe_issue_certification(db, apprenant_id=current.id, niveau_id=niveau_id)

    return QuizResult(score_pct=score_pct, reussi=reussi, seuil_reussite_pct=quiz.seuil_reussite_pct)
