import enum
from sqlalchemy import Column, Integer, String, Text, Numeric, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from database import Base

class CampaignSubmissionStatus(str, enum.Enum):
    PENDING = "pending"                     # Oczekuje na weryfikację
    REVISION_REQUESTED = "revision_requested" # Wymaga poprawek (sugestie firmy)
    APPROVED = "approved"                   # Zaakceptowane
    REJECTED = "rejected"                   # Odrzucone

class CampaignPayoutStatus(str, enum.Enum):
    UNPAID = "unpaid"           # Nienaliczone / nieopłacone
    PROCESSING = "processing"   # W trakcie realizacji przelewu
    PAID = "paid"               # Opłacone

class CampaignSubmission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)

    # --- Klucze Obce (Relacje) ---
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    creator_id = Column(Integer, ForeignKey("creators.id", ondelete="CASCADE"), nullable=False)

    # Obiekty relacyjne (pozwalają na dostęp np. submission.creator.full_name)
    campaign = relationship("Campaign", back_populates="submissions")
    creator = relationship("Creator", back_populates="submissions")

    # --- Dane Zgłoszonego Materiału ---
    video_url = Column(String(500), nullable=False)
    platform = Column(String(50), nullable=False)      # np. "youtube", "tiktok", "instagram"
    content_type = Column(String(50), nullable=False)  # np. "Short", "LongVideo", "Reel"

    # --- Weryfikacja i Akceptacja przez Firmę ---
    status = Column(Enum(CampaignSubmissionStatus), default=CampaignSubmissionStatus.PENDING, nullable=False)
    feedback = Column(Text, nullable=True)             # Uwagi marki, powód odrzucenia lub wskazówki do poprawek
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # --- Wyniki Materiału (Statystyki) ---
    views_count = Column(Integer, default=0)
    clicks_count = Column(Integer, default=0)
    last_metrics_update = Column(DateTime(timezone=True), nullable=True)

    # --- Obsługa Wypłat ---
    payout_status = Column(Enum(CampaignPayoutStatus), default=CampaignPayoutStatus.UNPAID, nullable=False)
    calculated_payout = Column(Numeric(10, 2), default=0.00) # Kwota wyliczona ze stawek (CPM, CPC, typ treści)
    paid_amount = Column(Numeric(10, 2), nullable=True)      # Rzeczywiście wypłacona kwota
    paid_at = Column(DateTime(timezone=True), nullable=True)

    # --- Znaczniki Czasu ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())