TEST FIXTURE

Invented rows only. No customer, card, transaction, name, document, email or
phone number in this directory was copied from the organizers' `data/` bucket
(R10). Every person is `Prueba <N>`, every email ends in `@example.invalid`,
and every card number is `000000000000NNNN` where `NNNN` is the last 4 shown
below.

Same raw CSV schema and layout as `data/` (UTF-8 with BOM, CRLF line endings,
`transactions/year=YYYY/month=MM/day=DD/transactions_YYYYMMDD.csv` hive
partitioning) so `FakeBank` (`app/domains/conversation/tools/fakebank.py`) can
read this fixture and the real `data/` directory the same way.

## Customers

- `CLI-TFMULTI00001` (Mexico, multi-card):
  - `PRD-TFM1CRED0001` - Tarjeta Credito, USD, Active, last4 `6475`,
    limit 5000.00, balance 1234.50, expiry 2027-08-31
  - `PRD-TFM1DEBT0002` - Tarjeta Debito, USD, Active, last4 `1203`
  - `PRD-TFM1DEBT0003` - Tarjeta Debito, USD, **Closed**, last4 `9001`
  - `PRD-TFM1SAVE0004` - Cuenta Ahorro (not a card; excluded from `list_cards`)
- `CLI-TFSINGLE0002` (Colombia, single card):
  - `PRD-TFS2CRED0001` - Tarjeta Credito, COP, Active, last4 `2222`,
    limit 8000000, balance 1234567
- `CLI-TFBLOCKD0003` (Argentina, blocked card):
  - `PRD-TFB3DEBT0001` - Tarjeta Debito, ARS, Blocked, last4 `3333`
- `CLI-TFINACT00004` (Colombia, Medellin, inactive customer):
  - `PRD-TFI4CRED0001` - Tarjeta Credito, COP, Active, last4 `4444`,
    limit 2000000, balance 500000, dpd 0, expiry 2028-01-31
- `CLI-TFPASTD00005` (Argentina, Cordoba, past-due card):
  - `PRD-TFP5CRED0001` - Tarjeta Credito, ARS, Active, last4 `5555`,
    limit 900000.00, balance 123456.50, dpd 30, expiry 2027-05-31
- `CLI-TFDECLN00006` (Colombia, decline explainer, D5-B):
  - `PRD-TFD6CRED0001` - Tarjeta Credito, COP, Active, last4 `6666`,
    limit 3000000, balance 100000, expiry 2027-09-30
- `CLI-TFTXSRC00007` (Mexico, transaction search/explain, D7-B B1):
  - `PRD-TFT7CRED0001` - Tarjeta Credito, USD, Active, last4 `7777`
  - `PRD-TFT7DEBT0002` - Tarjeta Debito, USD, Active, last4 `7778`
- `CLI-TFREPT00008` (Colombia, repeat-complainer priority flag, D7-B B2):
  - `PRD-TFR8CRED0001` - Tarjeta Credito, COP, Active, last4 `8888`
- `CLI-TFAMNT00009` (Argentina, amount-threshold priority flag, D7-B B2):
  - `PRD-TFA9CRED0001` - Tarjeta Credito, ARS, Active, last4 `9999`
- `CLI-TFCRIT00010` (Mexico, open-Critical-complaint priority flag, D7-B B2):
  - `PRD-TFC0CRED0001` - Tarjeta Credito, USD, Active, last4 `1010`

## Transactions

`transactions/year=2026/month=03/day=30/transactions_20260330.csv` has 2 rows
per customer, referencing each customer's card product(s), plus (D4-B) three
more rows for `unrecognized_charge`'s tests:

- `PRD-TFS2CRED0001` (`CLI-TFSINGLE0002`) gains `TXN03` (Pending, empty
  `merchant_name`, `fraud_score` 45.00) and `TXN04` (Declined): 3 non-declined
  candidates (one with `fraud_score` over `disputes.yaml`'s `fraud_score_gt`)
  plus 1 declined (excluded from candidates).
- `PRD-TFP5CRED0001` (`CLI-TFPASTD00005`) gains one Declined row, so its only
  transaction is declined -- the "no candidates" case.
- `PRD-TFD6CRED0001` (`CLI-TFDECLN00006`, D5-B) has 4 Declined rows,
  `TRX-TFD6CRED0001TXN01..04`, one per `policies/decline_codes.yaml` code
  (`51`/`14`/`05`/`54`), merchants `Super Uno`/`Libreria Dos`/`Cine Tres`/
  `Viajes Cuatro`, dated 2026-03-30 09:00/10:00/11:00/12:00 (`54` is the
  newest, and its `self_service` is `true`).

`transactions/year=2026/month=03/day=31/transactions_20260331.csv` (D7-B B1,
2026-03-31 is a Tuesday) adds the rows the search/explain and priority-flag
tests use:

- `CLI-TFTXSRC00007`: `TRX-TFT7CRED0001TXN01` Super Ahorro 352.40 USD
  **Approved** 16:00Z (credit card, `test_tx_search_flow`'s "el cargo de
  Super Ahorro del martes pasado"); `TXN02` Uber 18.50 USD **Pending** 20:00Z
  (same card); `TRX-TFT7DEBT0002TXN01` Mercado Central 75.00 USD
  **Reversed** 14:00Z (debit card, no twin row -- A5).
- `CLI-TFREPT00008`: two Approved rows (120000 and 95000 COP), low
  `fraud_score`, for the repeat-complainer flag test.
- `CLI-TFAMNT00009`: one Approved row, 2500000.00 ARS (above the
  `disputes.yaml` `priority.amount_threshold.ARS` of 1,800,000), low
  `fraud_score`, for the amount-threshold flag test.
- `CLI-TFCRIT00010`: one Approved row, 40.00 USD, low `fraud_score`, for the
  open-Critical-complaint flag test.

## Complaints

`complaints/year=2026/month=03/day=30/complaints_20260330.csv` (D7-B B2) uses
the real `bank.complaints` CSV header. The existing customers (`00001`-
`00006`) get no complaint rows, so they stay unflagged by every priority
check:

- `CLI-TFREPT00008` has one complaint, `status=Closed`,
  `priority=Low`, `is_repeat_complainer=true` -- the repeat-complainer flag
  (A6) fires regardless of that complaint's own status or priority.
- `CLI-TFCRIT00010` has two complaints: `status=In Process`,
  `priority=Critical`, `is_repeat_complainer=false` (this one is "open" per
  `disputes.yaml`'s `priority.open_statuses`, so the open-Critical flag
  fires), and a second `status=Resolved`, `priority=Critical` (not "open",
  so it must not fire the flag on its own -- the "Resolved-only" regression
  case).

## FX rates

`daily_exchange_rates.csv` (same schema as `data/daily_exchange_rates.csv`):
invented USD/MXN rates for 2026-03-11 and 2026-03-12 (latest), plus the
inverse MXN/USD rate for 2026-03-12.
