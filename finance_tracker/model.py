"""Shared schema for year worksheets and default categories."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


MONTH_ABBREV = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]

MONTH_FULL = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


class CategoryType(str, Enum):
    INCOME = "Income"
    EXPENSE = "Expense"


INCOME_TOTAL_LABEL = "Income total"
EXPENSE_TOTAL_LABEL = "Expense total"
NET_LABEL = "Net"
YEAR_COLUMN_LABEL = "Year"
HEADER_CATEGORY = "Category"
HEADER_TYPE = "Type"
TOTAL_LABELS = {INCOME_TOTAL_LABEL, EXPENSE_TOTAL_LABEL, NET_LABEL}
META_SHEET_NAME = "Meta"


@dataclass
class Category:
    name: str
    type: CategoryType


DEFAULT_CATEGORIES: List[Category] = []
# Categories come from Plaid personal_finance_category on import.


@dataclass
class MonthEntry:
    """Amounts for one calendar month keyed by category name."""

    year: int
    month: int  # 1-12
    amounts: Dict[str, float] = field(default_factory=dict)

    @property
    def month_label(self) -> str:
        return MONTH_ABBREV[self.month - 1]

    @property
    def sheet_name(self) -> str:
        return str(self.year)


def month_sort_key(label: str) -> int:
    try:
        return MONTH_ABBREV.index(label)
    except ValueError:
        return 99


def ordered_month_labels(existing: List[str], new_label: str) -> List[str]:
    """Return month labels in calendar order, inserting new_label if missing."""
    labels = set(existing)
    labels.add(new_label)
    return sorted(labels, key=month_sort_key)


def column_letter(col_1based: int) -> str:
    """Convert 1-based column index to Excel column letter(s)."""
    result = []
    n = col_1based
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result.append(chr(65 + rem))
    return "".join(reversed(result))


@dataclass
class YearSheetLayout:
    """In-memory representation of one year sheet."""

    year: int
    categories: List[Category] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    months: List[str] = field(default_factory=list)
    # amounts[category_name][month_label] = float
    amounts: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def ensure_categories(self, categories: Optional[List[Category]] = None) -> None:
        cats = categories or DEFAULT_CATEGORIES
        known = {c.name for c in self.categories}
        for cat in cats:
            if cat.name not in known:
                self.categories.append(cat)
                known.add(cat.name)
            self.amounts.setdefault(cat.name, {})

    def apply_month(self, entry: MonthEntry) -> None:
        if entry.year != self.year:
            raise ValueError(f"Entry year {entry.year} does not match sheet {self.year}")
        label = entry.month_label
        self.months = ordered_month_labels(self.months, label)
        for cat in self.categories:
            self.amounts.setdefault(cat.name, {})
            if cat.name in entry.amounts:
                value = entry.amounts[cat.name]
                if value is None or value == "":
                    continue
                self.amounts[cat.name][label] = float(value)

    def get_month_amounts(self, month: int) -> Dict[str, float]:
        label = MONTH_ABBREV[month - 1]
        result: Dict[str, float] = {}
        for cat in self.categories:
            val = self.amounts.get(cat.name, {}).get(label)
            if val is not None:
                result[cat.name] = float(val)
        return result

    def add_category(self, category: Category) -> None:
        if any(c.name == category.name for c in self.categories):
            raise ValueError(f"Category already exists: {category.name}")
        self.categories.append(category)
        self.amounts.setdefault(category.name, {})
