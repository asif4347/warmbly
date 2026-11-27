// Datamart: AI credits for a server with billing off. Copied into
// internal/app/credits by datamart/rebrand.py.
//
// With BILLING_PROVIDER=none upstream meters nothing, so one busy workspace
// could run up any bill on the operator's AI provider. Every AI feature (the
// Molty agent, campaign AI steps, automations, reply drafts) already charges
// credits through Consume, so capping credits caps all of it.
//
// A charge is taken from the free allowance first:
//
//   - every workspace gets DATAMART_AI_FREE_DAILY credits per UTC day
//     (default 15, about five Molty messages);
//   - unlocked workspaces get DATAMART_AI_UNLOCKED_MONTHLY credits per UTC
//     month instead (default 1500). A workspace is unlocked when the Molty
//     billing service (datamart/billing) has it in the Redis set
//     datamart:ai:unlocked, or when it is listed in DATAMART_AI_UNLOCKED_ORGS;
//   - DATAMART_AI_ORG_MONTHLY sets a workspace's own monthly allowance and
//     overrides both ("<organization id>=2500,<organization id>=500").
//
// What the free allowance cannot cover comes out of the workspace's paid
// credits: one-time packs bought through datamart/billing. They live in
// upstream's own credit ledger (the purchased pool in Postgres), so they never
// expire and are debited atomically. The billing service never writes the
// ledger itself: a paid checkout lands in the Redis hash
// datamart:ai:grants:<organization id> (session id -> credits), and the next
// balance read or charge grants it here, keyed on the Stripe session so a
// replay never credits twice. Stripe stays the record: the billing service
// re-offers every paid session it does not see in datamart:ai:granted.
//
// A free limit of 0 means no limit. The free count lives in Redis and fails
// open: a Redis outage never blocks AI, the same as upstream's own caps.

package credits

import (
	"context"
	"errors"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/warmbly/warmbly/internal/repository"
)

var (
	datamartFreeDaily       = datamartEnvInt("DATAMART_AI_FREE_DAILY", 15)
	datamartUnlockedMonthly = datamartEnvInt("DATAMART_AI_UNLOCKED_MONTHLY", 1500)
	datamartUnlocked        = datamartEnvSet("DATAMART_AI_UNLOCKED_ORGS")
	datamartOrgMonthly      = datamartEnvLimits("DATAMART_AI_ORG_MONTHLY")
)

const (
	datamartUnlockedKey = "datamart:ai:unlocked" // set the billing service keeps
	datamartGrantsKey   = "datamart:ai:grants:"  // hash per workspace: session id -> credits
	datamartGrantedKey  = "datamart:ai:granted"  // set of session ids already in the ledger
	datamartGrantReason = "credit_topup"         // the ledger reason upstream uses for packs
	datamartBuyPath     = "/molty/credits?org="  // datamart/billing's pack page
	datamartPaidKeyPart = ":datamart-paid"       // keeps the paid debit's idempotency key apart
)

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

func datamartEnvLimits(name string) map[string]int {
	limits := map[string]int{}
	for _, pair := range strings.Split(os.Getenv(name), ",") {
		id, n, ok := strings.Cut(pair, "=")
		v, err := strconv.Atoi(strings.TrimSpace(n))
		if ok && err == nil && v >= 0 {
			limits[strings.ToLower(strings.TrimSpace(id))] = v
		}
	}
	return limits
}

// datamartWindow is the workspace's free allowance right now.
type datamartWindow struct {
	key     string // Redis counter
	limit   int    // 0 means no limit
	ttl     time.Duration
	resetAt time.Time
	period  string // "day" or "month"
}

func (s *creditService) datamartWindow(ctx context.Context, orgID uuid.UUID) datamartWindow {
	now := time.Now().UTC()
	day := time.Date(now.Year(), now.Month(), now.Day(), 0, 0, 0, 0, time.UTC)
	month := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
	w := datamartWindow{
		key:     "datamart:ai:day:" + orgID.String() + ":" + now.Format("2006-01-02"),
		limit:   datamartFreeDaily,
		ttl:     26 * time.Hour,
		resetAt: day.AddDate(0, 0, 1),
		period:  "day",
	}
	monthly := func(limit int) {
		w.key = "datamart:ai:month:" + orgID.String() + ":" + now.Format("2006-01")
		w.limit, w.ttl, w.resetAt, w.period = limit, 32*24*time.Hour, month.AddDate(0, 1, 0), "month"
	}
	unlocked := datamartUnlocked[orgID.String()]
	if !unlocked && s.cache != nil {
		unlocked, _ = s.cache.SIsMember(ctx, datamartUnlockedKey, orgID.String()).Result()
	}
	if unlocked {
		monthly(datamartUnlockedMonthly)
	}
	if own, ok := datamartOrgMonthly[orgID.String()]; ok {
		monthly(own)
	}
	return w
}

// datamartFree takes amount from the free allowance and returns the part it
// could not cover, plus a function that gives the whole amount back.
func (s *creditService) datamartFree(ctx context.Context, w datamartWindow, amount int) (int, func()) {
	noop := func() {}
	if s.cache == nil || w.limit == 0 {
		return 0, noop
	}
	n, err := s.cache.IncrBy(ctx, w.key, int64(amount)).Result()
	if err != nil {
		return 0, noop
	}
	if n == int64(amount) {
		s.cache.Expire(ctx, w.key, w.ttl)
	}
	undo := func() { s.cache.DecrBy(context.WithoutCancel(ctx), w.key, int64(amount)) }
	if n <= int64(w.limit) {
		return 0, undo
	}
	return min(amount, int(n-int64(w.limit))), undo
}

// datamartApplyGrants moves paid checkouts waiting in Redis into the ledger.
// A failed grant stays queued and is retried on the next read.
func (s *creditService) datamartApplyGrants(ctx context.Context, orgID uuid.UUID) {
	if s.cache == nil || s.repo == nil {
		return
	}
	key := datamartGrantsKey + orgID.String()
	pending, err := s.cache.HGetAll(ctx, key).Result()
	if err != nil {
		return
	}
	for session, v := range pending {
		n, err := strconv.Atoi(v)
		if err != nil || n <= 0 {
			s.cache.HDel(ctx, key, session)
			continue
		}
		if _, _, err := s.repo.GrantPurchased(ctx, orgID, n, datamartGrantReason, "stripe:"+session); err != nil {
			continue
		}
		s.cache.SAdd(ctx, datamartGrantedKey, session)
		s.cache.HDel(ctx, key, session)
	}
}

// datamartConsume charges one AI action: free allowance first, then paid
// credits. Out of both, it returns ErrCapExceeded, which Molty shows with a
// link to buy more.
func (s *creditService) datamartConsume(ctx context.Context, orgID uuid.UUID, amount int, reason, model string, tokens int, idempotencyKey string) (int, error) {
	if amount <= 0 {
		return selfHostBalance, nil
	}
	s.datamartApplyGrants(ctx, orgID)
	over, undo := s.datamartFree(ctx, s.datamartWindow(ctx, orgID), amount)
	if over == 0 {
		return selfHostBalance, nil
	}
	if s.repo == nil {
		undo()
		return 0, ErrCapExceeded
	}
	key := ""
	if idempotencyKey != "" {
		key = idempotencyKey + datamartPaidKeyPart
	}
	if _, _, _, err := s.repo.Consume(ctx, orgID, over, reason, model, tokens, key); err != nil {
		undo()
		if errors.Is(err, repository.ErrInsufficientCredits) {
			return 0, ErrCapExceeded
		}
		return 0, err
	}
	return selfHostBalance, nil
}

// DatamartBalance is the credits payload for the top bar: the free allowance
// shown as the plan pool, paid credits as the purchased pool. ok is false when
// svc is not this package's service.
func DatamartBalance(ctx context.Context, svc CreditService, orgID uuid.UUID) (map[string]any, bool) {
	s, ok := svc.(*creditService)
	if !ok {
		return nil, false
	}
	s.datamartApplyGrants(ctx, orgID)
	w := s.datamartWindow(ctx, orgID)
	used := 0
	if s.cache != nil && w.limit > 0 {
		if n, err := s.cache.Get(ctx, w.key).Int(); err == nil {
			used = min(max(n, 0), w.limit)
		}
	}
	paid, total := 0, 0
	if s.repo != nil {
		if l, err := s.repo.GetBalance(ctx, orgID); err == nil && l != nil {
			paid, total = l.Total(), l.TotalPurchased
		}
	}
	free := w.limit - used
	return map[string]any{
		"unlimited":         w.limit == 0,
		"balance":           free + paid,
		"monthly_balance":   free,
		"purchased_balance": paid,
		"monthly_allowance": w.limit,
		"total_purchased":   total,
		"monthly_reset_at":  nil,
		"next_reset_at":     w.resetAt,
		"packs":             []CreditPack{},
		"free_period":       w.period,
		"free_used":         used,
		"buy_url":           datamartBuyPath + orgID.String(),
	}, true
}
