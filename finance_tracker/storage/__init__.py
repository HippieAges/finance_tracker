"""Storage protocol for spreadsheet backends."""

from __future__ import annotations

from typing import List, Optional, Protocol

from finance_tracker.model import Category, MonthEntry, YearSheetLayout


class SpreadsheetStore(Protocol):
    """Read/write monthly finances into a year-oriented spreadsheet."""

    def describe(self) -> str:
        """Human-readable destination label for status messages."""
        ...

    def list_years(self) -> List[int]:
        ...

    def load_year(self, year: int) -> Optional[YearSheetLayout]:
        """Return layout for year, or None if the sheet does not exist."""
        ...

    def save_month(
        self,
        entry: MonthEntry,
        categories: Optional[List[Category]] = None,
    ) -> YearSheetLayout:
        """
        Create or update the year sheet and write the month column.
        Returns the updated layout.
        """
        ...

    def add_category(self, year: int, category: Category) -> YearSheetLayout:
        ...
