# jetup/core/google_services.py
"""
Minimal Google Services module for Jetup.
Provides async access to Google Sheets and Drive.
"""
import logging
import asyncio
from typing import Tuple, Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
import gspread

from config import Config

logger = logging.getLogger(__name__)

# Semaphore to limit concurrent Google API calls
THREAD_SEMAPHORE = asyncio.Semaphore(10)


async def get_google_services() -> Tuple[Any, Any]:
    """
    Get Google Sheets and Drive clients.

    Returns:
        Tuple[gspread.Client, Drive Service]: Sheets client and Drive service

    Example:
        sheets_client, drive_service = await get_google_services()
        spreadsheet = sheets_client.open_by_key(sheet_id)
    """

    def _create_clients():
        credentials_path = Config.get(Config.GOOGLE_CREDENTIALS_PATH)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]

        creds = Credentials.from_service_account_file(
            credentials_path,
            scopes=scopes
        )

        sheets_client = gspread.authorize(creds)
        drive_service = build(
            "drive", "v3",
            credentials=creds,
            cache_discovery=False
        )

        return sheets_client, drive_service

    # Run in thread to avoid blocking
    async with THREAD_SEMAPHORE:
        return await asyncio.to_thread(_create_clients)