from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from database import Base


class CampaignRefLink(Base):
    __tablename__ = "campaign_ref_links"
    __table_args__ = (UniqueConstraint("campaign_id", "creator_id"),)

    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False)
    creator_id = Column(Integer, ForeignKey("creators.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(32), unique=True, index=True, nullable=False)
    url = Column(String(500), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    campaign = relationship("Campaign", back_populates="ref_links")
    creator = relationship("Creator", back_populates="ref_links")
