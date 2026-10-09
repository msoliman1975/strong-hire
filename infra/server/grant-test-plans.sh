#!/usr/bin/env bash
# Test server only (docs/hosting.md): give a free test subscription to the owner and to the first
# TEST_PLAN_SLOTS other people who sign up. Stripe is not set up, so these rows stand in for a paid
# plan: status active, TEST_PLAN_MINUTES minutes, one year. They are marked with
# stripe_customer_id "test-plan:<user id>", so they are easy to find and remove.
# Left out: the sim candidate (SIM_EMAIL), and emails at getstronghire.com or example.com.
# Safe to run more than once; cron runs it every 5 minutes (/etc/cron.d/stronghire-test-plans).
set -euo pipefail
cd "$(dirname "$0")/../.."
env_value() { grep -E "^$1=" .env | tail -1 | cut -d= -f2- | tr -d '"' || true; }

OWNER="$(env_value TEST_PLAN_OWNER)"
SLOTS="$(env_value TEST_PLAN_SLOTS)"
MINUTES="$(env_value TEST_PLAN_MINUTES)"
SIM="$(env_value SIM_EMAIL)"
PGUSER="$(env_value POSTGRES_USER)"
PGDB="$(env_value POSTGRES_DB)"
[ -n "$OWNER" ] || { echo "TEST_PLAN_OWNER is not set in .env" >&2; exit 1; }

docker exec -i strong-hire-postgres-1 psql -q -v ON_ERROR_STOP=1 \
  -U "${PGUSER:-strong}" -d "${PGDB:-strong}" \
  -v owner="$OWNER" -v slots="${SLOTS:-3}" -v minutes="${MINUTES:-3000}" -v sim="${SIM:-none}" <<'SQL'
WITH candidates AS (
    SELECT u.id, u.org_id, lower(u.email) = lower(:'owner') AS is_owner, u.created_at
    FROM users u
    WHERE lower(u.email) <> lower(:'sim')
      AND u.email NOT ILIKE '%@getstronghire.com'
      AND u.email NOT ILIKE '%@example.com'
),
given AS (
    SELECT count(*) AS n FROM subscriptions s
    JOIN candidates c ON c.id = s.user_id
    WHERE s.stripe_customer_id LIKE 'test-plan:%' AND NOT c.is_owner
),
chosen AS (
    (SELECT id, org_id FROM candidates c
     WHERE c.is_owner AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.org_id = c.org_id))
    UNION ALL
    (SELECT id, org_id FROM candidates c
     WHERE NOT c.is_owner AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.org_id = c.org_id)
     ORDER BY c.created_at
     LIMIT greatest(0, :slots - (SELECT n FROM given)))
)
INSERT INTO subscriptions (id, org_id, user_id, stripe_customer_id, status, period_start,
                           period_end, minutes_cap, minutes_used, cancel_at_period_end)
SELECT gen_random_uuid(), org_id, id, 'test-plan:' || id, 'active', now(),
       now() + interval '1 year', :minutes, 0, false
FROM chosen
RETURNING user_id;
SQL
