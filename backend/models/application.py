import enum
from sqlalchemy import Column, Integer, String, Text, Numeric, DateTime, ForeignKey, Enum, func
from sqlalchemy.orm import relationship
from database import Base

class ApplicationStatus(str, enum.Enum):
    PENDING = "pending"       # Oczekuje na rozpatrzenie przez markę
    INVITED = "invited"       # Marka zaprosiła twórcę (dla kampanii prywatnych)
    ACCEPTED = "accepted"     # Marka zaakceptowała twórcę – ma zielone światło na tworzenie wideo
    REJECTED = "rejected"     # Marka odrzuciła zgłoszenie
    WITHDRAWN = "withdrawn"   # Twórca sam wycofał aplikację

class CampaignApplication(Base):
    __tablename__ = "campaign_applications"

    id = Column(Integer, primary_key=True, index=True)

    # --- Klucze Obce ---
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    creator_id = Column(Integer, ForeignKey("creators.id", ondelete="CASCADE"), nullable=False)

    # --- Relacje ---
    campaign = relationship("Campaign", back_populates="applications")
    creator = relationship("Creator", back_populates="applications")

    # --- Dane Zgłoszenia ---
    status = Column(Enum(ApplicationStatus), default=ApplicationStatus.PENDING, nullable=False)
    pitch = Column(Text, nullable=True)                        # Pomysł na wideo / dlaczego twórca pasuje do marki
    proposed_rate = Column(Numeric(10, 2), nullable=True)     # Opcjonalna własna proponowana stawka
    proposed_content_type = Column(String(50), nullable=True) # np. "Short", "LongVideo", "Reel"

    # --- Decyzja Marki ---
    feedback = Column(Text, nullable=True)                     # Powód odrzucenia lub wytyczne po akceptacji
    reviewed_at = Column(DateTime(timezone=True), nullable=True)

    # --- Znaczniki Czasu ---
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())