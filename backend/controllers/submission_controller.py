from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from datetime import datetime, timezone
from decimal import Decimal

from database import get_db
from models import Campaign, CampaignApplication
from models import CampaignSubmission, CampaignSubmissionStatus, Creator
from models.application import ApplicationStatus
from typing import List
from schemas import CampaignSubmissionCreate, CampaignSubmissionReview, CampaignSubmissionMetricsUpdate, CampaignSubmissionResponse

router = APIRouter(prefix="/api/submissions", tags=["submissions"])


def _submission_response(submission, creator):
    return {
        **{column.name: getattr(submission, column.name) for column in CampaignSubmission.__table__.columns},
        "creator_username": creator.username,
        "creator_full_name": creator.full_name,
        "creator_avatar_url": creator.avatar_url,
        "creator_languages": creator.languages,
        "creator_platform_stats": creator.platform_stats,
    }

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

    campaign = await db.get(Campaign, submission.campaign_id)
    if not campaign or campaign.company_id != review.company_id:
        raise HTTPException(status_code=403, detail="Nie możesz oceniać tego materiału")

    if review.status not in (
        CampaignSubmissionStatus.APPROVED,
        CampaignSubmissionStatus.REJECTED,
        CampaignSubmissionStatus.REVISION_REQUESTED,
    ):
        raise HTTPException(status_code=400, detail="Nieprawidłowy status decyzji")

    submission.status = review.status
    submission.feedback = review.feedback
    submission.reviewed_at = datetime.utcnow()

    await db.commit()
    await db.refresh(submission)
    creator = await db.get(Creator, submission.creator_id)
    return _submission_response(submission, creator)


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

    submission.views_count = metrics.views_count
    submission.last_metrics_update = datetime.now(timezone.utc)

    payout = Decimal("0")
    rates = campaign.payout_by_content_type or {}
    if submission.content_type in rates:
        payout += Decimal(str(rates[submission.content_type]))
    if campaign.payout_per_views and campaign.views_unit_step:
        payout += (submission.views_count // campaign.views_unit_step) * campaign.payout_per_views
    if campaign.budget_per_creator:
        payout = min(payout, campaign.budget_per_creator)
    submission.calculated_payout = payout.quantize(Decimal("0.01"))

    await db.commit()
    await db.refresh(submission)
    return submission

@router.post("", response_model=CampaignSubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_submission(
    submission_data: CampaignSubmissionCreate, 
    db: AsyncSession = Depends(get_db)
):
    campaign = await db.get(Campaign, submission_data.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")

    creator = await db.get(Creator, submission_data.creator_id)
    if not creator:
        raise HTTPException(status_code=404, detail="Twórca nie istnieje")

    application_result = await db.execute(
        select(CampaignApplication).where(
            CampaignApplication.campaign_id == submission_data.campaign_id,
            CampaignApplication.creator_id == submission_data.creator_id,
            CampaignApplication.status == ApplicationStatus.ACCEPTED,
        )
    )
    if not application_result.scalar_one_or_none():
        raise HTTPException(
            status_code=403,
            detail="Możesz wysłać materiał dopiero po zaakceptowaniu aplikacji przez firmę",
        )

    existing_result = await db.execute(
        select(CampaignSubmission).where(
            CampaignSubmission.campaign_id == submission_data.campaign_id,
            CampaignSubmission.creator_id == submission_data.creator_id,
            CampaignSubmission.video_url == submission_data.video_url,
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Ten materiał został już wysłany")

    new_submission = CampaignSubmission(**submission_data.model_dump())
    db.add(new_submission)
    await db.commit()
    await db.refresh(new_submission)
    return _submission_response(new_submission, creator)


@router.get("/campaign/{campaign_id}", response_model=List[CampaignSubmissionResponse])
async def get_campaign_submissions(
    campaign_id: int,
    company_id: int,
    db: AsyncSession = Depends(get_db),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Kampania nie istnieje")
    if campaign.company_id != company_id:
        raise HTTPException(status_code=403, detail="Nie masz dostępu do materiałów tej kampanii")

    result = await db.execute(
        select(CampaignSubmission, Creator)
        .join(Creator, Creator.id == CampaignSubmission.creator_id)
        .where(CampaignSubmission.campaign_id == campaign_id)
        .order_by(CampaignSubmission.created_at.desc())
    )
    return [_submission_response(submission, creator) for submission, creator in result.all()]