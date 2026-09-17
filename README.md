# Monthly Finance Tracker

A desktop app for tracking monthly income and expenses by category. Import monthly data from linked bank accounts via Plaid, review/edit the amounts, then save to an Excel workbook (`.xlsx`) or a Google Sheet.

## Features

- **Plaid category form** — income and expense fields are generated from Plaid categories returned by import
- **Income filtering** — only Salary and savings Interest income are imported
- **Payment filtering** — credit card payments are omitted so spending is counted by purchase category instead
- **Excel storage** — create or open `.xlsx` workbooks with one sheet per year
- **Google Sheets** — connect via OAuth or a service account and write the same layout remotely
- **Bank import (Plaid)** — link institutions for the current session, pull transactions for a selected month, and use generalized Plaid category names with hidden transaction-name subcategories in Excel

## Requirements

- Python 3.10+ (3.10 and 3.11 tested conceptually; use a current 3.x)
- A desktop environment (Tk / CustomTkinter GUI)
- Optional: [Plaid](https://plaid.com/) API credentials for bank linking
- Optional: Google Cloud OAuth client or service-account JSON for Sheets

## Setup

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python3 -m finance_tracker
```

Or:

```bash
python3 -m finance_tracker.app
```

## Typical workflow

1. Start the app and choose a destination:
   - **New file** / **Open .xlsx** for a local workbook, or
   - **Google Sheet** to connect an existing spreadsheet
2. Pick the **month** and **year**
3. Enter amounts by category, and/or use bank import (below)
4. Click **Save to spreadsheet**

Income total, expense total, and net are computed when data is written to the sheet.
In Excel, imported categories with transaction details have hidden grouped rows underneath them. Expand a category row to see merchant/payee subcategories; the child rows sum to the parent category.

## Bank import (optional)

1. Create a Plaid account and obtain a **client ID** and **secret** (Sandbox is fine for testing).
2. In the app, open **Plaid settings…** and enter your credentials for **this session only** (they are never written to disk; re-enter them after restarting the app).
3. Click **Connect bank…** and complete Plaid Link in the browser.
4. Select the month/year, then **Import month from bank**.
5. Review the prefilled amounts, edit if needed, then save.

Linked bank access tokens are kept in memory for the current session only. Manage Banks starts empty after each app restart. Plaid Client ID and secret are never saved to disk.

## Google Sheets (optional)

Use **Google Sheet** in the toolbar and authenticate with either:

- **OAuth** (installed-app client secrets), or
- A **service account** JSON key with access to the target spreadsheet

OAuth tokens are saved under `~/.config/finance_tracker/`. Spreadsheet layout matches the Excel year-sheet format (categories as rows, months as columns).

## Project layout

```text
finance_tracker/
  app.py              # CustomTkinter UI
  model.py            # Categories, month entries, sheet layout
  totals.py           # Sheet grid / totals helpers
  bank/               # Plaid client, Link helper, categorization rules
  storage/            # .xlsx and Google Sheets backends
requirements.txt
```

## Notes

- Default save directory for new workbooks: `~/Documents/finance_tracker`
- Spreadsheet finance files (e.g. `finances.xlsx`) are gitignored so personal data stays local
- Bank and Google credentials live in `~/.config/finance_tracker/` and should never be committed
