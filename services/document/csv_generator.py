# jetup/services/document/csv_generator.py
"""
CSV report generator service.
Generates various reports in CSV format for users.
"""
import io
import csv
import logging
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from models.active_balance import ActiveBalance
from models.passive_balance import PassiveBalance

logger = logging.getLogger(__name__)


class CSVGenerator:
    """Service for generating CSV reports."""

    # Report type registry
    REPORTS = {
        "team_full": {
            "name": "Team Full Report",
            "description": "Complete team structure with referrals and purchases"
        },
        "active_balance_history": {
            "name": "Active Balance History",
            "description": "All active balance transactions"
        },
        "passive_balance_history": {
            "name": "Passive Balance History",
            "description": "All passive balance transactions"
        }
    }

    def generate_report(
            self,
            session: Session,
            user: User,
            report_type: str,
            params: Dict[str, Any] = None
    ) -> Optional[bytes]:
        """
        Generate CSV report.

        Args:
            session: Database session
            user: User requesting report
            report_type: Type of report from REPORTS keys
            params: Additional parameters

        Returns:
            CSV file as bytes or None if failed
        """
        if report_type not in self.REPORTS:
            logger.error(f"Unknown report type: {report_type}")
            return None

        try:
            if params is None:
                params = {}

            # Get generator method
            method_name = f"_generate_{report_type}"
            if not hasattr(self, method_name):
                logger.error(f"No generator for report type: {report_type}")
                return None

            generator = getattr(self, method_name)

            # Generate report data
            headers, data = generator(session, user, params)

            # Create CSV in memory
            string_output = io.StringIO()
            writer = csv.writer(string_output, delimiter=';')  # Semicolon for Excel

            # Write BOM for Excel UTF-8
            string_output.write('\ufeff')

            # Write headers
            writer.writerow(headers)

            # Write data
            for row in data:
                writer.writerow(row)

            # Convert to bytes
            output = string_output.getvalue().encode('utf-8')

            return output

        except Exception as e:
            logger.error(f"Error generating {report_type} report: {e}", exc_info=True)
            return None

    def _generate_team_full(
            self,
            session: Session,
            user: User,
            params: Dict[str, Any]
    ) -> Tuple[List[str], List[List[Any]]]:
        """
        Generate full team report with referrals.

        Returns:
            (headers, data_rows)
        """
        headers = [
            "ID", "Name", "Registration Date", "Level",
            "Direct Referrals", "Total Team", "Purchases Amount", "Bonus Gained",
            "Purchase ID", "Purchase Date", "Project", "Shares", "Price"
        ]

        def get_team_size(telegram_id, visited=None):
            """Recursively calculate team size."""
            if visited is None:
                visited = set()

            referrals = session.query(User.telegramID).filter(
                User.upline == telegram_id
            ).all()

            total = 0
            for (ref_id,) in referrals:
                if ref_id not in visited:
                    visited.add(ref_id)
                    total += 1 + get_team_size(ref_id, visited)
            return total

        def get_referral_tree(telegram_id, level=1, visited=None):
            """Recursively build referral tree."""
            if visited is None:
                visited = set()

            if telegram_id in visited:
                return []

            visited.add(telegram_id)
            referrals = session.query(User).filter(User.upline == telegram_id).all()

            result = []
            for ref in referrals:
                # Get basic info
                direct_refs_count = session.query(func.count(User.userID)).filter(
                    User.upline == ref.telegramID
                ).scalar() or 0

                total_team = get_team_size(ref.telegramID)

                # Get purchases sum
                purchases_sum = session.query(func.sum(Purchase.packPrice)).filter(
                    Purchase.userID == ref.userID
                ).scalar() or 0

                # Get bonuses from this referral
                bonuses_gained = session.query(func.sum(Bonus.bonusAmount)).filter(
                    Bonus.userID == user.userID,
                    Bonus.downlineID == ref.userID
                ).scalar() or 0

                # User info row
                user_row = [
                    ref.userID,
                    f"{ref.firstname} {ref.surname or ''}".strip(),
                    ref.createdAt.strftime("%Y-%m-%d") if ref.createdAt else "",
                    level,
                    direct_refs_count,
                    total_team,
                    float(purchases_sum) if purchases_sum else 0,
                    float(bonuses_gained) if bonuses_gained else 0
                ]

                # Add user row
                result.append(user_row)

                # Get purchases
                purchases = session.query(Purchase).filter(
                    Purchase.userID == ref.userID
                ).order_by(Purchase.createdAt.desc()).all()

                # Add purchase rows
                for purchase in purchases:
                    purchase_row = [""] * 8  # Empty cells for user data
                    purchase_row.extend([
                        purchase.purchaseID,
                        purchase.createdAt.strftime("%Y-%m-%d %H:%M:%S") if purchase.createdAt else "",
                        purchase.projectName,
                        purchase.packQty,
                        float(purchase.packPrice)
                    ])
                    result.append(purchase_row)

                # Add nested referrals
                result.extend(get_referral_tree(ref.telegramID, level + 1, visited))

            return result

        # Generate data
        data = get_referral_tree(user.telegramID)

        return headers, data

    def _generate_active_balance_history(
            self,
            session: Session,
            user: User,
            params: Dict[str, Any]
    ) -> Tuple[List[str], List[List[Any]]]:
        """
        Generate active balance history report.

        Returns:
            (headers, data_rows)
        """
        headers = ["Transaction ID", "Date", "Amount", "Status", "Reason", "Details", "Notes"]

        # Get all active balance records
        records = session.query(ActiveBalance).filter(
            ActiveBalance.userID == user.userID
        ).order_by(ActiveBalance.createdAt.desc()).all()

        data = []
        for record in records:
            # Parse reason field
            doc_id = ""
            reason_type = ""
            if record.reason and '=' in record.reason:
                parts = record.reason.split('=')
                reason_type = parts[0]
                doc_id = parts[1]

            row = [
                record.paymentID,
                record.createdAt.strftime("%Y-%m-%d %H:%M:%S") if record.createdAt else "",
                float(record.amount),
                record.status,
                reason_type,
                doc_id,
                record.notes or ""
            ]
            data.append(row)

        return headers, data

    def _generate_passive_balance_history(
            self,
            session: Session,
            user: User,
            params: Dict[str, Any]
    ) -> Tuple[List[str], List[List[Any]]]:
        """
        Generate passive balance history report.

        Returns:
            (headers, data_rows)
        """
        headers = ["Transaction ID", "Date", "Amount", "Status", "Reason", "Details", "Notes"]

        # Get all passive balance records
        records = session.query(PassiveBalance).filter(
            PassiveBalance.userID == user.userID
        ).order_by(PassiveBalance.createdAt.desc()).all()

        data = []
        for record in records:
            # Parse reason field
            doc_id = ""
            reason_type = ""
            if record.reason and '=' in record.reason:
                parts = record.reason.split('=')
                reason_type = parts[0]
                doc_id = parts[1]

            row = [
                record.paymentID,
                record.createdAt.strftime("%Y-%m-%d %H:%M:%S") if record.createdAt else "",
                float(record.amount),
                record.status,
                reason_type,
                doc_id,
                record.notes or ""
            ]
            data.append(row)

        return headers, data