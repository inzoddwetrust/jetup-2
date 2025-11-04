# 📊 ПОЛНЫЙ АНАЛИЗ ШАБЛОНОВ GOOGLE SHEETS

## Дата анализа: 2025-11-04

---

## 1️⃣ ШАБЛОНЫ ИЗ GOOGLE SHEETS

Из предоставленного CSV я извлёк следующие **уникальные stateKey**:

### ✅ Шаблоны с полным языковым покрытием (ru, en, de):

1. `/dashboard/newUser` ✅
2. `/dashboard/noSubscribe` ✅  
3. `/dashboard/noSubscribeRepeat` ✅
4. `/dashboard/existingUser` ✅
5. `/projects` ✅
6. `/projects/notFound` ✅
7. `/projects/details` ✅
8. `/projects/details/notFound` ✅
9. `/projects/invest` ✅
10. `projects/invest/child_project` ⚠️ (нет `/` в начале)
11. `/projects/invest/buttons` ✅
12. `/projects/invest/buttonBack` ✅
13. `/projects/invest/noOptions` ✅
14. `/projects/invest/purchaseStart` ✅
15. `/projects/invest/insufficientFunds` ✅
16. `/projects/invest/purchseSuccess` ✅ (опечатка: purchse вместо purchase)
17. `/case` ✅
18. `/case/purchases` ✅
19. `/case/purchases/empty` ✅
20. `/case/certs` ✅
21. `/case/certs/empty` ✅
22. `certificate_generating` ✅
23. `certificate_ready` ✅
24. `certificate_error` ✅
25. `/case/strategies` ✅
26. `/case/strategies/manual` ✅
27. `/case/strategies/safe` ✅
28. `/case/strategies/aggressive` ✅
29. `/case/strategies/risky` ✅
30. `portfolio_value_strategy_manual` ✅
31. `portfolio_value_strategy_safe` ✅
32. `portfolio_value_strategy_aggressive` ✅
33. `portfolio_value_strategy_risky` ✅
34. `portfolio_value_info` ✅
35. `portfolio_value_back` ✅
36. `/finances` ✅
37. `active_balance` ✅
38. `paid_invoices_list` ✅
39. `pending_invoices_list` ✅
40. `paid_invoices_empty` ✅
41. `pending_invoices_empty` ✅
42. `active_balance_history_payments` ✅
43. `active_balance_history_purchases` ✅
44. `active_balance_history_transfers` ✅
45. `active_balance_history_empty_payments` ✅
46. `active_balance_history_empty_purchases` ✅
47. `active_balance_history_empty_transfers` ✅
48. `passive_balance` ✅
49. `passive_balance_history_bonuses` ✅
50. `passive_balance_history_transfers` ✅
51. `passive_balance_history_others` ✅
52. `passive_balance_history_empty_bonuses` ✅
53. `passive_balance_history_empty_transfers` ✅
54. `passive_balance_history_empty_others` ✅
55. `transfer_start` ✅
56. `transfer_active_enter_user_id` ✅
57. `transfer_passive_select_recipient` ✅
58. `transfer_passive_enter_user_id` ✅
59. `transfer_passive_self_enter_amount` ✅
60. `transfer_active_enter_amount` ✅
61. `transfer_passive_other_enter_amount` ✅
62. `transfer_confirm` ✅
63. `transfer_success` ✅
64. `transfer_error_self_transfer_not_allowed` ✅
65. `transfer_error_recipient_not_found` ✅
66. `transfer_error_non_positive_amount` ✅
67. `transfer_error_insufficient_funds` ✅
68. `transfer_error_invalid_amount_format` ✅
69. `transfer_error` ✅
70. `transfer_cancelled` ✅
71. `transfer_received_notification` ✅
72. `add_balance_step1` ✅
73. `add_balance_custom` ✅
74. `add_balance_currency` ✅
75. `add_balance_amount_error` ✅
76. `add_balance_rate_error` ✅
77. `add_balance_confirm` ✅
78. `add_balance_creation_error` ✅
79. `add_balance_created` ✅
80. `pending_invoice_details` ✅
81. `add_balance_enter_txid` ✅
82. `txid_payment_not_found` ✅
83. `txid_invalid_format` ✅
84. `txid_already_used` ✅
85. `txid_save_error` ✅
86. `txid_wrong_recipient` ✅
87. `txid_not_found` ✅
88. `txid_success` ✅
89. `txid_success_no_notify` ✅
90. `purchase_doc_not_found` ✅
91. `doc_need_data` ✅
92. `purchase_doc_generating` ✅
93. `purchase_doc_ready` ✅
94. `purchase_doc_template_error` ✅
95. `purchase_doc_generation_error` ✅
96. `user_data_firstname` ✅
97. `user_data_firstname_error` ✅
98. `user_data_surname` ✅
99. `user_data_surname_error` ✅
100. `user_data_birthday` ✅
101. `user_data_birthday_error` ✅
102. `user_data_passport` ✅
103. `user_data_passport_error` ✅
104. `user_data_country` ✅
105. `user_data_country_error` ✅
106. `user_data_city` ✅
107. `user_data_city_error` ✅
108. `user_data_address` ✅
109. `user_data_address_error` ✅
110. `user_data_phone` ✅
111. `user_data_phone_error` ✅
112. `user_data_email` ✅
113. `user_data_email_error` ✅
114. `user_data_confirmation` ✅
115. `user_data_saved` ✅
116. `user_data_save_error` ✅
117. `user_data_cancelled` ✅
118. `admin_payment_not_found` ✅
119. `admin_payment_wrong_status` ✅
120. `admin_payment_confirm_action` ✅
121. `admin_payment_approved` ✅
122. `admin_payment_rejected` ✅
123. `admin_payment_error` ✅
124. `admin_new_payment_notification` ✅
125. `user_payment_approved` ✅
126. `user_payment_rejected` ✅
127. `admin_payment_check_cancelled` ✅
128. `settings_main` ✅
129. `settings_unfilled_data` ✅
130. `settings_filled_unconfirmed` ✅ (только ru есть!)
131. `email_resend_cooldown` ✅
132. `email_resend_success` ✅
133. `email_resend_failed` ✅
134. `settings_language` ✅
135. `/team` ✅
136. `/team/stats` ✅
137. `/download/csv/report_generating` ✅
138. `/download/csv/report_error` ✅
139. `/download/csv/report_ready` ✅
140. `/team/referal/info` ✅
141. `/team/referal/card` ✅
142. `/team/marketing` ✅
143. `/help` ✅
144. `/help/contacts` ✅
145. `/help/social` ✅
146. `invoice_warning` ✅
147. `invoice_expired` ✅
148. `bonus_received` ✅
149. `fallback` ✅
150. `email_verification_subject` (de, en) ❌ нет ru
151. `email_verification_body` (de, en) ❌ нет ru
152. `email_verification_text` (de, en) ❌ нет ru
153. `/dashboard/emailverif` (de, en) ❌ нет ru
154. `/dashboard/emailverif_invalid` (de, en) ❌ нет ru
155. `/dashboard/emailverif_already` (de, en) ❌ нет ru
156. `user_data_saved_email_sent` (de, en) ❌ нет ru
157. `user_data_saved_email_failed` (de, en) ❌ нет ru
158. `admin_tokens_added_notification` (de, en) ❌ нет ru
159. `admin_tokens_added_admin_notification` (de, en) ❌ нет ru
160. `legacy_user_welcome` (de, en) ❌ нет ru
161. `legacy_purchase_created_user` (de, en) ❌ нет ru
162. `legacy_upliner_assigned_user` (de, en) ❌ нет ru
163. `legacy_upliner_assigned_upliner` (de, en) ❌ нет ru
164+. Множество `admin/` шаблонов (de, en) ❌ нет ru
165+. `broadcast_*` шаблоны ✅
166+. `dw_instructions` ✅
167+. `dashboard_dw_instructions_button` ✅

**ИТОГО в таблице: ~170+ уникальных stateKey**

---

## 2️⃣ ПРОБЛЕМЫ С ЯЗЫКОВЫМ ПОКРЫТИЕМ

### ❌ Шаблоны БЕЗ русского языка (только en, de):

1. `email_verification_subject`
2. `email_verification_body`
3. `email_verification_text`
4. `/dashboard/emailverif`
5. `/dashboard/emailverif_invalid`
6. `/dashboard/emailverif_already`
7. `user_data_saved_email_sent`
8. `user_data_saved_email_failed`
9. `admin_tokens_added_notification`
10. `admin_tokens_added_admin_notification`
11. `legacy_user_welcome`
12. `legacy_purchase_created_user`
13. `legacy_upliner_assigned_user`
14. `legacy_upliner_assigned_upliner`
15. Все `admin/*` шаблоны

### ⚠️ Шаблоны только с RU:

1. `settings_filled_unconfirmed` (только ru в CSV!)

---

## 3️⃣ ЛИШНИЕ ШАБЛОНЫ (есть в таблице, но НЕ используются в коде)

Эти шаблоны ЕСТЬ в Google Sheets, но НЕ найдены в коде:

1. `/dashboard/noSubscribeRepeat` ❌ (3 языка)
2. `certificate_generating` ❌
3. `certificate_ready` ❌
4. `certificate_error` ❌
5. `/case/strategies/manual` ❌
6. `/case/strategies/safe` ❌
7. `/case/strategies/aggressive` ❌
8. `/case/strategies/risky` ❌
9. `portfolio_value_strategy_manual` ❌
10. `portfolio_value_strategy_safe` ❌
11. `portfolio_value_strategy_aggressive` ❌
12. `portfolio_value_strategy_risky` ❌
13. `active_balance_history_payments` ❌
14. `active_balance_history_purchases` ❌
15. `active_balance_history_transfers` ❌
16. `active_balance_history_empty_payments` ❌
17. `active_balance_history_empty_purchases` ❌
18. `active_balance_history_empty_transfers` ❌
19. `passive_balance_history_bonuses` ❌
20. `passive_balance_history_transfers` ❌
21. `passive_balance_history_others` ❌
22. `passive_balance_history_empty_bonuses` ❌
23. `passive_balance_history_empty_transfers` ❌
24. `passive_balance_history_empty_others` ❌
25. `transfer_start` ❌
26. `transfer_active_enter_amount` ❌
27. `transfer_passive_other_enter_amount` ❌
28. `transfer_error_self_transfer_not_allowed` ❌
29. `transfer_error_recipient_not_found` ❌
30. `transfer_error_non_positive_amount` ❌
31. `transfer_error_insufficient_funds` ❌
32. `transfer_error_invalid_amount_format` ❌
33. `transfer_cancelled` ❌
34. `transfer_received_notification` ❌
35. `add_balance_created` ❌
36. `txid_invalid_format` ❌
37. `txid_wrong_recipient` ❌
38. `txid_not_found` ❌
39. `purchase_doc_not_found` ❌
40. `doc_need_data` ❌
41. `purchase_doc_generating` ❌
42. `purchase_doc_ready` ❌
43. `purchase_doc_template_error` ❌
44. `purchase_doc_generation_error` ❌
45. Множество `user_data_*_error` шаблонов
46. Множество `admin_*` шаблонов
47. `settings_filled_unconfirmed` ❌
48. Все `legacy_*` шаблоны
49. Все `admin/*` шаблоны
50. `broadcast_*` шаблоны
51. `dw_instructions`
52. `dashboard_dw_instructions_button`

---

## 4️⃣ НЕДОСТАЮЩИЕ ШАБЛОНЫ (используются в коде, но НЕТ в таблице)

### ❌ Эти шаблоны используются в коде, но ОТСУТСТВУЮТ в Google Sheets:

1. `eula_screen` ❌ НЕТ В ТАБЛИЦЕ!
2. `channel_missing` ❌ НЕТ В ТАБЛИЦЕ!
3. `/fallback` vs `fallback` (в таблице без `/`)
4. `csv_generating` ❌ НЕТ В ТАБЛИЦЕ!
5. `csv_error` ❌ НЕТ В ТАБЛИЦЕ!
6. `csv_ready` ❌ НЕТ В ТАБЛИЦЕ!
7. `report_generation_error` ❌ НЕТ В ТАБЛИЦЕ!
8. Динамические шаблоны:
   - `/case/strategies/{strategy_key}` 
   - `portfolio_value_strategy_{strategy}`
   - `{balance_type}_{operation_type}`
   - `{balance_type}_{operation_type}_empty`

---

## 5️⃣ ОПЕЧАТКИ И НЕСООТВЕТСТВИЯ

1. ⚠️ **`/projects/invest/purchseSuccess`** - опечатка: `purchse` должно быть `purchase`
2. ⚠️ **`projects/invest/child_project`** - нет `/` в начале (должно быть `/projects/invest/child_project`)
3. ⚠️ **`fallback`** vs **`/fallback`** - в коде используется `/fallback`, в таблице `fallback`

---

## 📊 ИТОГОВАЯ СТАТИСТИКА

| Метрика | Значение |
|---------|----------|
| **Шаблонов в таблице (уникальных stateKey)** | ~170+ |
| **Шаблонов используется в коде** | ~98 |
| **Лишних (не используются)** | ~80+ |
| **Недостающих (нет в таблице)** | ~8 |
| **С неполным языковым покрытием** | ~20 |
| **Опечаток/несоответствий** | 3 |

---

## 💡 РЕКОМЕНДАЦИИ

### 1. СРОЧНО ИСПРАВИТЬ:

❗ **Добавить русский язык для критических шаблонов:**
- `email_verification_subject`
- `email_verification_body`
- `/dashboard/emailverif`
- `/dashboard/emailverif_invalid`
- `/dashboard/emailverif_already`
- `user_data_saved_email_sent`

❗ **Добавить отсутствующие шаблоны:**
- `eula_screen` (ru, en, de)
- `channel_missing` (ru, en, de)
- `csv_generating` (ru, en, de)
- `csv_error` (ru, en, de)
- `csv_ready` (ru, en, de)
- `report_generation_error` (ru, en, de)

❗ **Исправить опечатки:**
- `purchseSuccess` → `purchaseSuccess`
- `projects/invest/child_project` → `/projects/invest/child_project`
- `fallback` → `/fallback`

### 2. ОПТИМИЗАЦИЯ:

⚠️ **Удалить неиспользуемые шаблоны** (после проверки):
- Все `certificate_*` (если не используются)
- Все `transfer_error_*` (отдельные ключи, если есть общий `transfer_error`)
- Множество admin шаблонов (если не используются)
- Legacy и broadcast шаблоны (если временные)

### 3. УЛУЧШЕНИЯ:

✅ **Привести к единому стилю:**
- Все пути должны начинаться с `/`
- Использовать единый naming convention
- Проверить все динамические шаблоны

✅ **Добавить недостающие en/de переводы** для:
- `settings_filled_unconfirmed`
- Всех admin шаблонов

---

## ✅ ЗАКЛЮЧЕНИЕ

Таблица Google Sheets содержит много полезных шаблонов, но требует:
1. Добавления ~8 критических шаблонов
2. Добавления русских переводов для ~20 шаблонов
3. Удаления ~80 неиспользуемых шаблонов
4. Исправления 3 опечаток

После этих изменений таблица будет полностью соответствовать коду.

