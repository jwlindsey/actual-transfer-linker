import datetime as dt
from decimal import Decimal

from actual_transfer_linker.matching import Pair, Txn, find_matches

D = dt.date(2026, 3, 10)
PAIRS = [Pair("Checking", "Savings"), Pair("PayPal", "Checking"), Pair("Checking", "Brokerage", "Investments")]
WORDS = ["transfer"]


def t(id, account, amount, days=0, label="", categorised=False):
    return Txn(id, account, D + dt.timedelta(days=days), Decimal(str(amount)), label, categorised)


def ids(matches):
    return [(m.out.id, m.inn.id) for m in matches]


def test_simple_pair_either_direction():
    m, s = find_matches([t("o", "Savings", -400), t("i", "Checking", 400, 1)], PAIRS, WORDS)
    assert ids(m) == [("o", "i")] and not s
    m, _ = find_matches([t("o", "Checking", -50), t("i", "Savings", 50)], PAIRS, WORDS)
    assert ids(m) == [("o", "i")]


def test_amount_must_match_exactly():
    m, _ = find_matches([t("o", "Savings", -400), t("i", "Checking", 399.99)], PAIRS, WORDS)
    assert m == []


def test_outside_window_not_linked():
    m, _ = find_matches([t("o", "Savings", -400), t("i", "Checking", 400, 6)], PAIRS, WORDS, max_days=5)
    assert m == []


def test_accounts_not_paired_not_linked():
    m, _ = find_matches([t("o", "Savings", -400), t("i", "PayPal", 400)], PAIRS, WORDS)
    assert m == []


def test_categorised_purchase_left_alone_unless_described_as_transfer():
    txns = [t("o", "Checking", -61.11, label="Costco", categorised=True), t("i", "PayPal", 61.11)]
    assert find_matches(txns, PAIRS, WORDS)[0] == []
    txns = [t("o", "Checking", -61.11, label="Online Transfer to PayPal", categorised=True), t("i", "PayPal", 61.11)]
    assert ids(find_matches(txns, PAIRS, WORDS)[0]) == [("o", "i")]


def test_closest_date_wins():
    txns = [t("o", "Savings", -100), t("far", "Checking", 100, 4), t("near", "Checking", 100, 1)]
    assert ids(find_matches(txns, PAIRS, WORDS)[0]) == [("o", "near")]


def test_tie_is_skipped_not_guessed():
    txns = [t("o", "Checking", -100), t("a", "Savings", 100, 1), t("b", "PayPal", 100, 1)]
    m, s = find_matches(txns, PAIRS, WORDS)
    assert m == [] and len(s) == 1 and s[0].txn.id == "o"


def test_rival_outflow_is_skipped_not_guessed():
    txns = [t("o1", "Savings", -100), t("o2", "PayPal", -100), t("i", "Checking", 100)]
    m, s = find_matches(txns, PAIRS, WORDS)
    assert m == [] and s


def test_two_transfers_same_amount_on_different_days():
    txns = [t("o1", "Savings", -200), t("i1", "Checking", 200), t("o2", "Savings", -200, 10), t("i2", "Checking", 200, 11)]
    assert sorted(ids(find_matches(txns, PAIRS, WORDS)[0])) == [("o1", "i1"), ("o2", "i2")]


def test_each_side_used_once():
    txns = [t("o1", "Savings", -50), t("i", "Checking", 50), t("o2", "Savings", -50, 3)]
    assert ids(find_matches(txns, PAIRS, WORDS)[0]) == [("o1", "i")]


def test_pair_category_carried():
    m, _ = find_matches([t("o", "Checking", -500), t("i", "Brokerage", 500)], PAIRS, WORDS)
    assert m[0].pair.category == "Investments"
