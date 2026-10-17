"""Pure matching logic: which pairs of transactions are the two sides of one transfer.

Kept free of Actual and database objects so it can be tested on its own.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Pair:
    """Two accounts money moves between (either direction). `category` is used only when one account is
    on budget and the other off budget: Actual books the on-budget side of such a transfer under a category."""
    a: str
    b: str
    category: str | None = None

    def other(self, account: str) -> str | None:
        if account == self.a:
            return self.b
        if account == self.b:
            return self.a
        return None


@dataclass(frozen=True)
class Txn:
    """The parts of a transaction the matcher needs."""
    id: str
    account: str
    date: dt.date
    amount: Decimal          # negative = money out of `account`
    label: str = ""          # payee / bank description / notes, for the transfer words
    categorised: bool = False


@dataclass(frozen=True)
class Match:
    out: Txn                 # money leaving one account
    inn: Txn                 # money arriving in the other
    pair: Pair


@dataclass(frozen=True)
class Skipped:
    txn: Txn
    reason: str


def eligible(t: Txn, words: list[str]) -> bool:
    """Uncategorised, or described like a transfer. A categorised transaction without transfer words is a
    real purchase or deposit that happens to have the same amount, and is left alone."""
    if not t.categorised:
        return True
    label = t.label.lower()
    return any(w in label for w in words)


def find_matches(txns: list[Txn], pairs: list[Pair], words: list[str], max_days: int = 5) -> tuple[list[Match], list[Skipped]]:
    """Match money out of one account with the same amount into its partner account within `max_days`.

    Only exact, unambiguous matches are returned. When two candidates are equally good (same amount, same
    distance in days) nothing is linked and the transaction is reported as skipped, so a wrong pair is never
    made silently.
    """
    words = [w.lower() for w in words]
    pool = [t for t in txns if eligible(t, words)]
    outs = sorted((t for t in pool if t.amount < 0), key=lambda t: (t.date, t.id))
    used: set[str] = set()
    matches: list[Match] = []
    skipped: list[Skipped] = []

    def candidates(out: Txn) -> list[tuple[int, Txn, Pair]]:
        found = []
        for pair in pairs:
            other = pair.other(out.account)
            if other is None:
                continue
            for t in pool:
                if (t.id not in used and t.account == other and t.amount == -out.amount
                        and abs((t.date - out.date).days) <= max_days):
                    found.append((abs((t.date - out.date).days), t, pair))
        return sorted(found, key=lambda c: (c[0], c[1].id))

    for out in outs:
        if out.id in used:
            continue
        found = candidates(out)
        if not found:
            continue
        best_days = found[0][0]
        best = [c for c in found if c[0] == best_days]
        if len(best) > 1:
            skipped.append(Skipped(out, f"{len(best)} equally close matches in {', '.join(sorted({c[1].account for c in best}))}"))
            continue
        _, inn, pair = best[0]
        # the other way round too: another unused outflow just as close to this inflow is just as likely
        rivals = [o for o in outs if o.id != out.id and o.id not in used and o.amount == out.amount
                  and any(p.other(o.account) == inn.account for p in pairs)
                  and abs((o.date - inn.date).days) == best_days]
        if rivals:
            skipped.append(Skipped(out, f"another {abs(out.amount)} from {rivals[0].account} is just as close"))
            continue
        used |= {out.id, inn.id}
        matches.append(Match(out, inn, pair))
    return matches, skipped
