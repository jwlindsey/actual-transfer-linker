"""Reading and writing the Actual budget (through actualpy)."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from .matching import Match, Pair, Skipped, Txn, find_matches


@dataclass
class Report:
    linked: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.linked or self.repaired)


def _label(t) -> str:
    payee = t.payee.name if t.payee is not None and t.payee.name else ""
    return " ".join(x for x in (payee, t.imported_description or "", t.notes or "") if x)


def _money(x) -> str:
    return f"{abs(x):,.2f}"


def repair(session, accounts: dict, since: dt.date, report: Report, dry_run: bool) -> None:
    """A transfer whose payee no longer names the other account is half broken.

    This happens when a transfer was entered ahead of time and bank sync later matched the bank's
    transaction to it (same amount, within 7 days): the import writes the bank's payee over the transfer
    payee. The link (transferred_id) survives, so the payee can be put back.
    """
    from actual.database import Transactions
    from actual.queries import get_transactions
    for t in get_transactions(session, start_date=since):
        if not t.transferred_id or t.tombstone:
            continue
        other = session.get(Transactions, t.transferred_id)
        if other is None or other.tombstone:
            continue
        acc = accounts.get(other.acct)
        if acc is None or acc.payee is None:
            continue
        if t.payee_id != acc.payee.id:
            if not dry_run:
                t.payee_id = acc.payee.id
            report.repaired.append(f"{t.get_date()} {accounts[t.acct].name}: {_money(t.get_amount())} "
                                   f"payee set back to the transfer to {acc.name}")


def link(session, pairs: list[Pair], words: list[str], max_days: int, since: dt.date, report: Report,
         dry_run: bool) -> list[Match]:
    """Find unlinked transaction pairs between the configured accounts and link them as transfers."""
    from actual.queries import get_accounts, get_category, get_transactions
    accounts = {a.id: a for a in get_accounts(session)}
    by_name = {a.name: a for a in accounts.values()}
    for p in pairs:
        for name in (p.a, p.b):
            if name not in by_name:
                report.problems.append(f'account "{name}" is not in this budget')
    pairs = [p for p in pairs if p.a in by_name and p.b in by_name]
    names = {n for p in pairs for n in (p.a, p.b)}

    rows = {}
    for t in get_transactions(session, start_date=since):
        acc = accounts.get(t.acct)
        if (acc is None or acc.name not in names or t.tombstone or t.transferred_id or t.is_parent
                or t.is_child or t.starting_balance_flag):
            continue
        rows[str(t.id)] = t
    txns = [Txn(id=i, account=accounts[t.acct].name, date=t.get_date(), amount=t.get_amount(),
                label=_label(t), categorised=t.category_id is not None) for i, t in rows.items()]
    matches, skipped = find_matches(txns, pairs, words, max_days)

    for s in skipped:
        report.skipped.append(f"{s.txn.date} {s.txn.account}: {_money(s.txn.amount)} not linked ({s.reason})")
    for m in matches:
        out, inn = rows[m.out.id], rows[m.inn.id]
        src, dst = accounts[out.acct], accounts[inn.acct]
        category = None
        if m.pair.category and bool(src.offbudget) != bool(dst.offbudget):
            category = get_category(session, m.pair.category)
            if category is None:
                report.problems.append(f'category "{m.pair.category}" is not in this budget; '
                                       f"{src.name} → {dst.name} linked without it")
        line = f"{m.out.date} {_money(m.out.amount)} {src.name} → {dst.name}" + (
            f" (on {m.inn.date})" if m.inn.date != m.out.date else "") + (
            f", booked under {category.name}" if category is not None else "")
        report.linked.append(line)
        if dry_run:
            continue
        for side, own, other in ((out, src, dst), (inn, dst, src)):
            side.payee_id = other.payee.id
            side.category_id = category.id if category is not None and not own.offbudget else None
        out.transferred_id, inn.transferred_id = inn.id, out.id
    return matches


def sync_start(session, account) -> dt.date | None:
    """Where bank sync starts for one account: a week before the newest transaction the bank itself sent.

    actualpy starts at the account's newest transaction of any kind. One you typed in before the bank posted
    it (a transfer entered ahead of time, a purchase logged the same day) then moves the start past whatever
    the bank posts later with an earlier date, and those are never imported. Fetching the last week again is
    safe: transactions the bank already sent are recognised by their id. None: no bank transactions yet,
    actualpy decides.
    """
    from actual.database import Transactions
    from sqlmodel import select
    newest = session.exec(select(Transactions.date).where(
        Transactions.acct == account.id, Transactions.financial_id.is_not(None), Transactions.tombstone == 0,
    ).order_by(Transactions.date.desc())).first()
    if not newest:
        return None
    return dt.datetime.strptime(str(newest), "%Y%m%d").date() - dt.timedelta(days=7)


def bank_sync(actual) -> None:
    """Actual's bank sync for every linked account, each starting at sync_start, then the budget's rules."""
    from actual.queries import get_accounts
    s = actual.session
    imported = []
    for acct in get_accounts(s):
        if acct.account_id and acct.account_sync_source:
            imported += actual.run_bank_sync(account=acct, start_date=sync_start(s, acct))
    actual.run_rules(imported)


def run(cfg, dry_run: bool = True, sync: bool = False, today: dt.date | None = None) -> Report:
    """Open the budget, optionally run bank sync, link and repair transfers, and commit unless `dry_run`."""
    from actual import Actual
    from actual.queries import get_accounts
    today = today or dt.date.today()
    since = today - dt.timedelta(days=cfg.lookback_days)
    report = Report()
    with Actual(base_url=cfg.url, password=cfg.password, file=cfg.file,
                encryption_password=cfg.encryption_password, cert=cfg.cert) as actual:
        if sync:
            bank_sync(actual)
            actual.commit()          # the import is kept even in a dry run: it is what bank sync does anyway
        s = actual.session
        accounts = {a.id: a for a in get_accounts(s)}
        repair(s, accounts, since, report, dry_run)
        link(s, cfg.pairs, cfg.words, cfg.max_days, since, report, dry_run)
        if not dry_run and report.changed:
            actual.commit()
    return report
