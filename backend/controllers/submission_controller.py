from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime

from database import get_db
from models import CampaignSubmission, CampaignSubmissionStatus
from models import Campaign
from schemas import CampaignSubmissionCreate, CampaignSubmissionReview, CampaignSubmissionMetricsUpdate, CampaignSubmissionResponse

router = APIRouter(prefix="/api/submissions", tags=["submissions"])

# Akceptacja lub odrzucenie zgłoszenia przez markę
@router.patch("/{submission_id}/review", response_model=CampaignSubmissionResponse)
async def review_submission(
    submission_id: int, 
    review: CampaignSubmissionReview, 
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(CampaignSubmission).where(CampaignSubmission.id == submission_id))
    submission = result.scalars().first()

    if not submission:
        raise HTTPException(status_code=404, detail="Zgłoszenie nie istnieje")

    submission.status = review.status
    submission.feedback = review.feedback
    submission.reviewed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(submission)
    return submission


# Aktualizacja wyświetleń i automatyczne obliczenie wypłaty
@router.patch("/{submission_id}/metrics", response_model=CampaignSubmissionResponse)
async def update_metrics(
    submission_id: int, 
    metrics: CampaignSubmissionMetricsUpdate, 
    db: AsyncSession = Depends(get_db)
):
    # Pobieramy zgłoszenie wraz z regułami kampanii
    result = await db.execute(
        select(CampaignSubmission, Campaign)
        .join(Campaign, CampaignSubmission.campaign_id == Campaign.id)
        .where(CampaignSubmission.id == submission_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Zgłoszenie nie istnieje")

    submission, campaign = row

    if submission.status != CampaignSubmissionStatus.APPROVED:
        raise HTTPException(status_code=400, detail="Można aktualizować statystyki tylko dla zaakceptowanych wideo")

    # Aktualizacja liczników
    submission.views_count = metrics.views_count
    submission.clicks_count = metrics.clicks_count
    submission.last_metrics_update = datetime.utcnow()

    # --- KALKULACJA WYPŁATY ---
    total = 0.0

    # 1. Stawka za typ treści (np. Short vs Long)
    if campaign.payout_by_content_type and submission.content_type in campaign.payout_by_content_type:
        total += float(campaign.payout_by_content_type[submission.content_type])

    # 2. Wyświetlenia (CPM) - np. stawka X za każde 1000 wyświetleń
    if campaign.payout_per_views and campaign.views_unit_step:
        units = submission.views_count // campaign.views_unit_step
        total += units * float(campaign.payout_per_views)

    # 3. Kliknięcia (CPC)
    if campaign.payout_per_click:
        total += submission.clicks_count * float(campaign.payout_per_click)

    # Weryfikacja z górnym limitem budżetu na twórcę w danej kampanii
    if campaign.budget_per_creator and total > float(campaign.budget_per_creator):
        total = float(campaign.budget_per_creator)

    submission.calculated_payout = total

    await db.commit()
    await db.refresh(submission)
    return submission

@router.post("", response_model=CampaignSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    submission_data: CampaignSubmissionCreate, 
    db: AsyncSession = Depends(get_db)
):
    new_submission = CampaignSubmission(**submission_data.model_dump())
    db.add(new_submission)
    await db.commit()
    await db.refresh(new_submission)
    return new_submission