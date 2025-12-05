"""
Option model - investment package options.
FIXED: Changed Float to DECIMAL for precise financial calculations.
"""
from sqlalchemy import Column, Integer, String, DECIMAL, Boolean
from sqlalchemy.orm import relationship
from models.base import Base


class Option(Base):
    __tablename__ = 'options'

    optionID = Column(Integer, primary_key=True)
    projectID = Column(Integer, nullable=False)  # БЕЗ ForeignKey (composite key issue)
    projectName = Column(String)

    # FIXED: DECIMAL(12, 2) instead of Float for precise calculations
    costPerShare = Column(DECIMAL(12, 2))  # Cost per single share in USD
    packQty = Column(Integer)  # Number of shares in package
    packPrice = Column(DECIMAL(12, 2))  # Total package price in USD

    isActive = Column(Boolean, default=True)

    # Relationship
    purchases = relationship('Purchase', back_populates='option')

    def __repr__(self):
        return f"<Option(optionID={self.optionID}, project={self.projectID}, qty={self.packQty}, price={self.packPrice})>"