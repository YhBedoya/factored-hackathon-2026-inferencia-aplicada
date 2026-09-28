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

## Transactions

`transactions/year=2026/month=03/day=30/transactions_20260330.csv` has 2 rows
per customer, referencing each customer's card product(s).

## FX rates

`daily_exchange_rates.csv` (same schema as `data/daily_exchange_rates.csv`):
invented USD/MXN rates for 2026-03-11 and 2026-03-12 (latest), plus the
inverse MXN/USD rate for 2026-03-12.
