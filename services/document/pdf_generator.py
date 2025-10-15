# jetup/services/document/pdf_generator.py
"""
PDF document generator service.
Generates purchase agreements and certificates from BookStack templates.
"""
import logging
import os
import subprocess
from typing import Optional
from sqlalchemy.orm import Session

from models.user import User
from models.purchase import Purchase
from models.project import Project
from models.option import Option
from services.document.bookstack_service import BookStackService
from config import Config

logger = logging.getLogger(__name__)


class PDFGenerator:
    """Service for generating PDF documents from templates."""

    def __init__(self):
        self.bookstack = BookStackService()
        self._wkhtmltopdf_path = None

    def _find_wkhtmltopdf(self) -> Optional[str]:
        """Find wkhtmltopdf binary path."""
        if self._wkhtmltopdf_path:
            return self._wkhtmltopdf_path

        # Check standard locations
        for path in ['/usr/bin/wkhtmltopdf', '/usr/local/bin/wkhtmltopdf', '/bin/wkhtmltopdf']:
            if os.path.exists(path):
                self._wkhtmltopdf_path = path
                logger.info(f"Found wkhtmltopdf at {path}")
                return path

        # Try using which command
        try:
            result = subprocess.run(['which', 'wkhtmltopdf'], capture_output=True, text=True)
            if result.returncode == 0:
                path = result.stdout.strip()
                if path:
                    self._wkhtmltopdf_path = path
                    logger.info(f"Found wkhtmltopdf using which: {path}")
                    return path
        except Exception as e:
            logger.warning(f"Could not use which command: {e}")

        logger.warning("wkhtmltopdf not found in standard locations")
        return None

    def _generate_pdf_with_pdfkit(self, html: str) -> Optional[bytes]:
        """Generate PDF using pdfkit/wkhtmltopdf."""
        try:
            import pdfkit

            wkhtmltopdf_path = self._find_wkhtmltopdf()
            if not wkhtmltopdf_path:
                logger.error("wkhtmltopdf binary not found")
                return None

            # Configure pdfkit
            config = pdfkit.configuration(wkhtmltopdf=wkhtmltopdf_path)

            # Options for wkhtmltopdf
            options = {
                'encoding': 'UTF-8',
                'page-size': 'A4',
                'margin-top': '2cm',
                'margin-right': '2cm',
                'margin-bottom': '2cm',
                'margin-left': '2cm',
                'footer-right': '[page]/[topage]',
                'footer-font-size': '9',
                'no-outline': None,
                'quiet': ''
            }

            # Add basic styles
            styled_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    body {{ 
                        font-family: Arial, sans-serif; 
                        line-height: 1.6;
                    }}
                    h1, h2, h3 {{ color: #333; }}
                    table {{ 
                        border-collapse: collapse; 
                        width: 100%; 
                        margin: 1em 0; 
                    }}
                    th, td {{ 
                        border: 1px solid #ddd; 
                        padding: 8px; 
                        text-align: left; 
                    }}
                    th {{ background-color: #f2f2f2; }}
                </style>
            </head>
            <body>
                {html}
            </body>
            </html>
            """

            # Generate PDF
            pdf_bytes = pdfkit.from_string(styled_html, False, options=options, configuration=config)

            if pdf_bytes:
                logger.info(f"PDF generated with pdfkit, size: {len(pdf_bytes)} bytes")
                return pdf_bytes
            else:
                logger.error("pdfkit returned empty PDF")
                return None

        except ImportError:
            logger.warning("pdfkit not available")
            return None
        except Exception as e:
            logger.error(f"Error generating PDF with pdfkit: {e}")
            return None

    def _generate_pdf_with_weasyprint(self, html: str) -> Optional[bytes]:
        """Generate PDF using weasyprint as fallback."""
        try:
            import weasyprint

            # Add basic styles
            styled_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    @page {{ 
                        size: A4; 
                        margin: 2cm; 
                    }}
                    body {{ 
                        font-family: Arial, sans-serif; 
                        line-height: 1.6;
                    }}
                    h1, h2, h3 {{ color: #333; }}
                    table {{ 
                        border-collapse: collapse; 
                        width: 100%; 
                        margin: 1em 0; 
                    }}
                    th, td {{ 
                        border: 1px solid #ddd; 
                        padding: 8px; 
                        text-align: left; 
                    }}
                    th {{ background-color: #f2f2f2; }}
                </style>
            </head>
            <body>
                {html}
            </body>
            </html>
            """

            # Generate PDF
            html_obj = weasyprint.HTML(string=styled_html)
            pdf_bytes = html_obj.write_pdf()

            if pdf_bytes:
                logger.info(f"PDF generated with WeasyPrint, size: {len(pdf_bytes)} bytes")
                return pdf_bytes
            else:
                logger.error("WeasyPrint returned empty PDF")
                return None

        except ImportError:
            logger.warning("WeasyPrint not available")
            return None
        except Exception as e:
            logger.error(f"Error generating PDF with WeasyPrint: {e}")
            return None

    def html_to_pdf(self, html: str) -> Optional[bytes]:
        """
        Convert HTML to PDF bytes.
        Tries pdfkit first, then weasyprint as fallback.

        Args:
            html: HTML content

        Returns:
            PDF bytes or None if failed
        """
        if not html or not html.strip():
            logger.error("Empty HTML content for PDF generation")
            return None

        logger.debug(f"Generating PDF from HTML (length: {len(html)})")

        # Try pdfkit first (primary method)
        pdf_bytes = self._generate_pdf_with_pdfkit(html)
        if pdf_bytes:
            return pdf_bytes

        # Fallback to weasyprint
        logger.info("Falling back to WeasyPrint")
        pdf_bytes = self._generate_pdf_with_weasyprint(html)
        if pdf_bytes:
            return pdf_bytes

        logger.error("Failed to generate PDF with both pdfkit and weasyprint")
        return None


def generate_document(
        session: Session,
        user: User,
        document_type: str,
        document_id: int
) -> Optional[bytes]:
    """
    Generate PDF document (purchase agreement or certificate).

    Args:
        session: Database session
        user: User requesting document
        document_type: 'purchase' or 'certificate'
        document_id: Purchase ID

    Returns:
        PDF bytes or None if generation failed
    """
    try:
        generator = PDFGenerator()

        # Get purchase
        purchase = session.query(Purchase).filter_by(
            purchaseID=document_id,
            userID=user.userID
        ).first()

        if not purchase:
            logger.warning(f"Purchase {document_id} not found for user {user.userID}")
            return None

        # Get project
        project = session.query(Project).filter(
            Project.projectID == purchase.projectID,
            Project.lang == user.lang
        ).first() or session.query(Project).filter(
            Project.projectID == purchase.projectID,
            Project.lang == 'en'
        ).first()

        if not project:
            logger.error(f"Project {purchase.projectID} not found")
            return None

        # Get option
        option = session.query(Option).filter_by(optionID=purchase.optionID).first()
        if not option:
            logger.error(f"Option {purchase.optionID} not found")
            return None

        # Determine document type for BookStack
        if document_type == 'purchase':
            doc_type = 'agreement'
        else:  # certificate
            doc_type = 'cert'

        # Get PROJECT_DOCUMENTS mapping
        project_documents = Config.get('PROJECT_DOCUMENTS')
        if not project_documents:
            # Fallback to default mapping
            project_documents = {
                "agreement": "option-alienation-agreement",
                "cert": "option-certificate"
            }

        doc_slug = project_documents.get(doc_type)
        if not doc_slug:
            logger.error(f"Unknown document type: {doc_type}")
            return None

        # Get HTML template from BookStack
        html = generator.bookstack.get_document_html(project, doc_slug)
        if not html:
            logger.error(f"No HTML template found for {doc_type} in project {project.projectID}")
            return None

        # Prepare context
        context = {
            # Document data
            'docNumber': purchase.purchaseID,
            'date': purchase.createdAt.strftime('%d.%m.%Y'),

            # User data
            'firstname': user.firstname,
            'surname': user.surname or '',
            'city': user.city or 'Not provided',
            'country': user.country or 'Not provided',
            'address': user.address or 'Not provided',
            'passport': user.passport or 'Not provided',
            'birthday': user.birthday or 'Not provided',  # String field in DB
            'email': user.email or 'Not provided',

            # Purchase data
            'packQty': purchase.packQty,
            'pricePerShare': float(option.costPerShare),
            'packPrice': float(purchase.packPrice),
            'projectName': project.projectName,
            'optionName': option.projectName  # Note: Option model uses projectName field
        }

        # Add certificate-specific data
        if document_type == 'certificate':
            # Get all purchases for this project to calculate total
            all_purchases = session.query(Purchase).filter_by(
                userID=user.userID,
                projectID=purchase.projectID
            ).all()

            total_shares = sum(p.packQty for p in all_purchases)
            context['totalShares'] = total_shares
            context['certNumber'] = f"CERT-{purchase.projectID}-{user.userID}"

        # Render template with context
        rendered_html = generator.bookstack.render_template(html, context)

        # Convert to PDF
        pdf_bytes = generator.html_to_pdf(rendered_html)

        if pdf_bytes:
            logger.info(f"Successfully generated {document_type} document for purchase {document_id}")
        else:
            logger.error(f"Failed to generate PDF for {document_type} {document_id}")

        return pdf_bytes

    except Exception as e:
        logger.error(f"Error generating {document_type} document: {e}", exc_info=True)
        return None