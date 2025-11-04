#!/usr/bin/env python3
"""
Анализ шаблонов Google Sheets
Сравнение с использованием в коде
"""

import csv
import io
from collections import defaultdict

# CSV данные из Google Sheets (вставлены пользователем)
CSV_DATA = """#,stateKey,lang,text,buttons,parseMode,disablePreview,mediaType,mediaID,
1,/dashboard/newUser,ru,"👋 <b>Здравствуйте, {firstname}!</b>

Прежде чем начать, пожалуйста, ознакомьтесь с <b>правилами платформы</b>:

После этого нажмите <b>«Я принимаю»</b>, чтобы продолжить.
","|webapp|library.jetup.info/books/doc-ru:Изучить правила 📖
/acceptEula:Я принимаю правила ✅
lang_en:🇬🇧; lang_de:🇩🇪; lang_ru:🇷🇺;",HTML,1,picture,AgACAgIAAxkBAAIhZGgQ1VwKtYAtxmICU3CLp4znSTkqAAL27zEb-CGJSNMRqsirJpwIAQADAgADeQADNgQ,
1,/dashboard/newUser,en,"👋 <b>Hello, {firstname}!</b>

Before we get started, please read the <b>platform rules</b>:

Then tap <b>"I accept"</b> to continue.
","|webapp|library.jetup.info/books/doc-en:Learn the rules 🔎
/acceptEula:I accept the rules ✅
lang_en:🇬🇧; lang_de:🇩🇪; lang_ru:🇷🇺;",HTML,1,picture,AgACAgIAAxkBAAIhZGgQ1VwKtYAtxmICU3CLp4znSTkqAAL27zEb-CGJSNMRqsirJpwIAQADAgADeQADNgQ,
1,/dashboard/newUser,de,"👋 <b>Hallo, {firstname}!</b>

Bevor wir starten, lies bitte die <b>Plattform-Regeln</b>:

Tippe anschließend auf <b>„Ich akzeptiere"</b>, um fortzufahren.","|webapp|library.jetup.info/books/doc-de:Lerne die Regeln 🔎
/acceptEula:Ich akzeptiere die Regeln ✅
lang_en:🇬🇧; lang_de:🇩🇪; lang_ru:🇷🇺;",HTML,1,picture,AgACAgIAAxkBAAIhZGgQ1VwKtYAtxmICU3CLp4znSTkqAAL27zEb-CGJSNMRqsirJpwIAQADAgADeQADNgQ,"""

# Шаблоны, найденные в коде (из предыдущего анализа)
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

def parse_csv_data(csv_text):
    """Парсинг CSV данных"""
    templates = defaultdict(set)  # stateKey -> set of languages
    all_templates = []

    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        state_key = row.get('stateKey', '').strip()
        lang = row.get('lang', '').strip()

        if state_key and lang:
            templates[state_key].add(lang)
            all_templates.append({'stateKey': state_key, 'lang': lang, 'row': row})

    return templates, all_templates

def analyze_templates():
    """Основной анализ"""
    print("=" * 80)
    print("АНАЛИЗ ШАБЛОНОВ GOOGLE SHEETS")
    print("=" * 80)
    print()

    # Парсим CSV
    sheet_templates, all_rows = parse_csv_data(CSV_DATA)

    print(f"📊 Всего уникальных stateKey в таблице: {len(sheet_templates)}")
    print(f"📊 Всего шаблонов используется в коде: {len(CODE_TEMPLATES)}")
    print()

    # 1. Проверка языкового покрытия
    print("=" * 80)
    print("1️⃣ ПРОВЕРКА ЯЗЫКОВОГО ПОКРЫТИЯ (должно быть: ru, en, de)")
    print("=" * 80)
    print()

    missing_languages = []
    for state_key, languages in sorted(sheet_templates.items()):
        expected = {'ru', 'en', 'de'}
        missing = expected - languages
        if missing:
            missing_languages.append({
                'stateKey': state_key,
                'has': sorted(languages),
                'missing': sorted(missing)
            })

    if missing_languages:
        print(f"❌ Найдено {len(missing_languages)} шаблонов с неполным языковым покрытием:")
        print()
        for item in missing_languages:
            print(f"  • {item['stateKey']}")
            print(f"    Есть: {', '.join(item['has'])}")
            print(f"    Нет: {', '.join(item['missing'])}")
            print()
    else:
        print("✅ Все шаблоны имеют полное языковое покрытие (ru, en, de)")

    print()

    # 2. Лишние шаблоны (есть в таблице, но НЕ используются в коде)
    print("=" * 80)
    print("2️⃣ ЛИШНИЕ ШАБЛОНЫ (есть в таблице, но не используются в коде)")
    print("=" * 80)
    print()

    unused_templates = set(sheet_templates.keys()) - CODE_TEMPLATES
    if unused_templates:
        print(f"⚠️ Найдено {len(unused_templates)} неиспользуемых шаблонов:")
        print()
        for template in sorted(unused_templates):
            languages = sorted(sheet_templates[template])
            print(f"  • {template} ({', '.join(languages)})")
    else:
        print("✅ Все шаблоны из таблицы используются в коде")

    print()

    # 3. Недостающие шаблоны (используются в коде, но НЕТ в таблице)
    print("=" * 80)
    print("3️⃣ НЕДОСТАЮЩИЕ ШАБЛОНЫ (используются в коде, но нет в таблице)")
    print("=" * 80)
    print()

    missing_templates = CODE_TEMPLATES - set(sheet_templates.keys())
    if missing_templates:
        print(f"❌ Найдено {len(missing_templates)} отсутствующих шаблонов:")
        print()
        for template in sorted(missing_templates):
            print(f"  • {template} (нужны: ru, en, de)")
    else:
        print("✅ Все шаблоны из кода присутствуют в таблице")

    print()

    # 4. Итоговая статистика
    print("=" * 80)
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 80)
    print()
    print(f"Шаблонов в таблице:       {len(sheet_templates)}")
    print(f"Шаблонов в коде:          {len(CODE_TEMPLATES)}")
    print(f"Лишних шаблонов:          {len(unused_templates)}")
    print(f"Недостающих шаблонов:     {len(missing_templates)}")
    print(f"Неполное языковое покр.:  {len(missing_languages)}")
    print()

    # 5. Рекомендации
    print("=" * 80)
    print("💡 РЕКОМЕНДАЦИИ")
    print("=" * 80)
    print()

    if missing_templates:
        print("1. Добавьте недостающие шаблоны в Google Sheets (см. раздел 3)")

    if unused_templates:
        print("2. Удалите неиспользуемые шаблоны из Google Sheets (см. раздел 2)")
        print("   Или убедитесь, что они действительно не нужны")

    if missing_languages:
        print("3. Дополните шаблоны недостающими языками (см. раздел 1)")

    if not (missing_templates or unused_templates or missing_languages):
        print("✅ Всё отлично! Таблица полностью соответствует коду.")

if __name__ == '__main__':
    analyze_templates()
