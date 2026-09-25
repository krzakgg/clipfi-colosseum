from sqlalchemy import Column, Integer, String, Boolean, Text, Numeric, DateTime, JSON, ForeignKey
from sqlalchemy.orm import relationship
from database import Base

class Campaign(Base):
    __tablename__ = "campaigns"

    # --- Podstawowe informacje ---
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    completed = Column(Boolean, default=False)
    is_private = Column(Boolean, default=False)  # Zamknięta kampania (tylko dla zaproszonych)
    cover_image_url = Column(String(1000), nullable=True)
    gallery_image_urls = Column(JSON, nullable=True)

    # --- Klucz Obcy i Relacja z Firmą ---
    company_id = Column(Integer, ForeignKey("companies.id", ondelete="CASCADE"), nullable=False)
    company = relationship("Company", back_populates="campaigns")

    # --- Relacje do Aplikacji i Zgłoszeń Materiałów ---
    applications = relationship("CampaignApplication", back_populates="campaign", cascade="all, delete-orphan")
    submissions = relationship("CampaignSubmission", back_populates="campaign", cascade="all, delete-orphan")
    ref_links = relationship("CampaignRefLink", back_populates="campaign", cascade="all, delete-orphan")

    # --- Informacje o produkcie i wytyczne ---
    product_description = Column(Text, nullable=True)
    press_kit_url = Column(String(500), nullable=True)
    brand_guidelines = Column(Text, nullable=True)

    # --- Budżety ---
    total_budget = Column(Numeric(12, 2), nullable=False)
    budget_per_creator = Column(Numeric(10, 2), nullable=True)
    budget_per_time_unit = Column(Numeric(10, 2), nullable=True)
    budget_per_language = Column(JSON, nullable=True)

    # --- Język i zasady zgłoszeń ---
    languages = Column(JSON, nullable=True)
    max_videos_per_creator = Column(Integer, nullable=True)
    max_submissions_per_day = Column(Integer, nullable=True)

    # --- Minimalne zasięgi twórcy ---
    min_views = Column(Integer, default=0)
    min_subscribers = Column(Integer, default=0)
    platform_requirements = Column(JSON, nullable=True)

    # --- Warunki finansowe i rozliczenie ---
    payout_by_content_type = Column(JSON, nullable=True)
    payout_per_views = Column(Numeric(10, 2), nullable=True)
    views_unit_step = Column(Integer, default=1000)
    payout_per_click = Column(Numeric(10, 2), nullable=True)

    # --- Ramy czasowe i alokacja budżetu ---
    start_date = Column(DateTime(timezone=True), nullable=True)
    end_date = Column(DateTime(timezone=True), nullable=True)
    rollover_remaining_budget = Column(Boolean, default=False)