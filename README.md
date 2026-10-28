# actual-transfer-linker

When bank sync brings in money you moved between your own accounts, [Actual Budget](https://actualbudget.org)
gets two separate transactions, money out of one account and money into the other. Until you select both and
use **Make transfer**, reports count the move twice: once as spending and once as income.

This tool finds those pairs and links them as one transfer, the same way **Make transfer** does. Run it after
bank sync, by hand or on a schedule.

It also fixes a problem with transfers you enter ahead of time. When bank sync later matches the bank's
transaction to your transfer (same amount, within 7 days), the import can overwrite the transfer's payee and
half-break the link. The tool puts the payee back.

## Do you need this?

Probably not, if Actual's built-in options cover you:

- **Rules.** A rule can turn a synced transaction into a transfer (set the payee to the other account, e.g.
  "Transfer: Savings"). Actual then creates the other side, and when that account syncs, its transaction is
  matched to it instead of being added twice. See [Rules](https://actualbudget.org/docs/budgeting/rules/) and
  [Transfers](https://actualbudget.org/docs/transactions/transfers).
- **Past transactions.** The docs have a script for linking transfers already in your budget:
  [Identify and Apply Transfers Historically](https://actualbudget.org/docs/advanced/scripts/modify-transfers).

This tool is for the cases those leave open: you'd rather not write a rule per account, the receiving side
sometimes syncs before the sending side, or transfers you entered ahead of time get their payee overwritten
when bank sync matches them.

## What gets linked

Two transactions are linked only when **all** of these hold:

- They are in two accounts you listed as a pair (either direction).
- The amounts are exactly equal and opposite.
- They are at most `max_days` apart (5 by default).
- Neither is already a transfer, a split, or a starting balance.
- Each one either has no category yet, or its payee, bank description or notes contain one of your transfer
  `words`. A categorised transaction without those words is treated as a real purchase or deposit that just
  happens to have the same amount, and is left alone.

When two candidates are equally good (same amount, same distance in days), the tool **skips** them and reports
it instead of guessing. You link those by hand in Actual.

If one account is on budget and the other off budget (for example checking → brokerage), Actual books the
on-budget side under a category. Give the pair a third item to set it.

**Not handled (yet):** transfers where the two amounts differ (a fee taken on one side, currency conversion).

## Install

Python 3.10 or newer.

```sh
pip install git+https://github.com/jwlindsey/actual-transfer-linker
```

or from a checkout: `pip install .`

## Configure

Copy `config.example.yaml` to `config.yaml` and edit it:

```yaml
server:
  url: http://localhost:5006
  file: My Budget                  # the budget's name in Actual
  password_env: ACTUAL_PASSWORD    # environment variable holding the server password

pairs:
  - [Checking, Savings]
  - [PayPal, Checking]
  - [Checking, Brokerage, Investments]   # off-budget account: on-budget side booked under "Investments"

words: [transfer, xfer]
max_days: 5
lookback_days: 30
```

Use your account names exactly as they appear in Actual. Keep the password in an environment variable rather
than in the file. If your budget is end-to-end encrypted, also set `encryption_password_env`.

## Run

```sh
export ACTUAL_PASSWORD='...'
actual-transfer-linker -c config.yaml            # dry run: shows what it would do, changes nothing
actual-transfer-linker -c config.yaml --apply    # link and repair
actual-transfer-linker -c config.yaml --sync --apply   # run Actual's bank sync first, then link
```

With `--sync`, each account is synced from a week before the newest transaction the bank sent. Transactions
you typed in yourself don't move that start, so the bank's late postings still come in (0.1.1; before that,
a transaction entered ahead of the bank could make bank sync skip the bank's later postings).

Example output:

```
Linked: 2026-10-14 400.00 Savings → Checking (on 2026-10-15)
Linked: 2026-10-13 250.00 Checking → Brokerage (on 2026-10-14), booked under Investments
Repaired: 2026-10-16 Checking: 77.77 payee set back to the transfer to Savings
Skipped: 2026-10-09 Checking: 100.00 not linked (2 equally close matches in PayPal, Savings)
```

Exit codes: `0` done, `1` couldn't reach or open the budget, `2` bad settings, `3` done but something in the
settings doesn't exist in the budget (an account or category name).

Start with dry runs and look at what it proposes before you add `--apply`. Back up your budget first
(Settings → Export data in Actual).

### On a schedule

Run it shortly after your bank sync, for example with cron:

```cron
15 6 * * * ACTUAL_PASSWORD='...' /path/to/venv/bin/actual-transfer-linker -c /path/to/config.yaml --apply -q
```

## How it links

Exactly what **Make transfer** in Actual does: each side's payee becomes the other account's transfer payee,
the two transactions point at each other, and the category is cleared (except on the on-budget side of an
on/off-budget transfer). Nothing is deleted or created. The tool talks to your server through
[actualpy](https://github.com/bvanelli/actualpy).

## Tests

```sh
pip install '.[test]'
pytest tests/test_matching.py
```

`tests/integration_test.py` runs the whole tool against a **fresh, throwaway** Actual server: it sets that
server's password and creates a test budget. Never point it at a server you use.

```sh
docker run -d --name actual-test -p 127.0.0.1:5099:5006 actualbudget/actual-server:latest
ACTUAL_TEST_URL=http://localhost:5099 python tests/integration_test.py
docker rm -f actual-test
```

## Related

Automatic transfer detection inside Actual is a long-standing request:
[actualbudget/actual#1628](https://github.com/actualbudget/actual/issues/1628).

## How this was made

Written with AI assistance (Claude, by Anthropic) and reviewed, tested and maintained by
[@jwlindsey](https://github.com/jwlindsey). It started as part of a personal budgeting setup and is shared
for the community, free, with no strings attached. Issues and pull requests are welcome.

## License

MIT
