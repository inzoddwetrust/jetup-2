# sync_system/webhook_handler.py
"""
Webhook handler for exporting data from DB to Google Sheets.
Accepts requests from Google Apps Script and returns JSON data.
"""
import logging
import json
from aiohttp import web
from typing import Dict, Set
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
import ipaddress
from collections import defaultdict
import asyncio

from config import Config
from core.db import get_session
from sync_system.sync_engine import UniversalSyncEngine
from sync_system.sync_config import SUPPORT_TABLES
from models import Notification

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter implementation."""

    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests = defaultdict(list)
        self._cleanup_task = None

    def is_allowed(self, client_id: str) -> bool:
        """Check if request is allowed for given client."""
        now = datetime.now()
        cutoff_time = now - timedelta(seconds=self.time_window)

        self.requests[client_id] = [
            req_time for req_time in self.requests[client_id]
            if req_time > cutoff_time
        ]

        if len(self.requests[client_id]) >= self.max_requests:
            return False

        self.requests[client_id].append(now)
        return True

    async def cleanup_loop(self):
        """Periodic cleanup of old entries."""
        while True:
            await asyncio.sleep(300)
            now = datetime.now()
            cutoff_time = now - timedelta(seconds=self.time_window * 2)

            clients_to_remove = []
            for client_id, timestamps in self.requests.items():
                if all(ts < cutoff_time for ts in timestamps):
                    clients_to_remove.append(client_id)

            for client_id in clients_to_remove:
                del self.requests[client_id]

            if clients_to_remove:
                logger.debug(f"Cleaned up {len(clients_to_remove)} old rate limit entries")


class WebhookHandler:
    """Webhook handler with enhanced security."""

    ALLOWED_IP_RANGES = [
        '34.64.0.0/10',
        '35.184.0.0/13',
        '35.192.0.0/11',
        '35.224.0.0/12',
        '35.240.0.0/13',
        '104.154.0.0/15',
        '104.196.0.0/14',
        '107.167.160.0/19',
        '107.178.192.0/18',
        '108.59.80.0/20',
        '108.170.192.0/18',
        '130.211.0.0/16',
        '146.148.0.0/17',
        '162.216.148.0/22',
        '162.222.176.0/21',
        '173.255.112.0/20',
        '192.158.28.0/22',
        '199.192.112.0/22',
        '199.223.232.0/21',
        '208.68.108.0/22',
        '23.236.48.0/20',
        '23.251.128.0/19',
    ]

    ALLOWED_SPECIFIC_IPS: Set[str] = set()

    def __init__(self, secret_key: str = None):
        self.secret_key = secret_key or Config.get('WEBHOOK_SECRET_KEY')

        if not self.secret_key or self.secret_key == "error":
            logger.critical("WEBHOOK_SECRET_KEY is not properly configured!")
            raise ValueError("WEBHOOK_SECRET_KEY must be set in environment")

        self.app = web.Application()

        rate_limit_requests = Config.get('WEBHOOK_RATE_LIMIT_REQUESTS', 30)
        rate_limit_window = Config.get('WEBHOOK_RATE_LIMIT_WINDOW', 60)

        self.rate_limiter = RateLimiter(
            max_requests=int(rate_limit_requests) if rate_limit_requests else 30,
            time_window=int(rate_limit_window) if rate_limit_window else 60
        )

        self.health_token = Config.get('WEBHOOK_HEALTH_TOKEN')

        self.request_count = 0
        self.error_count = 0
        self.last_request_time = None

        allowed_ips = Config.get('WEBHOOK_ALLOWED_IPS')
        if allowed_ips:
            if isinstance(allowed_ips, str):
                self.ALLOWED_SPECIFIC_IPS.update(allowed_ips.split(','))
            elif isinstance(allowed_ips, list):
                self.ALLOWED_SPECIFIC_IPS.update(allowed_ips)

        self.setup_routes()
        self.setup_middleware()

        asyncio.create_task(self.rate_limiter.cleanup_loop())

    def setup_routes(self):
        """Setup routes."""
        self.app.router.add_post('/sync/export', self.handle_export)
        self.app.router.add_get('/sync/health', self.handle_health)
        self.app.router.add_get('/sync/metrics', self.handle_metrics)
        self.app.router.add_route('*', '/{path:.*}', self.handle_not_found)

    def setup_middleware(self):
        """Setup middleware for request processing."""

        @web.middleware
        async def security_middleware(request, handler):
            client_ip = self.get_client_ip(request)
            logger.info(f"Request from {client_ip}: {request.method} {request.path}")

            if request.path == '/sync/health':
                return await handler(request)

            if not self.is_ip_allowed(client_ip):
                logger.warning(f"Blocked request from unauthorized IP: {client_ip}")
                await self.notify_security_event(f"Blocked unauthorized IP: {client_ip}")
                return web.json_response({'error': 'Forbidden'}, status=403)

            if not self.rate_limiter.is_allowed(client_ip):
                logger.warning(f"Rate limit exceeded for IP: {client_ip}")
                await self.notify_security_event(f"Rate limit exceeded: {client_ip}")
                return web.json_response({'error': 'Too Many Requests'}, status=429)

            try:
                response = await handler(request)
                return response
            except Exception as e:
                logger.error(f"Error processing request: {e}", exc_info=True)
                self.error_count += 1
                return web.json_response({'error': 'Internal Server Error'}, status=500)

        self.app.middlewares.append(security_middleware)

    def get_client_ip(self, request: web.Request) -> str:
        """Get real client IP from request."""
        if 'X-Forwarded-For' in request.headers:
            return request.headers['X-Forwarded-For'].split(',')[0].strip()
        if 'X-Real-IP' in request.headers:
            return request.headers['X-Real-IP']
        return request.remote or '127.0.0.1'

    def is_ip_allowed(self, ip: str) -> bool:
        """Check if IP is allowed."""
        if ip in self.ALLOWED_SPECIFIC_IPS:
            return True
        if ip in ['127.0.0.1', '::1', 'localhost']:
            return True

        try:
            client_ip = ipaddress.ip_address(ip)
            for ip_range in self.ALLOWED_IP_RANGES:
                if client_ip in ipaddress.ip_network(ip_range, strict=False):
                    return True
        except ValueError:
            logger.warning(f"Invalid IP address format: {ip}")

        return False

    def verify_signature(self, data: Dict, signature: str) -> bool:
        """Verify request signature."""
        if not signature:
            return False

        payload = f"{data.get('table', '')}{data.get('timestamp', '')}{data.get('nonce', '')}"
        expected_signature = hmac.new(
            self.secret_key.encode(),
            payload.encode(),
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_signature, signature)

    async def notify_security_event(self, message: str):
        """Send notification about security event."""
        try:
            admin_ids = Config.get(Config.ADMIN_USER_IDS, [])
            if not admin_ids:
                return

            session = get_session()
            try:
                for admin_id in admin_ids[:3]:
                    notification = Notification(
                        userID=admin_id,
                        notificationType='security',
                        messageText=f"🔒 Security Alert:\n{message}",
                        status='pending'
                    )
                    session.add(notification)
                session.commit()
            finally:
                session.close()
        except Exception as e:
            logger.error(f"Failed to create security notification: {e}")

    async def handle_not_found(self, request: web.Request) -> web.Response:
        """Handle undefined routes."""
        return web.json_response({'error': 'Not Found'}, status=404)

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        token = request.headers.get('X-Health-Token')
        if self.health_token and token != self.health_token:
            return web.json_response({'status': 'ok'})

        return web.json_response({
            'status': 'ok',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime': (datetime.now() - self.start_time).total_seconds() if hasattr(self, 'start_time') else 0
        })

    async def handle_metrics(self, request: web.Request) -> web.Response:
        """Metrics endpoint."""
        return web.json_response({
            'requests_total': self.request_count,
            'errors_total': self.error_count,
            'last_request': self.last_request_time.isoformat() if self.last_request_time else None,
            'uptime_seconds': (datetime.now() - self.start_time).total_seconds() if hasattr(self, 'start_time') else 0
        })

    async def handle_export(self, request: web.Request) -> web.Response:
        """Handle export request."""
        self.request_count += 1
        self.last_request_time = datetime.now()
        client_ip = self.get_client_ip(request)

        try:
            body = await request.read()

            if len(body) > 1024 * 100:
                logger.warning(f"Request body too large from {client_ip}: {len(body)} bytes")
                return web.json_response({'error': 'Request too large'}, status=413)

            try:
                data = json.loads(body)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON from {client_ip}: {e}")
                return web.json_response({'error': 'Invalid JSON'}, status=400)

            # Check timestamp
            if 'timestamp' in data:
                try:
                    timestamp_str = data['timestamp']
                    if timestamp_str.endswith('Z'):
                        request_time = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    elif '+' in timestamp_str:
                        request_time = datetime.fromisoformat(timestamp_str)
                    else:
                        request_time = datetime.fromisoformat(timestamp_str)
                        if request_time.tzinfo is None:
                            request_time = request_time.replace(tzinfo=timezone.utc)

                    current_time = datetime.now(timezone.utc)
                    time_diff = abs((current_time - request_time).total_seconds())

                    if time_diff > 300:
                        logger.warning(f"Request timestamp too old from {client_ip}: {time_diff} seconds")
                        return web.json_response({'error': 'Request expired'}, status=400)
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid timestamp format from {client_ip}: {e}")
                    return web.json_response({'error': 'Invalid timestamp'}, status=400)

            # Verify signature
            signature = data.get('signature', '')
            if not self.verify_signature(data, signature):
                logger.warning(f"Invalid signature from {client_ip}")
                await self.notify_security_event(f"Invalid webhook signature from {client_ip}")
                return web.json_response({'error': 'Invalid signature'}, status=401)

            # Validate table name
            table_name = data.get('table')
            if not table_name:
                return web.json_response({'error': 'Table name required'}, status=400)

            if not table_name.replace('_', '').isalnum():
                logger.warning(f"Invalid table name format from {client_ip}: {table_name}")
                return web.json_response({'error': 'Invalid table name format'}, status=400)

            if table_name not in SUPPORT_TABLES:
                logger.warning(f"Unauthorized table access attempt from {client_ip}: {table_name}")
                await self.notify_security_event(f"Unauthorized table access: {table_name}")
                return web.json_response({'error': f'Table {table_name} not allowed'}, status=403)

            # Export data
            logger.info(f"Export request for table {table_name} from {client_ip}")

            session = get_session()
            try:
                engine = UniversalSyncEngine(table_name)
                result = engine.export_to_json(session)
            finally:
                session.close()

            if result['success']:
                logger.info(f"Successfully exported {result['count']} records from {table_name}")
                return web.json_response(result)
            else:
                logger.error(f"Export failed for {table_name}: {result.get('error')}")
                self.error_count += 1
                return web.json_response({'error': result.get('error', 'Export failed')}, status=500)

        except Exception as e:
            logger.error(f"Webhook error: {e}", exc_info=True)
            self.error_count += 1
            await self.notify_security_event(f"Webhook error from {client_ip}: {str(e)}")
            return web.json_response({'error': 'Internal server error'}, status=500)

    async def start(self, host: str = '127.0.0.1', port: int = 8080):
        """Start webhook server."""
        self.start_time = datetime.now()

        webhook_host = Config.get('WEBHOOK_HOST')
        if webhook_host:
            host = webhook_host

        if host == '0.0.0.0':
            logger.warning("⚠️ Webhook server listening on all interfaces!")

        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()

        logger.info(f"🔒 Secure webhook server started on {host}:{port}")
        return runner


async def start_webhook_server():
    """Start webhook server for sync."""
    try:
        handler = WebhookHandler()

        host = Config.get('WEBHOOK_HOST', '127.0.0.1')
        port = Config.get('WEBHOOK_PORT', 8080)

        runner = await handler.start(
            host=host,
            port=int(port) if port else 8080
        )
        return runner
    except ValueError as e:
        logger.critical(f"Failed to start webhook server: {e}")
        raise
    except Exception as e:
        logger.critical(f"Unexpected error starting webhook server: {e}", exc_info=True)
        raise