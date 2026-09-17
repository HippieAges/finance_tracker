"""Map bank transactions to monthly totals using Plaid categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Dict, Iterable, List, Optional, Tuple

from finance_tracker.model import Category, CategoryType

# Plaid personal_finance_category.primary values treated as income.
INCOME_PFC_PRIMARIES = {
    "INCOME",
    "TRANSFER_IN",
}

SALARY_TERMS = {
    "salary",
    "payroll",
    "paycheck",
    "direct dep",
    "direct deposit",
    "wages",
    "adp",
    "gusto",
}
INTEREST_TERMS = {
    "interest",
    "interest earned",
    "savings interest",
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
    subcategories: Dict[str, float] = field(default_factory=dict)


def humanize_plaid_category(raw: str) -> str:
    """FOOD_AND_DRINK → Food And Drink."""
    text = str(raw).strip()
    if not text:
        return "Uncategorized"
    return " ".join(part.capitalize() for part in text.replace("-", "_").split("_"))


def _specific_category(primary: Optional[str], detailed: Optional[str]) -> str:
    """
    Return the specific part of Plaid's detailed category.

    Examples:
    FOOD_AND_DRINK_FAST_FOOD -> Fast Food
    MEDICAL_EYE_CARE -> Eye Care
    ENTERTAINMENT_VIDEO_GAMES -> Video Games
    """
    detail = (detailed or "").strip().upper()
    broad = (primary or "").strip().upper()
    if detail and broad and detail.startswith(f"{broad}_"):
        return humanize_plaid_category(detail[len(broad) + 1 :])
    if detail:
        return humanize_plaid_category(detail)
    if broad:
        return humanize_plaid_category(broad)
    return "Uncategorized"


def transaction_label(txn: BankTransaction) -> str:
    """Specific merchant/payee label used as the Excel subcategory row."""
    label = (txn.merchant_name or txn.name or "Uncategorized").strip()
    return " ".join(label.split())


def is_credit_card_payment(txn: BankTransaction) -> bool:
    """Skip card payments so expenses are counted by the purchases themselves."""
    text = " ".join(
        part.lower()
        for part in (
            txn.pfc_primary or "",
            txn.pfc_detailed or "",
            txn.merchant_name or "",
            txn.name or "",
        )
    )
    if "credit_card_payment" in text or "credit card payment" in text:
        return True
    if "payment thank you" in text:
        return True
    if "automatic payment" in text and "credit" in text:
        return True
    return False


def _income_category(txn: BankTransaction) -> Optional[str]:
    text = " ".join(
        part.lower()
        for part in (
            txn.pfc_primary or "",
            txn.pfc_detailed or "",
            txn.merchant_name or "",
            txn.name or "",
        )
    )
    if any(term in text for term in INTEREST_TERMS):
        return "Interest"
    if any(term in text for term in SALARY_TERMS):
        return "Salary"
    return None


def plaid_category_name(txn: BankTransaction) -> str:
    """Use the specific part of Plaid's category for shorter labels."""
    return _specific_category(txn.pfc_primary, txn.pfc_detailed)


def plaid_category_type(txn: BankTransaction) -> CategoryType:
    primary = (txn.pfc_primary or "").upper()
    if primary in INCOME_PFC_PRIMARIES:
        return CategoryType.INCOME
    # Plaid: negative amount = money into the account.
    if txn.amount < 0:
        return CategoryType.INCOME
    return CategoryType.EXPENSE


def categorize_transaction(txn: BankTransaction) -> Optional[Tuple[str, CategoryType]]:
    cat_type = plaid_category_type(txn)
    if cat_type == CategoryType.INCOME:
        income_name = _income_category(txn)
        if income_name is None:
            return None
        return income_name, CategoryType.INCOME
    return plaid_category_name(txn), CategoryType.EXPENSE


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
        if is_credit_card_payment(txn):
            continue
        if txn.date.year != year or txn.date.month != month:
            continue
        if txn.amount == 0:
            continue

        categorized = categorize_transaction(txn)
        if categorized is None:
            continue
        name, cat_type = categorized
        value = abs(float(txn.amount))
        sub_name = transaction_label(txn)
        if name in totals:
            existing = totals[name]
            # Prefer Income if any txn in the bucket is income-typed.
            if cat_type == CategoryType.INCOME:
                existing.category = Category(name, CategoryType.INCOME)
            existing.amount = round(existing.amount + value, 2)
            existing.subcategories[sub_name] = round(
                existing.subcategories.get(sub_name, 0.0) + value,
                2,
            )
        else:
            totals[name] = CategoryTotal(
                category=Category(name, cat_type),
                amount=round(value, 2),
                subcategories={sub_name: round(value, 2)},
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
