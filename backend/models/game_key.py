import enum
from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship
from database import Base


class GameKeyStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    REVOKED = "revoked"


class KeyRequestStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class GameKey(Base):
    __tablename__ = "game_keys"

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    key_value = Column(String(500), nullable=False)
    status = Column(Enum(GameKeyStatus), default=GameKeyStatus.AVAILABLE, nullable=False, index=True)
    assigned_to_creator_id = Column(Integer, ForeignKey("creators.id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    campaign = relationship("Campaign", back_populates="game_keys")
    assigned_to_creator = relationship("Creator", back_populates="game_keys")
    request = relationship("KeyRequest", back_populates="game_key", uselist=False)


class KeyRequest(Base):
    __tablename__ = "key_requests"
    __table_args__ = (UniqueConstraint("campaign_id", "creator_id"),)

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    creator_id = Column(Integer, ForeignKey("creators.id", ondelete="CASCADE"), nullable=False, index=True)
    game_key_id = Column(Integer, ForeignKey("game_keys.id", ondelete="SET NULL"), nullable=True, unique=True)
    status = Column(Enum(KeyRequestStatus), default=KeyRequestStatus.PENDING, nullable=False, index=True)
    message = Column(Text, nullable=True)
    reviewer_feedback = Column(Text, nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    campaign = relationship("Campaign", back_populates="key_requests")
    creator = relationship("Creator", back_populates="key_requests")
    game_key = relationship("GameKey", back_populates="request")
