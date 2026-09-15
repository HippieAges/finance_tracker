"""Google Sheets store via gspread."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional

import gspread
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google.oauth2.service_account import Credentials as ServiceAccountCredentials
from google_auth_oauthlib.flow import InstalledAppFlow

from finance_tracker.model import (
    META_SHEET_NAME,
    TOTAL_LABELS,
    Category,
    CategoryType,
    DEFAULT_CATEGORIES,
    MONTH_ABBREV,
    MonthEntry,
    YEAR_COLUMN_LABEL,
    YearSheetLayout,
)
from finance_tracker.totals import build_sheet_grid, parse_amount

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

CONFIG_DIR = Path.home() / ".config" / "finance_tracker"
TOKEN_PATH = CONFIG_DIR / "google_token.json"


class GSheetsStore:
    def __init__(self, spreadsheet_id: str, client: gspread.Client) -> None:
        self.spreadsheet_id = spreadsheet_id
        self.client = client
        self._ss = client.open_by_key(spreadsheet_id)

    def describe(self) -> str:
        try:
            title = self._ss.title
        except Exception:
            title = self.spreadsheet_id
        return f"Google Sheet: {title} ({self.spreadsheet_id})"

    def list_years(self) -> List[int]:
        years: List[int] = []
        for ws in self._ss.worksheets():
            if ws.title == META_SHEET_NAME:
                continue
            if ws.title.isdigit():
                years.append(int(ws.title))
        return sorted(years)

    def load_year(self, year: int) -> Optional[YearSheetLayout]:
        try:
            ws = self._ss.worksheet(str(year))
        except gspread.WorksheetNotFound:
            return None
        return self._read_sheet(ws, year)

    def save_month(
        self,
        entry: MonthEntry,
        categories: Optional[List[Category]] = None,
    ) -> YearSheetLayout:
        layout = self._prepare_year(entry.year, categories)
        layout.apply_month(entry)
        self._write_layout(layout)
        self._touch_meta()
        return layout

    def add_category(self, year: int, category: Category) -> YearSheetLayout:
        layout = self._prepare_year(year, None)
        layout.add_category(category)
        self._write_layout(layout)
        self._touch_meta()
        return layout

    def _prepare_year(
        self,
        year: int,
        categories: Optional[List[Category]],
    ) -> YearSheetLayout:
        name = str(year)
        try:
            ws = self._ss.worksheet(name)
            layout = self._read_sheet(ws, year)
            if categories:
                layout.ensure_categories(categories)
            return layout
        except gspread.WorksheetNotFound:
            pass

        template = categories or self._template_categories() or list(DEFAULT_CATEGORIES)
        layout = YearSheetLayout(year=year, categories=list(template), months=[], amounts={})
        layout.ensure_categories(template)
        self._ss.add_worksheet(title=name, rows=50, cols=20)
        return layout

    def _template_categories(self) -> Optional[List[Category]]:
        years = self.list_years()
        if not years:
            return None
        layout = self.load_year(years[-1])
        return list(layout.categories) if layout else None

    def _read_sheet(self, ws: gspread.Worksheet, year: int) -> YearSheetLayout:
        rows = ws.get_all_values()
        if not rows:
            return YearSheetLayout(year=year)

        header = rows[0]
        months: List[str] = []
        for cell in header[2:]:
            if cell in MONTH_ABBREV:
                months.append(cell)
            elif cell == YEAR_COLUMN_LABEL:
                break

        categories: List[Category] = []
        amounts: dict = {}
        for row in rows[1:]:
            if not row or not row[0]:
                continue
            name = str(row[0]).strip()
            if name in TOTAL_LABELS:
                break
            type_raw = str(row[1]).strip() if len(row) > 1 and row[1] else "Expense"
            try:
                cat_type = CategoryType(type_raw)
            except ValueError:
                cat_type = CategoryType.EXPENSE
            categories.append(Category(name, cat_type))
            cat_amounts: dict = {}
            for i, month in enumerate(months):
                col_idx = 2 + i
                if col_idx < len(row):
                    parsed = parse_amount(row[col_idx])
                    if parsed is not None:
                        cat_amounts[month] = parsed
            amounts[name] = cat_amounts

        if not categories:
            categories = list(DEFAULT_CATEGORIES)

        return YearSheetLayout(
            year=year,
            categories=categories,
            months=months,
            amounts=amounts,
        )

    def _write_layout(self, layout: YearSheetLayout) -> None:
        name = str(layout.year)
        try:
            ws = self._ss.worksheet(name)
        except gspread.WorksheetNotFound:
            ws = self._ss.add_worksheet(title=name, rows=50, cols=20)

        grid = build_sheet_grid(layout)
        # Convert None to empty string for Sheets API
        values: List[List[Any]] = [
            ["" if v is None else v for v in row] for row in grid
        ]
        ws.clear()
        # USER_ENTERED so formulas (e.g. =SUM(...)) are stored as formulas.
        ws.update(values, value_input_option="USER_ENTERED")

    def _touch_meta(self) -> None:
        try:
            ws = self._ss.worksheet(META_SHEET_NAME)
        except gspread.WorksheetNotFound:
            ws = self._ss.add_worksheet(title=META_SHEET_NAME, rows=10, cols=5)
        ws.update(
            [["last_updated", datetime.now(timezone.utc).isoformat()]],
            value_input_option="USER_ENTERED",
        )


def extract_spreadsheet_id(url_or_id: str) -> str:
    text = url_or_id.strip()
    if "/d/" in text:
        # https://docs.google.com/spreadsheets/d/<ID>/edit...
        part = text.split("/d/", 1)[1]
        return part.split("/", 1)[0]
    return text


def connect_with_service_account(credentials_path: str | Path, spreadsheet_id: str) -> GSheetsStore:
    creds = ServiceAccountCredentials.from_service_account_file(
        str(credentials_path),
        scopes=SCOPES,
    )
    client = gspread.authorize(creds)
    return GSheetsStore(extract_spreadsheet_id(spreadsheet_id), client)


def connect_with_oauth(client_secrets_path: str | Path, spreadsheet_id: str) -> GSheetsStore:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    creds: Optional[Credentials] = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    elif not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), SCOPES)
        creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    client = gspread.authorize(creds)
    return GSheetsStore(extract_spreadsheet_id(spreadsheet_id), client)


def save_connection_info(spreadsheet_id: str, auth_mode: str, credentials_path: str) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    info = {
        "spreadsheet_id": spreadsheet_id,
        "auth_mode": auth_mode,
        "credentials_path": credentials_path,
    }
    (CONFIG_DIR / "gsheets_connection.json").write_text(
        json.dumps(info, indent=2),
        encoding="utf-8",
    )
