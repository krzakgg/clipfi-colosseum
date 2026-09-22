from sqlalchemy import Column, Integer, String, Text, DateTime, func
from sqlalchemy.orm import relationship
from database import Base

class Company(Base):
    __tablename__ = "companies"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=False)
    website_url = Column(String(500), nullable=True)
    logo_url = Column(String(500), nullable=True)
    description = Column(Text, nullable=True)
    industry = Column(String(100), nullable=True)   # np. Gaming, E-commerce, Beauty, Tech
    tax_id = Column(String(50), nullable=True)      # NIP / Tax ID do rozliczeń i faktur

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relacja 1-do-wielu: jedna firma posiada wiele kampanii
    campaigns = relationship("Campaign", back_populates="company", cascade="all, delete-orphan")