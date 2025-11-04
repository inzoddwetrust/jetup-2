#!/usr/bin/env python3
"""
Template Verification Service

Verifies that all templates used in code:
1. Exist in Google Sheets
2. Have complete language coverage
3. Have valid callback handlers (optional check)

Can run standalone or integrated at bot startup.

Usage:
    # Standalone
    python -m core.template_verifier

    # From code
    from core.template_verifier import TemplateVerifier
    verifier = TemplateVerifier()
    await verifier.verify()
"""

import os
import re
import asyncio
import logging
from typing import Dict, Set, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class Severity(Enum):
    """Issue severity levels."""
    CRITICAL = "CRITICAL"  # Missing templates - breaks functionality
    WARNING = "WARNING"    # Incomplete coverage, unused templates
    INFO = "INFO"          # Hanging callbacks (non-critical, triggers fallback)


@dataclass
class Issue:
    """Represents a verification issue."""
    severity: Severity
    category: str
    message: str
    details: Optional[str] = None


@dataclass
class VerificationReport:
    """Verification results."""
    issues: List[Issue] = field(default_factory=list)
    templates_in_sheets: int = 0
    templates_in_code: int = 0
    languages_checked: List[str] = field(default_factory=list)

    def add_issue(self, severity: Severity, category: str, message: str, details: Optional[str] = None):
        """Add an issue to the report."""
        self.issues.append(Issue(severity, category, message, details))

    def has_critical_issues(self) -> bool:
        """Check if report contains critical issues."""
        return any(issue.severity == Severity.CRITICAL for issue in self.issues)

    def get_issues_by_severity(self, severity: Severity) -> List[Issue]:
        """Get all issues of a specific severity."""
        return [issue for issue in self.issues if issue.severity == severity]


class TemplateVerifier:
    """
    Template verification service.

    Checks loaded templates for:
    - Missing templates (used in code but not in sheets)
    - Unused templates (in sheets but not used in code)
    - Incomplete language coverage
    - Hanging callbacks (optional)
    """

    # Templates referenced in code (from previous analysis)
    CODE_TEMPLATES = {
        # Dashboard & Main Screens
        '/dashboard/existingUser',
        '/dashboard/newUser',
        '/dashboard/noSubscribe',
        '/dashboard/emailverif',
        '/dashboard/emailverif_invalid',
        '/dashboard/emailverif_already',
        '/dashboard/oldemailverif',
        '/dashboard/oldemailverif_invalid',
        '/dashboard/oldemailverif_already',
        'eula_screen',
        'channel_missing',
        'pending_invoice_details',
        '/fallback',

        # Payment Flow
        'add_balance_step1',
        'add_balance_custom',
        'add_balance_currency',
        'add_balance_confirm',
        'add_balance_amount_error',
        'add_balance_rate_error',
        'add_balance_creation_error',
        'add_balance_enter_txid',
        'txid_payment_not_found',
        'txid_already_used',
        'txid_success',
        'txid_success_no_notify',
        'txid_save_error',
        'txid_error',
        'pending_invoices_list',
        'pending_invoices_empty',
        'paid_invoices_list',
        'paid_invoices_empty',
        'invoice_warning',
        'invoice_expired',

        # User Data Collection
        'user_data_firstname',
        'user_data_save_error',
        'user_data_saved_email_sent',
        'user_data_saved_two_emails_sent',
        'user_data_saved_email_failed',
        'user_data_cancelled',
        'email_resend_failed',
        'email_resend_cooldown',
        'email_resend_success',
        'user_data_old_email_request',
        'user_data_old_email_error',
        'user_data_old_email_same',

        # Email Templates
        'email_verification_subject',
        'email_verification_body',

        # Transfer/Balance
        'transfer_active_enter_user_id',
        'transfer_passive_select_recipient',
        'transfer_passive_self_enter_amount',
        'transfer_passive_enter_user_id',
        'transfer_confirm',
        'transfer_success',
        'transfer_error',
        'active_balance',
        'passive_balance',

        # Settings & Preferences
        'settings_main',
        'settings_unfilled_data',
        'settings_filled_unconfirmed',
        'settings_language',

        # Projects & Investments
        '/projects',
        '/projects/notFound',
        '/projects/details',
        '/projects/details/notFound',
        '/projects/invest',
        '/projects/invest/buttons',
        '/projects/invest/buttonBack',
        '/projects/invest/child_project',
        '/projects/invest/noOptions',
        '/projects/invest/purchaseStart',
        '/projects/invest/insufficientFunds',
        '/projects/invest/purchseSuccess',  # Note: typo in original code

        # Portfolio
        '/case',
        '/case/purchases',
        '/case/purchases/empty',
        '/case/certs',
        '/case/certs/empty',
        '/case/strategies',
        'portfolio_value_manual',
        'portfolio_value_info',
        'portfolio_value_back',

        # Team & Referrals
        '/team',
        '/team/referal/info',
        '/team/referal/card',
        '/team/marketing',
        '/team/stats',
        'under_development',

        # Help
        '/help',
        '/help/contacts',
        '/help/social',

        # Finances
        '/finances',
        'csv_generating',
        'csv_error',
        'csv_ready',

        # CSV/Reports
        '/download/csv/report_generating',
        '/download/csv/report_error',
        '/download/csv/report_ready',
        'report_generation_error',
    }

    def __init__(self, required_languages: Optional[List[str]] = None):
        """
        Initialize verifier.

        Args:
            required_languages: List of required language codes (e.g., ['ru', 'en', 'de'])
                               If None, will try to load from Config.TEMPLATE_LANGUAGES or use default
        """
        self.required_languages = required_languages or self._get_required_languages()

    def _get_required_languages(self) -> List[str]:
        """Get required languages from config or use default."""
        try:
            from config import Config

            # Try to get from config
            languages_str = Config.get('TEMPLATE_LANGUAGES', 'ru,en,de')
            languages = [lang.strip() for lang in languages_str.split(',') if lang.strip()]

            if languages:
                logger.info(f"Using template languages from config: {languages}")
                return languages

        except Exception as e:
            logger.warning(f"Failed to load languages from config: {e}")

        # Default fallback
        default_languages = ['ru', 'en', 'de']
        logger.info(f"Using default template languages: {default_languages}")
        return default_languages

    async def verify(self, templates_cache: Optional[Dict] = None) -> VerificationReport:
        """
        Verify templates.

        Args:
            templates_cache: Template cache from MessageTemplates._cache
                            If None, will try to load from MessageTemplates

        Returns:
            VerificationReport with all issues found
        """
        report = VerificationReport(languages_checked=self.required_languages)

        # Get templates cache
        if templates_cache is None:
            try:
                from core.templates import MessageTemplates

                # Load templates if not already loaded
                if not MessageTemplates._cache:
                    logger.info("Templates not loaded, loading now...")
                    await MessageTemplates.load_templates()

                templates_cache = MessageTemplates._cache

            except Exception as e:
                report.add_issue(
                    Severity.CRITICAL,
                    "initialization",
                    f"Failed to load templates: {e}"
                )
                return report

        # Parse templates from cache
        sheet_templates = self._parse_cache(templates_cache)

        # Update report stats
        report.templates_in_sheets = len(sheet_templates)
        report.templates_in_code = len(self.CODE_TEMPLATES)

        # Run checks
        self._check_missing_templates(sheet_templates, report)
        self._check_unused_templates(sheet_templates, report)
        self._check_language_coverage(sheet_templates, report)
        self._check_callback_handlers(templates_cache, report)

        return report

    def _parse_cache(self, cache: Dict) -> Dict[str, Set[str]]:
        """
        Parse template cache to get stateKey -> languages mapping.

        Args:
            cache: MessageTemplates._cache (Dict[(stateKey, lang)] -> template_dict)

        Returns:
            Dict[stateKey] -> Set[languages]
        """
        templates = defaultdict(set)

        for (state_key, lang), template_data in cache.items():
            if state_key and lang:
                templates[state_key].add(lang)

        return dict(templates)

    def _check_missing_templates(self, sheet_templates: Dict[str, Set[str]], report: VerificationReport):
        """Check for templates used in code but missing from sheets."""
        missing = self.CODE_TEMPLATES - set(sheet_templates.keys())

        if missing:
            for template in sorted(missing):
                report.add_issue(
                    Severity.CRITICAL,
                    "missing_template",
                    f"Template '{template}' used in code but not found in sheets",
                    f"Required languages: {', '.join(self.required_languages)}"
                )

    def _check_unused_templates(self, sheet_templates: Dict[str, Set[str]], report: VerificationReport):
        """Check for templates in sheets but not used in code."""
        unused = set(sheet_templates.keys()) - self.CODE_TEMPLATES

        if unused:
            report.add_issue(
                Severity.WARNING,
                "unused_templates",
                f"Found {len(unused)} templates in sheets that are not used in code",
                f"Templates: {', '.join(sorted(unused)[:10])}{'...' if len(unused) > 10 else ''}"
            )

    def _check_language_coverage(self, sheet_templates: Dict[str, Set[str]], report: VerificationReport):
        """Check for incomplete language coverage."""
        required_langs = set(self.required_languages)

        for state_key, available_langs in sorted(sheet_templates.items()):
            missing_langs = required_langs - available_langs

            if missing_langs:
                report.add_issue(
                    Severity.WARNING,
                    "incomplete_language",
                    f"Template '{state_key}' missing languages: {', '.join(sorted(missing_langs))}",
                    f"Has: {', '.join(sorted(available_langs))}"
                )

    def _check_callback_handlers(self, cache: Dict, report: VerificationReport):
        """
        Check for callbacks in templates that may not have handlers.

        Note: This is INFO level only, as hanging callbacks trigger the fallback handler
        which is expected behavior for "under development" features.
        """
        # Extract all callbacks from templates
        callbacks = self._extract_callbacks(cache)

        # Known callback patterns (from handler analysis)
        known_patterns = {
            # Direct matches
            '/team', '/help', '/help/contacts', '/help/social',
            '/finances', '/case', '/case/purchases', '/case/certs', '/case/strategies',
            '/projects', '/dashboard', '/settings',
            '/check/subscription', '/acceptEula',

            # Prefix patterns (simplified - just track the prefix)
            'amount_', 'currency_', 'confirm_', 'pending_invoice_', 'paid_invoice_',
            'move_', 'invest_', 'download_pdf_', 'purchase_', 'cert_',
            'referal_', 'active_balance', 'passive_balance',
            'transfer_', 'lang_', 'resend_email', 'change_email',
        }

        # Check each callback
        unhandled = []
        for callback in callbacks:
            # Check if callback matches any known pattern
            is_handled = False

            # Direct match
            if callback in known_patterns:
                is_handled = True
            else:
                # Prefix match
                for pattern in known_patterns:
                    if pattern.endswith('_') and callback.startswith(pattern):
                        is_handled = True
                        break

            if not is_handled:
                unhandled.append(callback)

        if unhandled:
            report.add_issue(
                Severity.INFO,
                "unhandled_callbacks",
                f"Found {len(unhandled)} callbacks that may not have handlers (will trigger fallback)",
                f"Callbacks: {', '.join(sorted(unhandled)[:10])}{'...' if len(unhandled) > 10 else ''}"
            )

    def _extract_callbacks(self, cache: Dict) -> Set[str]:
        """
        Extract all callback_data from template buttons.

        Args:
            cache: MessageTemplates._cache

        Returns:
            Set of callback_data strings
        """
        callbacks = set()

        for (state_key, lang), template_data in cache.items():
            buttons_str = template_data.get('buttons', '')

            if not buttons_str:
                continue

            # Parse button format: "callback_data:Button Text" or "|url|...:Text"
            for line in buttons_str.split('\n'):
                line = line.strip()
                if not line:
                    continue

                # Split by semicolon for multiple buttons per line
                for button in line.split(';'):
                    button = button.strip()
                    if not button:
                        continue

                    # Skip URL and WebApp buttons
                    if button.startswith('|url|') or button.startswith('|webapp|') or button.startswith('|rgroup:'):
                        continue

                    # Extract callback_data (before the colon)
                    if ':' in button:
                        callback_data = button.split(':', 1)[0].strip()
                        if callback_data:
                            callbacks.add(callback_data)

        return callbacks

    def print_report(self, report: VerificationReport):
        """
        Print verification report to console with color coding.

        Args:
            report: VerificationReport to print
        """
        # ANSI color codes
        RESET = '\033[0m'
        BOLD = '\033[1m'
        RED = '\033[91m'
        YELLOW = '\033[93m'
        GREEN = '\033[92m'
        BLUE = '\033[94m'
        CYAN = '\033[96m'

        # Header
        print()
        print("=" * 80)
        print(f"{BOLD}{CYAN}TEMPLATE VERIFICATION REPORT{RESET}")
        print("=" * 80)
        print()

        # Summary
        print(f"{BOLD}Summary:{RESET}")
        print(f"  Templates in sheets:  {report.templates_in_sheets}")
        print(f"  Templates in code:    {report.templates_in_code}")
        print(f"  Languages checked:    {', '.join(report.languages_checked)}")
        print(f"  Total issues:         {len(report.issues)}")
        print()

        if not report.issues:
            print(f"{GREEN}{BOLD}✓ All checks passed! No issues found.{RESET}")
            print()
            return

        # Group issues by severity
        critical = report.get_issues_by_severity(Severity.CRITICAL)
        warnings = report.get_issues_by_severity(Severity.WARNING)
        info = report.get_issues_by_severity(Severity.INFO)

        # Print critical issues
        if critical:
            print("=" * 80)
            print(f"{RED}{BOLD}CRITICAL ISSUES ({len(critical)}){RESET}")
            print("=" * 80)
            print()

            for issue in critical:
                print(f"{RED}✗ [{issue.category}] {issue.message}{RESET}")
                if issue.details:
                    print(f"  {issue.details}")
                print()

        # Print warnings
        if warnings:
            print("=" * 80)
            print(f"{YELLOW}{BOLD}WARNINGS ({len(warnings)}){RESET}")
            print("=" * 80)
            print()

            for issue in warnings:
                print(f"{YELLOW}⚠ [{issue.category}] {issue.message}{RESET}")
                if issue.details:
                    print(f"  {issue.details}")
                print()

        # Print info
        if info:
            print("=" * 80)
            print(f"{BLUE}{BOLD}INFO ({len(info)}){RESET}")
            print("=" * 80)
            print()

            for issue in info:
                print(f"{BLUE}ℹ [{issue.category}] {issue.message}{RESET}")
                if issue.details:
                    print(f"  {issue.details}")
                print()

        # Recommendations
        print("=" * 80)
        print(f"{BOLD}Recommendations:{RESET}")
        print("=" * 80)
        print()

        if critical:
            print(f"{RED}1. Fix CRITICAL issues immediately - missing templates will break functionality{RESET}")

        if warnings:
            print(f"{YELLOW}2. Review WARNINGS - incomplete language coverage affects UX{RESET}")

        if info:
            print(f"{BLUE}3. INFO items are non-critical - unhandled callbacks trigger fallback (expected){RESET}")

        print()


async def main():
    """Standalone execution."""
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize config
    try:
        from config import Config
        Config.initialize_from_env()
    except Exception as e:
        logger.error(f"Failed to initialize config: {e}")
        return

    # Run verification
    verifier = TemplateVerifier()
    report = await verifier.verify()

    # Print report
    verifier.print_report(report)

    # Exit with error code if critical issues found
    if report.has_critical_issues():
        exit(1)


if __name__ == '__main__':
    asyncio.run(main())
