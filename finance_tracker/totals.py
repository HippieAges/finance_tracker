"""Formula helpers for month and year totals."""

from __future__ import annotations

from typing import List, Tuple

from finance_tracker.model import (
    Category,
    CategoryType,
    EXPENSE_TOTAL_LABEL,
    HEADER_CATEGORY,
    HEADER_TYPE,
    INCOME_TOTAL_LABEL,
    NET_LABEL,
    YEAR_COLUMN_LABEL,
    YearSheetLayout,
    column_letter,
)


def header_row(months: List[str]) -> List[str]:
    return [HEADER_CATEGORY, HEADER_TYPE, *months, YEAR_COLUMN_LABEL]


def first_month_col() -> int:
    """1-based column index of the first month column."""
    return 3  # A=Category, B=Type, C=first month


def year_col_index(month_count: int) -> int:
    """1-based column index of the Year column."""
    return first_month_col() + month_count


def category_row_range(category_count: int) -> Tuple[int, int]:
    """1-based inclusive start/end row indices for category data rows."""
    start = 2  # row 1 is header
    end = start + category_count - 1
    return start, end


def total_row_indices(category_count: int) -> Tuple[int, int, int]:
    """1-based row indices for Income total, Expense total, Net."""
    start, end = category_row_range(category_count)
    income_total = end + 1
    expense_total = end + 2
    net = end + 3
    return income_total, expense_total, net


def sum_formula(row: int, month_count: int) -> str:
    if month_count <= 0:
        return "0"
    start_col = column_letter(first_month_col())
    end_col = column_letter(first_month_col() + month_count - 1)
    return f"=SUM({start_col}{row}:{end_col}{row})"


def income_expense_row_numbers(categories: List[Category]) -> Tuple[List[int], List[int]]:
    income_rows: List[int] = []
    expense_rows: List[int] = []
    for i, cat in enumerate(categories):
        row = 2 + i
        if cat.type == CategoryType.INCOME:
            income_rows.append(row)
        else:
            expense_rows.append(row)
    return income_rows, expense_rows


def sum_rows_formula(rows: List[int], col_letter: str) -> str:
    if not rows:
        return "0"
    if len(rows) == 1:
        return f"={col_letter}{rows[0]}"
    parts = "+".join(f"{col_letter}{r}" for r in rows)
    return f"={parts}"


def build_sheet_grid(layout: YearSheetLayout) -> List[List[object]]:
    """
    Build a 2D grid of cell values/formulas for a year sheet.

    Rows: header, categories, Income total, Expense total, Net.
    Columns: Category, Type, months..., Year.
    """
    months = layout.months
    month_count = len(months)
    cats = layout.categories
    income_rows, expense_rows = income_expense_row_numbers(cats)
    income_total_row, expense_total_row, net_row = total_row_indices(len(cats))

    grid: List[List[object]] = [header_row(months)]

    for i, cat in enumerate(cats):
        row_num = 2 + i
        row: List[object] = [cat.name, cat.type.value]
        cat_amounts = layout.amounts.get(cat.name, {})
        for m in months:
            val = cat_amounts.get(m)
            row.append(float(val) if val is not None else None)
        row.append(sum_formula(row_num, month_count))
        grid.append(row)

    # Total rows
    for label, rows in (
        (INCOME_TOTAL_LABEL, income_rows),
        (EXPENSE_TOTAL_LABEL, expense_rows),
    ):
        total_row: List[object] = [label, ""]
        for col_offset in range(month_count):
            col = column_letter(first_month_col() + col_offset)
            total_row.append(sum_rows_formula(rows, col))
        year_col = column_letter(year_col_index(month_count))
        total_row.append(sum_rows_formula(rows, year_col))
        grid.append(total_row)

    # Net = Income total - Expense total for each month column and Year
    net_row_values: List[object] = [NET_LABEL, ""]
    for col_offset in range(month_count + 1):  # months + Year
        col = column_letter(first_month_col() + col_offset)
        net_row_values.append(f"={col}{income_total_row}-{col}{expense_total_row}")
    grid.append(net_row_values)

    return grid


def parse_amount(value: object) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text.startswith("="):
        return None
    try:
        return float(text)
    except ValueError:
        return None
