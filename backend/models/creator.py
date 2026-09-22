from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, JSON, func
from sqlalchemy.orm import relationship
from database import Base

class Creator(Base):
    __tablename__ = "creators"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    avatar_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)

    # Weryfikacja profilu i wewnętrzna ocena
    is_verified = Column(Boolean, default=False)
    rating = Column(Float, default=0.0)

    # Preferencje i umiejętności
    languages = Column(JSON, nullable=True)
    categories = Column(JSON, nullable=True)

    # Statystyki z zewnętrznych platform
    platform_stats = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # --- Relacje ---
    applications = relationship("CampaignApplication", back_populates="creator", cascade="all, delete-orphan")
    submissions = relationship("CampaignSubmission", back_populates="creator", cascade="all, delete-orphan")