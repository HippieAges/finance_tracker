"""Map bank transactions to monthly totals using Plaid categories."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from finance_tracker.model import Category, CategoryType

# Plaid personal_finance_category.primary values treated as income.
INCOME_PFC_PRIMARIES = {
    "INCOME",
    "TRANSFER_IN",
}


@dataclass
class BankTransaction:
    """Normalized transaction used by the categorizer."""

    date: date
    amount: float  # Plaid convention: positive = money leaving the account
    name: str
    merchant_name: Optional[str] = None
    pending: bool = False
    pfc_primary: Optional[str] = None
    pfc_detailed: Optional[str] = None
    institution: Optional[str] = None


@dataclass
class CategoryTotal:
    category: Category
    amount: float


def humanize_plaid_category(raw: str) -> str:
    """FOOD_AND_DRINK → Food And Drink."""
    text = str(raw).strip()
    if not text:
        return "Uncategorized"
    return " ".join(part.capitalize() for part in text.replace("-", "_").split("_"))


def plaid_category_name(txn: BankTransaction) -> str:
    """Prefer Plaid detailed category, else primary, else Uncategorized."""
    if txn.pfc_detailed:
        return humanize_plaid_category(txn.pfc_detailed)
    if txn.pfc_primary:
        return humanize_plaid_category(txn.pfc_primary)
    return "Uncategorized"


def plaid_category_type(txn: BankTransaction) -> CategoryType:
    primary = (txn.pfc_primary or "").upper()
    if primary in INCOME_PFC_PRIMARIES:
        return CategoryType.INCOME
    # Plaid: negative amount = money into the account.
    if txn.amount < 0:
        return CategoryType.INCOME
    return CategoryType.EXPENSE


def categorize_transaction(txn: BankTransaction) -> Tuple[str, CategoryType]:
    return plaid_category_name(txn), plaid_category_type(txn)


def sum_month_by_category(
    transactions: Iterable[BankTransaction],
    year: int,
    month: int,
) -> tuple[List[CategoryTotal], int]:
    """
    Sum absolute totals for a calendar month using Plaid categories.

    Returns (category totals sorted income-then-expense, txn_count_included).
    """
    totals: Dict[str, CategoryTotal] = {}
    count = 0

    for txn in transactions:
        if txn.pending:
            continue
        if txn.date.year != year or txn.date.month != month:
            continue
        if txn.amount == 0:
            continue

        name, cat_type = categorize_transaction(txn)
        value = abs(float(txn.amount))
        if name in totals:
            existing = totals[name]
            # Prefer Income if any txn in the bucket is income-typed.
            if cat_type == CategoryType.INCOME:
                existing.category = Category(name, CategoryType.INCOME)
            existing.amount = round(existing.amount + value, 2)
        else:
            totals[name] = CategoryTotal(
                category=Category(name, cat_type),
                amount=round(value, 2),
            )
        count += 1

    ordered = sorted(
        totals.values(),
        key=lambda ct: (
            0 if ct.category.type == CategoryType.INCOME else 1,
            ct.category.name.lower(),
        ),
    )
    return ordered, count
