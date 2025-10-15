# jetup/services/document/bookstack_service.py
"""
BookStack integration service for document management.
Handles HTML template retrieval from private BookStack instance.
"""
import logging
import requests
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import jinja2

from config import Config

logger = logging.getLogger(__name__)


class BookStackAPIError(Exception):
    """Exception for BookStack API errors."""
    pass


class TemplateCache:
    """Simple cache for HTML templates from BookStack."""
    _cache = {}  # {key: (html, timestamp)}
    _ttl = 600  # 10 minutes

    @classmethod
    def get(cls, key: str) -> Optional[str]:
        """Get HTML from cache with TTL check."""
        if key in cls._cache:
            html, timestamp = cls._cache[key]
            if (datetime.now(timezone.utc) - timestamp).total_seconds() < cls._ttl:
                return html
        return None

    @classmethod
    def set(cls, key: str, html: str) -> None:
        """Store HTML in cache."""
        cls._cache[key] = (html, datetime.now(timezone.utc))

    @classmethod
    def clear(cls):
        """Clear all cache."""
        cls._cache.clear()


class BookStackClient:
    """Client for private BookStack API."""

    def __init__(self, base_url: str, token_id: str, token_secret: str):
        """Initialize BookStack API client with auth tokens."""
        self.base_url = base_url.rstrip('/')
        self.token_id = token_id
        self.token_secret = token_secret
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {token_id}:{token_secret}',
            'Accept': 'application/json'
        })

    def _make_request(self, endpoint: str) -> Dict[str, Any]:
        """Make GET request to BookStack API."""
        url = urljoin(f"{self.base_url}/api/", endpoint.lstrip('/'))

        try:
            response = self.session.get(url)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            error_msg = f"BookStack API error: {e}"
            logger.error(error_msg)
            raise BookStackAPIError(error_msg)

    def get_page_by_slug(self, book_slug: str, page_slug: str) -> Dict[str, Any]:
        """
        Get page by book and page slugs.

        Args:
            book_slug: Book slug (e.g. 'jetup-en')
            page_slug: Page slug (e.g. 'option-alienation-agreement')

        Returns:
            Page data dictionary
        """
        # Get book by slug
        book = self._make_request(f'/books/slug/{book_slug}')

        # Get pages of the book
        pages = self._make_request(f'/books/{book["id"]}/pages')

        # Find our page
        for page in pages.get('data', []):
            if page['slug'] == page_slug:
                # Get full page data
                return self._make_request(f'/pages/{page["id"]}')

        raise BookStackAPIError(f"Page {page_slug} not found in book {book_slug}")


class BookStackService:
    """
    Main service for BookStack integration.
    Singleton pattern for resource efficiency.
    """
    _instance = None
    _client = None

    def __new__(cls):
        """Implement singleton pattern."""
        if cls._instance is None:
            cls._instance = super(BookStackService, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize BookStack client if configured."""
        # Get config values
        base_url = Config.get(Config.BOOKSTACK_URL)
        token_id = Config.get(Config.BOOKSTACK_TOKEN_ID)
        token_secret = Config.get(Config.BOOKSTACK_TOKEN_SECRET)

        if not base_url:
            logger.warning("BOOKSTACK_URL not configured")
            return

        if not token_id or not token_secret:
            logger.warning("BookStack auth tokens not configured")
            return

        try:
            self._client = BookStackClient(
                base_url=base_url,
                token_id=token_id,
                token_secret=token_secret
            )
            logger.info(f"BookStack client initialized for {base_url}")
        except Exception as e:
            logger.error(f"Error initializing BookStack client: {e}")

    @property
    def client(self) -> Optional[BookStackClient]:
        """Get BookStack client."""
        if not self._client:
            self._initialize()
        return self._client

    def is_available(self) -> bool:
        """Check if BookStack is available."""
        return self._client is not None

    def get_book_slug(self, project) -> str:
        """
        Get book slug from project's docsFolder field.

        Args:
            project: Project model instance

        Returns:
            Book slug string
        """
        # Check if docsFolder is filled
        if project.docsFolder and project.docsFolder.strip():
            return project.docsFolder.strip()

        # Default format based on language
        return f"jetup-{project.lang}"

    def get_document_html(self, project, doc_slug: str) -> Optional[str]:
        """
        Get HTML document for a project.

        Args:
            project: Project model instance
            doc_slug: Document slug (e.g. 'option-alienation-agreement')

        Returns:
            HTML content or None if not found
        """
        # Create cache key
        cache_key = f"{project.projectID}_{project.lang}_{doc_slug}"

        # Check cache
        cached_html = TemplateCache.get(cache_key)
        if cached_html:
            return cached_html

        # Get book slug
        book_slug = self.get_book_slug(project)
        if not book_slug:
            logger.error(f"Cannot determine book slug for project {project.projectID} lang {project.lang}")
            return None

        # Try to get HTML from public page first (faster)
        try:
            base_url = Config.get(Config.BOOKSTACK_URL)
            url = f"{base_url}/books/{book_slug}/page/{doc_slug}"
            logger.info(f"Fetching document from public URL: {url}")

            response = requests.get(url)
            response.raise_for_status()

            # Parse HTML and extract content
            soup = BeautifulSoup(response.text, 'html.parser')
            content_div = soup.select_one('.page-content')

            if content_div:
                # Remove first H1 if exists (usually duplicate title)
                first_h1 = content_div.find('h1')
                if first_h1:
                    first_h1.decompose()

                html = str(content_div)
                TemplateCache.set(cache_key, html)
                return html

            logger.warning(f"Content block not found in document at {url}")
            return None

        except Exception as e:
            logger.error(f"Error fetching document {doc_slug} for project {project.projectID} directly: {e}")

            # Fallback to API if direct fetch failed
            if self.is_available():
                try:
                    page = self.client.get_page_by_slug(book_slug, doc_slug)
                    html = page.get('html')
                    if html:
                        TemplateCache.set(cache_key, html)
                        return html
                except BookStackAPIError:
                    logger.warning(f"Document {doc_slug} not found for project {project.projectID} via API")
                except Exception as e2:
                    logger.error(f"Error getting document via API: {e2}")

            return None

    def render_template(self, html: str, context: Dict[str, Any]) -> str:
        """
        Render HTML template with context using Jinja2.

        Args:
            html: HTML template with Jinja2 variables
            context: Dictionary with data for rendering

        Returns:
            Rendered HTML
        """
        try:
            # Create Jinja2 environment
            env = jinja2.Environment(
                loader=jinja2.BaseLoader(),
                autoescape=True,
                undefined=jinja2.make_logging_undefined(
                    logger=logger,
                    base=jinja2.DebugUndefined
                )
            )
            template = env.from_string(html)
            return template.render(**context)
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            return html