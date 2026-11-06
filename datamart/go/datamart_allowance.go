// Datamart: an AI allowance for a server with billing off. Copied into
// internal/app/credits by datamart/rebrand.py.
//
// With BILLING_PROVIDER=none upstream meters nothing, so one busy workspace
// could run up any bill on the operator's AI provider. Every AI feature (the
// Molty agent, campaign AI steps, automations, reply drafts) already charges
// credits through Consume, so capping credits caps all of it:
//
//   - every workspace gets DATAMART_AI_FREE_DAILY credits per UTC day
//     (default 15, about five Molty messages);
//   - unlocked workspaces get DATAMART_AI_UNLOCKED_MONTHLY credits per UTC
//     month instead (default 1500). A workspace is unlocked when the Molty
//     billing service (datamart/billing) has it in the Redis set
//     datamart:ai:unlocked after a paid Stripe checkout, or when it is listed
//     by hand in DATAMART_AI_UNLOCKED_ORGS (comma-separated organization IDs).
//
// A limit of 0 means no limit. Counting lives in Redis and fails open: a Redis
// outage never blocks AI, the same as upstream's own caps.

package credits

import (
	"context"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

var (
	datamartFreeDaily       = datamartEnvInt("DATAMART_AI_FREE_DAILY", 15)
	datamartUnlockedMonthly = datamartEnvInt("DATAMART_AI_UNLOCKED_MONTHLY", 1500)
	datamartUnlocked        = datamartEnvSet("DATAMART_AI_UNLOCKED_ORGS")
)

// datamartUnlockedKey is the Redis set the billing service keeps.
const datamartUnlockedKey = "datamart:ai:unlocked"

func datamartEnvInt(name string, def int) int {
	if v, err := strconv.Atoi(strings.TrimSpace(os.Getenv(name))); err == nil && v >= 0 {
		return v
	}
	return def
}

func datamartEnvSet(name string) map[string]bool {
	set := map[string]bool{}
	for _, id := range strings.Split(os.Getenv(name), ",") {
		if id = strings.ToLower(strings.TrimSpace(id)); id != "" {
			set[id] = true
		}
	}
	return set
}

// datamartAllowance charges amount against the org's allowance and returns
// ErrCapExceeded, leaving the count unchanged, when it would go over.
func (s *creditService) datamartAllowance(ctx context.Context, orgID uuid.UUID, amount int) error {
	if s.cache == nil || amount <= 0 {
		return nil
	}
	now := time.Now().UTC()
	key := "datamart:ai:day:" + orgID.String() + ":" + now.Format("2006-01-02")
	limit, window := datamartFreeDaily, 26*time.Hour
	unlocked := datamartUnlocked[orgID.String()]
	if !unlocked {
		unlocked, _ = s.cache.SIsMember(ctx, datamartUnlockedKey, orgID.String()).Result()
	}
	if unlocked {
		key = "datamart:ai:month:" + orgID.String() + ":" + now.Format("2006-01")
		limit, window = datamartUnlockedMonthly, 32*24*time.Hour
	}
	if limit == 0 {
		return nil
	}
	n, err := s.cache.IncrBy(ctx, key, int64(amount)).Result()
	if err != nil {
		return nil
	}
	if n == int64(amount) {
		s.cache.Expire(ctx, key, window)
	}
	if n > int64(limit) {
		s.cache.DecrBy(ctx, key, int64(amount))
		return ErrCapExceeded
	}
	return nil
}
