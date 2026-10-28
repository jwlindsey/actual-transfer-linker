"""End-to-end test against a throwaway Actual server (never a real budget).

    ACTUAL_TEST_URL=http://localhost:5006 python tests/integration_test.py

The server must be fresh: the script sets its password, creates a budget "Linker Test" with fake accounts,
runs the linker the way the command line does, and checks the result after downloading the budget again.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from actual import Actual  # noqa: E402
from actual.database import Accounts, Transactions  # noqa: E402
from actual.queries import (create_account, create_category, create_transaction, create_transfer,  # noqa: E402
                            get_accounts, get_transactions, reconcile_transaction)

from actual_transfer_linker import cli, ledger  # noqa: E402

URL = os.environ.get("ACTUAL_TEST_URL", "http://localhost:5006")
PASSWORD = "linker-test-only"
BUDGET = "Linker Test"
TODAY = dt.date.today()
DAY = lambda n: TODAY - dt.timedelta(days=n)  # noqa: E731


def setup() -> None:
    with Actual(base_url=URL, password=PASSWORD, bootstrap=True) as a:
        a.create_budget(BUDGET)
        a.upload_budget()
        s = a.session
        chk = create_account(s, "Checking", Decimal("1000"))
        sav = create_account(s, "Savings", Decimal("500"))
        pp = create_account(s, "PayPal", Decimal("0"))
        brk = create_account(s, "Brokerage", Decimal("0"), off_budget=True)
        create_category(s, "Groceries", "Usual Expenses")
        create_category(s, "Investments", "Usual Expenses")
        groceries = "Groceries"
        # 1. a plain move, both sides from the bank, no category
        create_transaction(s, DAY(3), sav, "Online Transfer To Checking", amount=Decimal("-400"), imported_id="b1")
        create_transaction(s, DAY(2), chk, "Online Transfer From Savings", amount=Decimal("400"), imported_id="b2")
        # 2. PayPal -> Checking where the bank side already got a category from a rule, but says "transfer"
        create_transaction(s, DAY(6), pp, "Money Transfer to BANK", amount=Decimal("-180"), imported_id="b3")
        create_transaction(s, DAY(5), chk, "Paypal Transfer", category="Groceries", amount=Decimal("180"), imported_id="b4")
        # 3. on budget -> off budget: booked under Investments on the Checking side
        create_transaction(s, DAY(4), chk, "ACH transfer brokerage", amount=Decimal("-250"), imported_id="b5")
        create_transaction(s, DAY(3), brk, "Deposit", amount=Decimal("250"), imported_id="b6")
        # 4. a real purchase that happens to equal a PayPal deposit: must NOT be linked
        create_transaction(s, DAY(1), chk, "Costco", category=groceries, amount=Decimal("-61.11"), imported_id="b7")
        create_transaction(s, DAY(1), pp, "Refund from seller", amount=Decimal("61.11"), imported_id="b8")
        # 5. a tie: 100 out of Checking, 100 into Savings and into PayPal on the same day: skipped, not guessed
        create_transaction(s, DAY(8), chk, "Transfer", amount=Decimal("-100"), imported_id="b9")
        create_transaction(s, DAY(8), sav, "Transfer in", amount=Decimal("100"), imported_id="b10")
        create_transaction(s, DAY(8), pp, "Transfer in", amount=Decimal("100"), imported_id="b11")
        # 6. entered ahead of time, then bank sync matched both sides and overwrote the payees
        create_transfer(s, DAY(2), sav, chk, Decimal("77.77"), notes="entered ahead")
        a.commit()
        reconcile_transaction(s, DAY(1), sav, "XFER TO CHK", "bank", amount=Decimal("-77.77"), imported_id="b12",
                              imported_payee="XFER TO CHK")
        reconcile_transaction(s, DAY(1), chk, "XFER FROM SAV", "bank", amount=Decimal("77.77"), imported_id="b13",
                              imported_payee="XFER FROM SAV")
        a.commit()
        assert len([t for t in get_transactions(s) if abs(t.get_amount()) == Decimal("77.77")]) == 2, "bank match made a duplicate"
        # 7. typed in today, before the bank has it: must not move where bank sync starts
        create_transaction(s, TODAY, chk, "Coffee", category=groceries, amount=Decimal("-4.50"))
        create_account(s, "Wallet", Decimal("20"))
        a.commit()


def check_sync_start() -> None:
    """Bank sync starts a week before the newest BANK transaction, not the newest transaction."""
    with Actual(base_url=URL, password=PASSWORD, file=BUDGET, data_dir=tempfile.mkdtemp()) as a:
        acc = {x.name: x for x in get_accounts(a.session)}
        got = {n: ledger.sync_start(a.session, acc[n]) for n in ("Checking", "Savings", "Brokerage", "Wallet")}
    assert got == {"Checking": DAY(8), "Savings": DAY(8), "Brokerage": DAY(10), "Wallet": None}, got


def config_file(tmp: Path) -> Path:
    p = tmp / "config.yaml"
    p.write_text(f"""
server:
  url: {URL}
  file: {BUDGET}
  password_env: LINKER_TEST_PASSWORD
pairs:
  - [Checking, Savings]
  - [PayPal, Checking]
  - [Checking, Brokerage, Investments]
words: [transfer, xfer]
""")
    os.environ["LINKER_TEST_PASSWORD"] = PASSWORD
    return p


def state() -> dict:
    """Download the budget again and describe every non-starting-balance transaction."""
    with Actual(base_url=URL, password=PASSWORD, file=BUDGET, data_dir=tempfile.mkdtemp()) as a:
        s = a.session
        acc = {x.id: x for x in get_accounts(s)}
        out = {}
        for t in get_transactions(s):
            if t.starting_balance_flag:
                continue
            other = s.get(Transactions, t.transferred_id) if t.transferred_id else None
            oacc = acc.get(other.acct) if other else None
            out[(acc[t.acct].name, t.get_amount())] = {
                "linked_to": oacc.name if oacc else None,
                "payee_ok": bool(oacc and t.payee_id == oacc.payee.id),
                "category": t.category.name if t.category else None,
            }
        return out


def main() -> int:
    setup()
    check_sync_start()
    tmp = Path(tempfile.mkdtemp())
    cfg = config_file(tmp)
    before = state()

    print("--- dry run")
    assert cli.main(["-c", str(cfg)]) == 0
    assert state() == before, "dry run changed the budget"

    print("--- apply")
    assert cli.main(["-c", str(cfg), "--apply"]) == 0
    st = state()
    D = Decimal
    expect_linked = [("Savings", D("-400"), "Checking"), ("Checking", D("400"), "Savings"),
                     ("PayPal", D("-180"), "Checking"), ("Checking", D("180"), "PayPal"),
                     ("Checking", D("-250"), "Brokerage"), ("Brokerage", D("250"), "Checking"),
                     ("Savings", D("-77.77"), "Checking"), ("Checking", D("77.77"), "Savings")]
    for acct, amount, other in expect_linked:
        row = st[(acct, amount)]
        assert row["linked_to"] == other and row["payee_ok"], (acct, amount, row)
    assert st[("Checking", D("180"))]["category"] is None, "a transfer between on-budget accounts keeps no category"
    assert st[("Checking", D("-250"))]["category"] == "Investments"
    assert st[("Brokerage", D("250"))]["category"] is None
    for key in [("Checking", D("-61.11")), ("PayPal", D("61.11")), ("Checking", D("-100")), ("Savings", D("100")),
                ("PayPal", D("100"))]:
        assert st[key]["linked_to"] is None, (key, st[key])
    assert st[("Checking", D("-61.11"))]["category"] == "Groceries"

    print("--- second run: nothing left to do")
    assert cli.main(["-c", str(cfg), "--apply"]) == 0
    assert state() == st
    print("INTEGRATION PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
