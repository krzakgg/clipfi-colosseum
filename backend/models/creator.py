from sqlalchemy import Column, Integer, String, Text, Boolean, Float, DateTime, JSON, Numeric, func
from sqlalchemy.orm import relationship
from database import Base

class Creator(Base):
    __tablename__ = "creators"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    bio = Column(Text, nullable=True)
    solana_wallet_address = Column(String(44), unique=True, nullable=True, index=True)
    internal_balance = Column(Numeric(20, 8), nullable=False, server_default="0")

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
    ref_links = relationship("CampaignRefLink", back_populates="creator", cascade="all, delete-orphan")
    game_keys = relationship("GameKey", back_populates="assigned_to_creator")
    key_requests = relationship("KeyRequest", back_populates="creator", cascade="all, delete-orphan")