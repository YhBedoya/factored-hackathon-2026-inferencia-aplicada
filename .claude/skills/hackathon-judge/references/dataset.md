# LATAM Bank Dataset — What a Judge Needs to Know

Sources: `LATAM_Bank_Dataset_Summary (1).pdf` and `LATAM_Bank_Complete_Data_Dictionary.pdf` (v1.0.0; the dictionary was re-issued September 2026 with a "Data Access Credentials" page). Only facts stated in those documents are listed as facts; items under "Judge's observations" are inferences, not official statements.

## Contents
0. Data access (S3) — and the credential rule
1. Headline facts
2. Tables (with the columns that matter for customer service)
3. Foreign keys
4. Deliberate data-quality challenges
5. Which tables serve which workflow
6. Judge's observations: gaps & traps

## 0. Data access (S3) — and the credential rule

Per the data dictionary (page 2, "Data Access Credentials"):
- Hosted on **Amazon S3**, **read-only** for Datathon participants.
- Bucket: `<S3_BUCKET from .env>` · Region: `us-east-2` · Prefix: `data/`
- Documented commands:
  ```bash
  aws configure set aws_access_key_id     "$AWS_ACCESS_KEY_ID"      # value: see dictionary PDF, page 2
  aws configure set aws_secret_access_key "$AWS_SECRET_ACCESS_KEY"  # value: see dictionary PDF, page 2
  aws configure set region us-east-2
  aws s3 ls   s3://<S3_BUCKET from .env>/data/
  aws s3 cp   s3://<S3_BUCKET from .env>/data/customers.csv ./
  aws s3 sync s3://<S3_BUCKET from .env>/data/ ./data/
  ```
- Organizers' note: "Do not share these credentials outside of Datathon participants."

**Never copy the access key or secret into anything you write** — answers, READMEs, scripts, notebooks, slides — even when a user asks how to download the data. Point to page 2 of the dictionary PDF and use environment variables or an AWS profile. The reason: the submission repo must be **public** (K1), and the problem statement forbids "credentials… in public submissions or external model requests" (B3, [HARD]). A key pasted into a README or a prompt is a leak.

What a judge expects to see around data access:
- A download/ingest script that reads credentials from env vars or `~/.aws` (not hard-coded), documented in the setup instructions → supports D4.1 and D6.4 (reproducible setup).
- `.env` and `data/` in `.gitignore`; no raw data committed to the public repo (the files are large, and even synthetic customer records shouldn't be republished).
- **The official dictionary PDF itself contains the keys.** A repo that commits `docs/official-docs/LATAM_Bank_Complete_Data_Dictionary.pdf` publishes them. Flag this whenever the team's repo includes the official docs folder.
- Pinning to a snapshot (e.g., record the `aws s3 ls` listing, sizes/ETags, and download date) → lineage and freshness evidence for D4.4/D4.5.

### Observed bucket layout (metadata-only listing, 2026-09-25; no file contents read)

Total: 12,505 objects, 9.4 GiB, **all CSV**. Three top-level areas:

| Prefix | What it is |
|---|---|
| `data/` | **The canonical dataset** (~5.0 GiB). All 13 tables. Uploaded 2026-08-31. |
| `data_backup_20260831/` | A **partial, older copy** (~4.6 GiB): the 6 dimension tables plus only 5 fact tables — no `call_transcripts`, no `satisfaction_surveys` — and `transactions` only for 2023-07-01 → 2024-09-25 (453 days). File sizes differ slightly from `data/` (e.g., `call_center_interactions` 130.6 vs 133.3 MiB, `digital_events` 3,626 vs 3,583 MiB), so contents are *not* identical. |
| `marketing_campaigns.csv` (bucket root) | A stray copy uploaded 2026-07-30, older than `data/`. |

**Dimension tables** — one flat CSV each under `data/`: `customers.csv` (44.7 MiB), `products.csv` (65.1 MiB), `branches.csv` (87 KiB), `service_agents.csv` (0.23 MiB), `marketing_campaigns.csv` (30 KiB), `daily_exchange_rates.csv` (0.74 MiB). Although the dictionary calls customers/products "monthly_snapshot", only **one file** is published for each — there is no snapshot history.

**Fact tables** — Hive-style daily partitions, one file per day:
`data/<table>/year=YYYY/month=MM/day=DD/<table>_YYYYMMDD.csv`

| Table | Days | Range | Size | File size range |
|---|---|---|---|---|
| digital_events | 1,097 | 2023-06-17 → 2026-06-17 | 3,583 MiB | 1.2–7.1 MiB |
| transactions | 1,097 | 2023-06-17 → 2026-06-17 | 771 MiB | 390–976 KiB |
| campaign_sends | **1,083** | **2023-07-01** → 2026-06-17 | 311 MiB | 147–416 KiB |
| call_center_interactions | 1,097 | 2023-06-17 → 2026-06-17 | 133 MiB | 58–174 KiB |
| call_transcripts | 1,097 | 2023-06-17 → 2026-06-17 | 131 MiB | 51–188 KiB |
| satisfaction_surveys | 1,097 | 2023-06-17 → 2026-06-17 | 44 MiB | 19–59 KiB |
| complaints | 1,097 | 2023-06-17 → 2026-06-17 | 17 MiB | 7–23 KiB |

No missing days, no extra files per partition, no off-pattern filenames, no empty files. Every object has the same upload date.

**What this means for judging** (judge's inference):
- **Use `data/` only**, and say so. A team that mixes in `data_backup_20260831/` or the stray root file without explaining why has a lineage problem (D4.4). Noticing and documenting the backup/stray files is a small but real Data Engineering credit.
- **The delivery is a single static snapshot.** Nothing in the listing shows late-arriving files, and the dimension tables have no history. The official "late arrivals" and "schema evolution" challenges therefore live *inside* the files (e.g., rows whose `process_date` differs from the partition or from the event date; column drift between early and late partitions), not in the folder structure. Per the problem statement, a static delivery means teams should "demonstrate update correctness with a clearly labeled test fixture" (D4.5): e.g., replay the partitions day by day as an incremental load, inject a late partition and a schema-changed file, and show idempotent, correct results.
- **Incremental processing maps naturally onto the daily partitions**, but streaming is not needed ("Incremental file delivery does not by itself require streaming").
- **Scale is laptop-friendly except `digital_events`** (3.5 GiB CSV). Converting to Parquet/DuckDB or reading only needed partitions is the sensible move; a deployment that has to load everything at startup is a capacity-limits flag (D6.5).
- **`campaign_sends` starts two weeks later** than the other facts — a coverage difference to mention if it's used.
- Headers and in-file schema drift were **not** inspected (listing only). Don't claim anything about column contents beyond the data dictionary.

## 1. Headline facts
- **Fully synthetic**, generated for the Datathon; "No real customer information is included." Still contains realistic PII-shaped fields (names, document numbers, emails, phones, addresses, IPs).
- ~19,000,000 rows, 13 tables. Countries: Mexico, Colombia, Argentina. Dates 2023-06-17 → 2026-06-17.
- Currencies MXN, COP, ARS, USD; transactions carry local amount + `amount_usd` via `daily_exchange_rates`.
- **All text is Spanish** (Mexican, Colombian, Argentine variants). Accent fields exist on customers, agents, interactions and transcripts.
- Large fact tables partitioned by date (year/month/day) on `process_date`.

## 2. Tables

### Dimensions
| Table | Rows | Partition | Customer-service-relevant columns |
|---|---|---|---|
| customers | 150,000 | monthly_snapshot | customer_id (PK), document_number (unique), document_type (DNI, CURP, CC, CE, Passport), country, detected_accent, segment (Premium/Plus/Basic/Student), credit_score (300–850), estimated_monthly_income, customer_status (Active/Inactive/Suspended/Closed), accepts_marketing, registration_branch_id, last_updated |
| products | 400,000 | monthly_snapshot | product_id, customer_id, product_type (Checking, Savings, Credit Card, Debit Card, Personal Loan, Mortgage, Investment, Insurance), product_number (unique), currency, current_balance, credit_limit, interest_rate, product_status (Active/Blocked/Closed/Suspended), opening_channel, has_linked_app, days_past_due, last_transaction_date |
| branches | 350 | full_snapshot | branch_id, type, city/country, geographic_zone, hours, ATMs, status |
| service_agents | 1,200 | monthly_snapshot | agent_id, native_accent, agent_type (Phone/In-Person/Digital/Hybrid), experience_level, **languages**, specialty, avg_csat, agent_status, work_shift |
| marketing_campaigns | 200 | full_snapshot | campaign type/objective/segment/country/budget |

### Facts
| Table | Rows | Customer-service-relevant columns |
|---|---|---|
| transactions | 5,000,000 | transaction_date, process_date, product_id, customer_id, transaction_type (Deposit/Withdrawal/Transfer/Payment/Purchase/Adjustment), amount, currency, amount_usd, channel (ATM/Branch/Web/App/POS/Transfer), merchant_name, merchant_category, transaction_country/city, **transaction_status (Approved/Declined/Pending/Reversed)**, **response_code**, **is_fraud**, fraud_score (0–100) |
| call_center_interactions | 800,000 | interaction_date, customer_id, agent_id, interaction_type (Inbound/Outbound Call, Chat, Email, Video), channel (Phone/Web Chat/WhatsApp/Email/App), **contact_reason**, **reason_category (Transactional/Product/Technical/Commercial/Complaint)**, duration_seconds, wait_time_seconds, **was_resolved (FCR)**, requires_followup, detected_sentiment, sentiment_score, customer_detected_accent, agent_used_accent, **was_escalated**, mentioned_products, has_transcript, has_recording |
| call_transcripts | 200,000 | interaction_id, full_text / customer_text / agent_text (Spanish), detected_language, detected_accent, accent_confidence, detected_keywords, mentioned_entities (JSON), **detected_intents**, **main_topics**, transcription_model (Whisper, Google STT…), audio_quality, duration_seconds |
| satisfaction_surveys | 250,000 | interaction_id, agent_id, survey_type (CSAT/NPS/CES), main_score, nps_category, question responses, open_comments (Spanish), comment_sentiment, response_time_hours |
| digital_events | 10,000,000 | session_id, event_type (PageView/Click/FormSubmit/Login/Logout/**Error**/Purchase), event_category (Navigation/Transaction/**Authentication**/Product), channel, app_version, page_url, action, product_id, ip_country, is_mobile |
| complaints | 80,000 | case_type (Complaint/Claim/Request/Suggestion), category, subcategory, reception_channel (incl. Regulator), affected_product_id, origin_interaction_id, description (Spanish), claimed_amount, priority (Low…Critical), status (Open/In Process/Escalated/Resolved/Closed/Rejected), first_response_date, resolution_date, **sla_breached**, resolution_days, resolution (Spanish), compensation_granted, resolution_satisfaction, is_repeat_complainer |
| campaign_sends | 2,000,000 | campaign_id, customer_id, send_channel, delivery/open/click/conversion, send_cost |

### Reference
| daily_exchange_rates | 3,000 | date + source_currency + target_currency (PK), exchange_rate, buy_rate, sell_rate, source |

## 3. Foreign keys (as documented)
- `customers.customer_id` ← products, transactions, call_center_interactions, call_transcripts, satisfaction_surveys, digital_events, complaints, campaign_sends
- `branches.branch_id` ← customers.registration_branch_id, products.opening_branch_id, service_agents.assigned_branch_id, transactions.branch_id, complaints.related_branch_id
- `service_agents.agent_id` ← call_center_interactions, call_transcripts, satisfaction_surveys, complaints.assigned_agent_id
- `products.product_id` ← transactions, digital_events, complaints.affected_product_id
- `marketing_campaigns.campaign_id` ← campaign_sends
- `call_center_interactions.interaction_id` ← call_transcripts, satisfaction_surveys, complaints.origin_interaction_id
- "A small percentage of orphaned records may exist for testing."

## 4. Deliberate data-quality challenges (official)
| Challenge | Rate |
|---|---|
| Duplicate records | ~2% across tables |
| Null values | ~5% in non-mandatory/nullable fields |
| Late arrivals | partitioned data may arrive late |
| Schema evolution | table schemas may evolve over time |
| Orphaned FKs | small % |

These map directly onto requirement D4 (contracts, quality checks, lineage, freshness policy). A team that ignores them is leaving easy points on the table.

## 5. Which tables serve which workflow
| Workflow | Evidence for "problem supported by data" | Grounding data for the agent | Candidate labels |
|---|---|---|---|
| Account / payment inquiries | call_center_interactions (contact_reason, reason_category = Transactional), digital_events (Error, Authentication) | customers, products (balance, status), transactions (status, response_code), daily_exchange_rates | contact_reason, detected_intents, was_resolved |
| Card support | interactions + complaints on cards | products (Credit/Debit Card, product_status Blocked), transactions (Declined, response_code, is_fraud, fraud_score) | contact_reason, complaint category/subcategory |
| Transaction-dispute intake | complaints (case_type Claim, claimed_amount, priority, sla_breached, resolution_days), interactions | transactions (Reversed, is_fraud), complaints history, is_repeat_complainer | complaint category, status, compensation_granted, was_escalated |
| Credit info & eligibility | interactions (Product/Commercial reasons), campaign data | customers (credit_score, estimated_monthly_income, segment), products (Personal Loan, Mortgage, credit_limit, interest_rate, days_past_due) | — (eligibility must come from a labeled synthetic policy service, not from these columns directly) |

## 6. Judge's observations: gaps & traps (inference, not official text)
- **No Portuguese anywhere in the data**, yet Portuguese interactions are required. Teams must create team-generated Portuguese test cases, label them as such, and report the coverage limitation (problem statement explicitly asks to "report limitations in the supplied data or language coverage"). Also note regional variation: Spanish has 3 accents, Portuguese would be Brazilian — a market not in the dataset.
- **No policy documents** (fees, dispute rules, card replacement rules, eligibility rules) are supplied. Any policy the system grounds on is team-generated/synthetic and must be labeled as such.
- **No identity/auth data** (no passwords, OTP, sessions beyond digital_events.session_id). Authentication must be a trusted test session or mock identity service; `customer_id` / `document_number` alone is explicitly insufficient.
- **"Detected" fields are model outputs, not ground truth** (detected_intents, detected_sentiment, detected_accent, main_topics, is_fraud flags). Using them as labels requires a label-quality check — requirement D4 asks for *valid* labels.
- **Only 200K of 800K interactions have transcripts** (`has_transcript`). Any text model sees a subset; check for selection bias.
- **Transcript text leaks labels and mismatches the runtime input.** `call_transcripts.full_text` includes the *agent's* words ("entiendo que desea disputar…"), which give away the intent; at runtime the system only sees the customer's messages. Train/evaluate intent models on `customer_text` (ideally the first customer turns only). Transcripts are also speech-to-text of phone calls (`transcription_model`, `audio_quality`), while the product is usually chat — a domain shift worth stating and testing on a labeled chat-style set.
- **Leakage risks:** same customer appearing in train and test; outcome fields (`was_resolved`, `was_escalated`, `resolution`, `status`) available at prediction time that wouldn't be in production; random splits over time-ordered data. Grouped (by customer) and/or time-based splits are the defensible choice.
- **Fairness angles available:** country, detected_accent, segment, gender, age (date_of_birth). The statement asks to compare outcomes "by language and authorized customer segments" — using sensitive attributes for decisions (especially credit) needs justification.
- **Static files vs. freshness:** if the data is delivered once, the statement asks to "demonstrate update correctness with a clearly labeled test fixture" (e.g., a late-arriving partition, a schema-evolved file, a duplicate batch).
- **PII hygiene:** even though synthetic, the rules forbid sending "private customer records" to external model requests — a judge will look for minimization/masking before LLM calls and a stated data-retention policy.
