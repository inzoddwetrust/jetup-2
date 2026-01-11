# services/imports.py
"""
Import services for Projects, Options, and other data from Google Sheets.
"""
import logging
from typing import Dict, Any
from decimal import Decimal

from core.db import get_session
from core.google_services import get_google_services
from models.project import Project
from models.option import Option
from config import Config

logger = logging.getLogger(__name__)


async def import_projects_and_options() -> Dict[str, Any]:
    """
    Import Projects and Options from Google Sheets.

    Returns:
        Dict with import statistics
    """
    logger.info("Starting Projects and Options import from Google Sheets...")

    results = {
        "success": True,
        "projects": {"added": 0, "updated": 0, "errors": 0},
        "options": {"added": 0, "updated": 0, "errors": 0},
        "error_messages": []
    }

    try:
        # Get Google Sheets service
        sheets_client, _ = await get_google_services()
        sheet_id = Config.get(Config.GOOGLE_SHEET_ID)
        spreadsheet = sheets_client.open_by_key(sheet_id)

        # Import Projects
        logger.info("Importing Projects...")
        projects_sheet = spreadsheet.worksheet('Projects')
        projects_rows = projects_sheet.get_all_records()

        session = get_session()
        try:
            for idx, row in enumerate(projects_rows, start=2):
                try:
                    # Validate required fields
                    if not all(row.get(f) for f in ['projectID', 'projectName', 'lang', 'status']):
                        results["projects"]["errors"] += 1
                        results["error_messages"].append(f"Row {idx}: Missing required fields")
                        continue

                    # Get or create project (composite key: projectID + lang)
                    project = session.query(Project).filter_by(
                        projectID=row['projectID'],
                        lang=row['lang']
                    ).first()

                    is_update = bool(project)
                    if not project:
                        project = Project()

                    # Set fields
                    project.projectID = row['projectID']
                    project.lang = row['lang']
                    project.projectName = row['projectName']
                    project.projectTitle = row.get('projectTitle')
                    project.fullText = row.get('fullText')
                    project.status = row['status']
                    project.rate = float(row['rate']) if row.get('rate') else None
                    project.linkImage = row.get('linkImage')
                    project.linkPres = row.get('linkPres')
                    project.linkVideo = row.get('linkVideo')
                    project.docsFolder = row.get('docsFolder')

                    if not is_update:
                        session.add(project)
                        results["projects"]["added"] += 1
                    else:
                        results["projects"]["updated"] += 1

                except Exception as e:
                    results["projects"]["errors"] += 1
                    error_msg = f"Row {idx} error: {str(e)}"
                    results["error_messages"].append(error_msg)
                    logger.error(error_msg)

            # Import Options
            logger.info("Importing Options...")
            options_sheet = spreadsheet.worksheet('Options')
            options_rows = options_sheet.get_all_records()

            for idx, row in enumerate(options_rows, start=2):
                try:
                    # Validate required fields
                    if not all(row.get(f) for f in ['optionID', 'projectID', 'projectName']):
                        results["options"]["errors"] += 1
                        results["error_messages"].append(f"Options row {idx}: Missing required fields")
                        continue

                    # Get or create option
                    option = session.query(Option).filter_by(
                        optionID=row['optionID']
                    ).first()

                    is_update = bool(option)
                    if not option:
                        option = Option()

                    # Set fields
                    option.optionID = row['optionID']
                    option.projectID = row['projectID']
                    option.projectName = row['projectName']
                    option.costPerShare = float(row.get('costPerShare', 0))
                    option.packQty = int(row.get('packQty', 0))
                    option.packPrice = float(row.get('packPrice', 0))

                    # isActive = True ONLY if value is "1"
                    # Column name in Google Sheets: "isActive?"
                    option.isActive = str(row.get('isActive?', '')).strip() == '1'

                    if not is_update:
                        session.add(option)
                        results["options"]["added"] += 1
                    else:
                        results["options"]["updated"] += 1

                except Exception as e:
                    results["options"]["errors"] += 1
                    error_msg = f"Options row {idx} error: {str(e)}"
                    results["error_messages"].append(error_msg)
                    logger.error(error_msg)

            # Commit all changes
            session.commit()

            logger.info(
                f"Import completed: "
                f"Projects (added={results['projects']['added']}, updated={results['projects']['updated']}, errors={results['projects']['errors']}), "
                f"Options (added={results['options']['added']}, updated={results['options']['updated']}, errors={results['options']['errors']})"
            )

        finally:
            session.close()

    except Exception as e:
        results["success"] = False
        error_msg = f"Critical import error: {str(e)}"
        results["error_messages"].append(error_msg)
        logger.error(error_msg, exc_info=True)

    return results