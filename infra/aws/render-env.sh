#!/usr/bin/env bash
# Render the box's .env from SSM Parameter Store (08 section 9, R10).
# Template values from .env.prod.example, overridden by /swip/prod/* SecureStrings.
# Writes mode 0600 and never prints a value.
set -euo pipefail
umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEMPLATE="$ROOT/.env.prod.example"
OUT="$ROOT/.env"
TMP="$(mktemp "$ROOT/.env.XXXXXX")"
trap 'rm -f "$TMP" "$TMP.ssm"' EXIT

# Region from the environment, else the template's AWS_REGION (the first render
# runs before any .env exists).
REGION="${AWS_REGION:-$(grep -m1 '^AWS_REGION=' "$TEMPLATE" | cut -d= -f2)}"

aws ssm get-parameters-by-path --region "$REGION" --path /swip/prod/ --with-decryption --recursive \
  --query 'Parameters[].[Name,Value]' --output json \
  | jq -r '.[] | "\(.[0] | split("/") | last)=\(.[1])"' > "$TMP.ssm"

# Template first, minus keys SSM overrides; then SSM.
keys="$(cut -d= -f1 "$TMP.ssm")"
grep -vE '^\s*(#|$)' "$TEMPLATE" | while IFS= read -r line; do
  k="${line%%=*}"
  grep -qxF "$k" <<<"$keys" || printf '%s\n' "$line"
done > "$TMP"
cat "$TMP.ssm" >> "$TMP"

# Host-side tools (alembic, make data) reach Postgres on loopback.
if ! grep -q '^DATABASE_URL=' "$TMP"; then
  pw="$(grep '^POSTGRES_PASSWORD=' "$TMP" | head -1 | cut -d= -f2-)"
  {
    printf 'DATABASE_URL=postgresql+asyncpg://postgres:%s@localhost:5432/latam_app\n' "$pw"
    printf 'GOLDEN_DATABASE_URL=postgresql+asyncpg://postgres:%s@localhost:5432/latam_golden\n' "$pw"
  } >> "$TMP"
fi

chmod 600 "$TMP"
mv "$TMP" "$OUT"
echo "rendered .env ($(wc -l < "$OUT") lines, mode 0600)"
