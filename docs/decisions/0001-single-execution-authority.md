# ADR 0001: Single exchange execution authority

- Status: Accepted for containment
- Date: 2026-09-05

## Context

Two independently evolved Barry systems contain overlapping market-data,
risk, Telegram, persistence, and exchange-execution behavior. This makes the
effective owner of trading decisions ambiguous and allows safety controls in
one system to be bypassed by another.

## Decision

BastoBot is the conversational, research, dashboard, and trade-proposal layer.
It must not mutate exchange state directly. A separate canonical Barry engine
will become the only process allowed to place, modify, cancel, or close orders.

Until that engine is implemented and validated, all exchange mutations from
BastoBot are disabled by a fail-closed environment gate. Analysis and read-only
account/market inspection remain available.

## Invariants

1. Exchange signing credentials will ultimately exist only in the canonical
   execution service.
2. The final execution gateway must enforce risk, freshness, idempotency, and
   mode checks itself.
3. Interface-layer approval never bypasses execution-layer validation.
4. Paper, testnet, shadow, and live state must be explicitly separated.
5. An absent, invalid, or false execution gate denies exchange mutations.

## Consequences

Existing direct BastoBot exchange commands are contained. Useful market-data,
Telegram, and account-inspection code can be retained while execution is
rebuilt behind a narrow authenticated interface.
