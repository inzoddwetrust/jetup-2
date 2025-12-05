"""
Payment model - tracks deposits and withdrawals.
FIXED: Increased DECIMAL precision to support large crypto amounts.
"""
from sqlalchemy import Column, Integer, String, DECIMAL, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from models.base import Base, AuditMixin


class Payment(Base, AuditMixin):
    __tablename__ = 'payments'

    # Primary key
    paymentID = Column(Integer, primary_key=True, autoincrement=True)

    # Relations
    userID = Column(Integer, ForeignKey('users.userID'), nullable=False)

    # Denormalized user info for convenience
    firstname = Column(String, nullable=True)
    surname = Column(String, nullable=True)

    # Payment details
    direction = Column(String, nullable=False)  # 'in' (пополнение) или 'out' (вывод)

    # FIXED: DECIMAL(18, 2) instead of (12, 2) to support large amounts
    amount = Column(DECIMAL(18, 2), nullable=False)  # Сумма в USD (up to 9,999,999,999,999,999.99)

    method = Column(String, nullable=False)  # USDT-TRC20, ETH, BNB и т.д.

    # FIXED: DECIMAL(20, 8) instead of (12, 8) to support large crypto amounts
    # Supports up to 999,999,999,999.99999999 (e.g. 1M USDT with 8 decimals precision)
    sumCurrency = Column(DECIMAL(20, 8))  # Сумма в криптовалюте

    # Wallet addresses
    fromWallet = Column(String, nullable=True)  # Откуда пришла транзакция
    toWallet = Column(String, nullable=True)  # Куда отправлена

    # Transaction info
    txid = Column(String, nullable=True)  # Transaction ID в блокчейне
    status = Column(String, default="pending")  # pending, check, confirmed, rejected, cancelled

    # Confirmation
    confirmedBy = Column(String, nullable=True)  # Кто подтвердил (админ)
    confirmationTime = Column(DateTime, nullable=True)  # Когда подтвердил

    # Additional
    notes = Column(String, nullable=True)  # Заметки

    # Note: createdAt, updatedAt, ownerTelegramID, ownerEmail - от AuditMixin

    # Relationships
    user = relationship('User', backref='payments')

    def __repr__(self):
        return f"<Payment(paymentID={self.paymentID}, direction={self.direction}, amount={self.amount})>"