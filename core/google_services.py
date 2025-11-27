# jetup/core/google_services.py
"""
Google Services module for Jetup.
Provides access to Google Sheets and Drive (async and sync versions).
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

# Cached clients for sync access
_sheets_client = None
_drive_service = None


def _create_credentials():
    """Create Google credentials from service account file."""
    credentials_path = Config.get(Config.GOOGLE_CREDENTIALS_PATH)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    return Credentials.from_service_account_file(credentials_path, scopes=scopes)


def get_sheets_client():
    """
    Get Google Sheets client (synchronous).

    Used by sync code like UniversalSyncEngine.

    Returns:
        gspread.Client: Authorized gspread client

    Example:
        sheets_client = get_sheets_client()
        spreadsheet = sheets_client.open_by_key(sheet_id)
    """
    global _sheets_client
    if _sheets_client is None:
        creds = _create_credentials()
        _sheets_client = gspread.authorize(creds)
        logger.info("Google Sheets client created (sync)")
    return _sheets_client


def get_drive_service():
    """
    Get Google Drive service (synchronous).

    Returns:
        Drive Service: Google Drive API service
    """
    global _drive_service
    if _drive_service is None:
        creds = _create_credentials()
        _drive_service = build("drive", "v3", credentials=creds, cache_discovery=False)
        logger.info("Google Drive service created (sync)")
    return _drive_service


async def get_google_services() -> Tuple[Any, Any]:
    """
    Get Google Sheets and Drive clients (async).

    Runs credential creation in thread pool to avoid blocking.

    Returns:
        Tuple[gspread.Client, Drive Service]: Sheets client and Drive service

    Example:
        sheets_client, drive_service = await get_google_services()
        spreadsheet = sheets_client.open_by_key(sheet_id)
    """

    def _create_clients():
        sheets = get_sheets_client()
        drive = get_drive_service()
        return sheets, drive

    async with THREAD_SEMAPHORE:
        return await asyncio.to_thread(_create_clients)


def clear_clients_cache():
    """Clear cached clients (use after credential changes)."""
    global _sheets_client, _drive_service
    _sheets_client = None
    _drive_service = None
    logger.info("Google services cache cleared")