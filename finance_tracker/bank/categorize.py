"""Map bank transactions to monthly category totals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional

from finance_tracker.bank.rules import load_rules


@dataclass
class BankTransaction:
    """Normalized transaction used by the categorizer."""

    date: date
    amount: float  # Plaid convention: positive = money leaving the account
    name: str
    merchant_name: Optional[str] = None
    pending: bool = False
    pfc_primary: Optional[str] = None  # personal_finance_category.primary
    institution: Optional[str] = None


def _match_merchant(text: str, rules: List[tuple[str, str]]) -> Optional[str]:
    hay = text.lower()
    for pattern, category in rules:
        if pattern and pattern in hay:
            return category
    return None


def categorize_transaction(
    txn: BankTransaction,
    rules: Optional[List[tuple[str, str]]] = None,
    pfc_fallback: Optional[Dict[str, str]] = None,
) -> str:
    if rules is None or pfc_fallback is None:
        loaded_rules, loaded_pfc = load_rules()
        rules = rules if rules is not None else loaded_rules
        pfc_fallback = pfc_fallback if pfc_fallback is not None else loaded_pfc

    for text in (txn.merchant_name or "", txn.name or ""):
        if not text:
            continue
        hit = _match_merchant(text, rules)
        if hit:
            return hit

    if txn.pfc_primary:
        mapped = pfc_fallback.get(txn.pfc_primary.upper())
        if mapped:
            return mapped

    # Plaid: positive amount = outflow (expense); negative = inflow (income)
    if txn.amount < 0:
        return "Other income"
    return "Other Expenses"


def sum_month_by_category(
    transactions: Iterable[BankTransaction],
    year: int,
    month: int,
) -> tuple[Dict[str, float], int]:
    """
    Sum absolute category totals for a calendar month.

    Returns (category -> total, txn_count_included).
    Expense categories get positive outflows; income categories get positive inflows.
    """
    rules, pfc_fallback = load_rules()
    totals: Dict[str, float] = {}
    count = 0

    for txn in transactions:
        if txn.pending:
            continue
        if txn.date.year != year or txn.date.month != month:
            continue
        if txn.amount == 0:
            continue

        category = categorize_transaction(txn, rules, pfc_fallback)
        value = abs(float(txn.amount))
        totals[category] = totals.get(category, 0.0) + value
        count += 1

    # Round to cents
    totals = {k: round(v, 2) for k, v in totals.items()}
    return totals, count
