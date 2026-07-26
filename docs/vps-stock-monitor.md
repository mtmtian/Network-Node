# VPS Stock Monitor

`tools/vps_stock.py` is a read-only inventory monitor. It checks public
provider pages and recent social leads; it never logs in, adds a product to a
cart, submits an order, or changes a server.

Run it from the repository root:

```bash
python3 tools/vps_stock.py --state-file ~/.cache/network-node/vps-stock.json
```

The state file is intentionally outside the repository. The monitor reports
only new availability/lead transitions and meaningful source exceptions.
Social posts and third-party catalog observations remain leads until the
provider's official page is checked.

The first successful run creates a baseline and does not notify existing stock
or posts. Later transport, parser, rate-limit, and dependency failures are
written to `<state>.last-run.json` but do not overwrite the last valid source
state. Runs with `--cn2-only` or `--no-social` merge their checked sources into
the existing state instead of deleting unselected history. State, previous
state, and run-report files are replaced atomically; webhook events use a
persisted pending record and deterministic idempotency key until delivery.
Each source establishes its own baseline: a source whose first attempt fails
is stored as `unobserved`, and its first later success does not produce a false
restock notification. Failed attempts on previously valid sources are attached
as `last_attempt` while the last valid status remains available for comparison.

The default source order is official provider pages, Exa web discovery, named
provider X/Reddit leads, and generic X/Reddit discovery. Exa is the preferred
web-search backend for broad VPS discovery, not an inventory authority: its
results are kept only when they are within the three-day window and contain
eligible price plus concrete VPS evidence, then still require official
verification. Configure it locally with:

```bash
mcporter config add exa https://mcp.exa.ai/mcp
```

If Exa is unavailable, the monitor reports the exception and continues with
the remaining sources. `--no-social` remains an official-source-only check and
skips Exa and X/Reddit discovery.

The default overall source-check budget is 300 seconds (`--run-timeout`).
Official pages are checked first, duplicate official URLs share one response,
and transient transport/5xx failures receive one retry. A Twitter/X 429 opens
a per-run circuit breaker so later X searches are skipped without erasing
their previous successful state. Set `--run-timeout 0` only when an unbounded
manual run is intentional.

The official matrix includes the ZgoVPS Los Angeles AMD Optimised Starter at
`$18/quarter` (`$6/month` equivalent), tracked separately from the `$52/year`
special-offer page.
It also includes DediOne `LAX.VPS.CMIN2.1C1G10G-Annual` at `$29.99/year`; the
official product card exposes an order action but no numeric inventory count.
YT.NET's [Los Angeles deployment page](https://cloud.yt.net/deploy/us-lax) is
tracked as two independent CNY monthly sources: `US.LAX.A` at `¥22/month` and
`US.LAX.B` at `¥35/month`. The monitor reads each plan card separately and uses
the page's `缺货` label as an orderability signal. If either configured offer
keeps the plan name but changes price, it reports `offer_changed` with the
observed prices instead of treating the page as unreachable. It does not claim
a numeric inventory count or convert the CNY prices to the USD budget
threshold. The page's `US.LAX.C` tier is not included in this monitor.
ZoroCloud's [Japan residential BGP page](https://my.zorocloud.com/store/jpisp)
is also tracked for the requested `JP-Titan-Plus` plan at `¥138/month`. The
monitor uses a numeric `可用` count when published and otherwise falls back to
the enabled/disabled order action at medium confidence. Its CNY price is
tracked as a user-requested source and is not treated as within the monitor's
default USD value filter.

LightLayer keeps its whole catalog behind an account login, so its two Los
Angeles annual plans use the `manual` source kind: the monitor never fetches
them and reports the specs and price verified by hand, plus how old that
snapshot is. Past `stale_after_days` (30 by default) the source turns
`unknown`, surfacing as an exception that prompts a re-check.

- `lightlayer-lax-vp01-a-annual` — `LA-VP01-A`, `$24.99/year`, Premium line,
  20Mbps unmetered, 50GB NVMe, native IPv4
- `lightlayer-lax-vp04-l-a-annual` — `LA-VP04-L-A`, `$49.99/year`, Premium
  line, 1Gbps at 1TB/month, 50GB NVMe, native IPv4

Premium means CN2 for China Telecom and CMIN2 for China Unicom and Mobile.
Both promo plans are non-upgradeable and non-refundable. Re-verify at the URL
recorded on each source and bump `verified_on` when the snapshot changes.

Validation for monitor changes:

```bash
python3 -m py_compile tools/vps_stock.py
python3 -m unittest tests.test_vps_stock
```
