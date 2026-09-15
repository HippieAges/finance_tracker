"""CustomTkinter UI for the monthly finance tracker."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Dict, List, Optional

import customtkinter as ctk

from finance_tracker.model import (
    DEFAULT_CATEGORIES,
    MONTH_FULL,
    Category,
    CategoryType,
    MonthEntry,
)
from finance_tracker.bank.categorize import CategoryTotal, sum_month_by_category
from finance_tracker.bank.link_server import run_plaid_link
from finance_tracker.bank.plaid_client import (
    PlaidClient,
    PlaidCredentials,
    linked_institution_summary,
    load_credentials,
    load_enabled_items,
    load_items,
    remove_item,
    save_credentials,
    set_item_enabled,
)
from finance_tracker.storage.gsheets_store import (
    connect_with_oauth,
    connect_with_service_account,
    save_connection_info,
)
from finance_tracker.storage.xlsx_store import XlsxStore


ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

DEFAULT_SAVE_DIR = Path.home() / "Documents" / "finance_tracker"


class ManageBanksDialog(ctk.CTkToplevel):
    """Include/exclude linked banks from import, or remove them entirely."""

    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title("Manage banks")
        self.geometry("560x420")
        self.minsize(520, 360)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._vars: Dict[str, ctk.BooleanVar] = {}

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=16)
        ctk.CTkButton(btn_row, text="Close", width=120, command=self._on_close).pack(
            side="right", padx=8
        )
        ctk.CTkButton(
            btn_row, text="Save inclusion", width=140, command=self._on_save
        ).pack(side="right", padx=8)

        ctk.CTkLabel(
            self,
            text="Uncheck a bank to exclude it from Import month. Remove deletes the link.",
            wraplength=500,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(16, 8))

        self.list_frame = ctk.CTkScrollableFrame(self, label_text="Linked banks")
        self.list_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self._rebuild_list()

        self.update_idletasks()
        self.grab_set()
        self.lift()
        self.wait_window(self)

    def _rebuild_list(self) -> None:
        for child in self.list_frame.winfo_children():
            child.destroy()
        self._vars.clear()
        items = load_items()
        if not items:
            ctk.CTkLabel(self.list_frame, text="No banks linked yet.").pack(anchor="w")
            return
        for item in items:
            row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
            row.pack(fill="x", pady=6)
            var = ctk.BooleanVar(value=item.enabled)
            self._vars[item.item_id] = var
            label = item.institution_name or item.item_id
            ctk.CTkCheckBox(
                row,
                text=f"Include {label}",
                variable=var,
                width=320,
            ).pack(side="left", padx=(0, 8))
            ctk.CTkButton(
                row,
                text="Remove",
                width=90,
                fg_color="#8B3A3A",
                hover_color="#A04545",
                command=lambda iid=item.item_id, name=label: self._remove(iid, name),
            ).pack(side="right")

    def _remove(self, item_id: str, name: str) -> None:
        if not messagebox.askyesno(
            "Remove bank",
            f"Remove “{name}” from this app?\n\n"
            "It will no longer be used for imports until you Connect bank again.",
            parent=self,
        ):
            return
        remove_item(item_id)
        self._rebuild_list()

    def _on_save(self) -> None:
        for item_id, var in self._vars.items():
            set_item_enabled(item_id, bool(var.get()))
        messagebox.showinfo(
            "Manage banks",
            f"Import will use: {linked_institution_summary(enabled_only=True)}",
            parent=self,
        )
        self._on_close()

    def _on_close(self) -> None:
        self.grab_release()
        self.destroy()


class GoogleConnectDialog(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title("Connect Google Sheet")
        self.geometry("520x340")
        self.minsize(520, 340)
        self.resizable(False, False)
        self.result = None
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=16)
        ctk.CTkButton(btn_row, text="Cancel", width=100, command=self._on_cancel).pack(
            side="left", padx=8
        )
        ctk.CTkButton(btn_row, text="Connect", width=100, command=self._on_ok).pack(
            side="right", padx=8
        )

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(16, 0))

        ctk.CTkLabel(body, text="Spreadsheet URL or ID").pack(anchor="w", pady=(0, 4))
        self.sheet_entry = ctk.CTkEntry(body, width=480)
        self.sheet_entry.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(body, text="Auth mode").pack(anchor="w", pady=(0, 4))
        self.auth_var = ctk.StringVar(value="service_account")
        ctk.CTkOptionMenu(
            body,
            variable=self.auth_var,
            values=["service_account", "oauth"],
            width=480,
        ).pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(body, text="Credentials JSON file").pack(anchor="w", pady=(0, 4))
        cred_row = ctk.CTkFrame(body, fg_color="transparent")
        cred_row.pack(fill="x")
        self.cred_entry = ctk.CTkEntry(cred_row, width=360)
        self.cred_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(cred_row, text="Browse…", width=100, command=self._browse).pack(
            side="left", padx=(8, 0)
        )

        self.update_idletasks()
        self.grab_set()
        self.lift()
        self.wait_window(self)

    def _browse(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select Google credentials JSON",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.cred_entry.delete(0, tk.END)
            self.cred_entry.insert(0, path)

    def _on_cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()

    def _on_ok(self) -> None:
        sheet = self.sheet_entry.get().strip()
        creds = self.cred_entry.get().strip()
        if not sheet or not creds:
            messagebox.showerror(
                "Invalid",
                "Spreadsheet and credentials path are required.",
                parent=self,
            )
            return
        if not Path(creds).exists():
            messagebox.showerror("Invalid", "Credentials file not found.", parent=self)
            return
        self.result = {
            "spreadsheet": sheet,
            "credentials": creds,
            "auth_mode": self.auth_var.get(),
        }
        self.grab_release()
        self.destroy()


class PlaidSettingsDialog(ctk.CTkToplevel):
    def __init__(self, master: ctk.CTk) -> None:
        super().__init__(master)
        self.title("Plaid settings")
        self.geometry("520x340")
        self.minsize(520, 340)
        self.resizable(False, False)
        self.result: Optional[PlaidCredentials] = None
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        existing = load_credentials()

        btn_row = ctk.CTkFrame(self, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=16, pady=16)
        ctk.CTkButton(btn_row, text="Cancel", width=120, command=self._on_cancel).pack(
            side="left", padx=8
        )
        ctk.CTkButton(btn_row, text="Save", width=120, command=self._on_save).pack(
            side="right", padx=8
        )

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=(16, 0))

        ctk.CTkLabel(
            body,
            text="Create keys at https://dashboard.plaid.com — never commit them to git.",
            wraplength=480,
            justify="left",
        ).pack(anchor="w", pady=(0, 12))

        ctk.CTkLabel(body, text="Client ID").pack(anchor="w", pady=(0, 4))
        self.client_entry = ctk.CTkEntry(body, width=480)
        self.client_entry.pack(fill="x", pady=(0, 8))
        if existing:
            self.client_entry.insert(0, existing.client_id)

        ctk.CTkLabel(body, text="Secret").pack(anchor="w", pady=(0, 4))
        self.secret_entry = ctk.CTkEntry(body, width=480, show="*")
        self.secret_entry.pack(fill="x", pady=(0, 8))
        if existing:
            self.secret_entry.insert(0, existing.secret)

        ctk.CTkLabel(body, text="Environment").pack(anchor="w", pady=(0, 4))
        self.env_var = ctk.StringVar(value=(existing.env if existing else "sandbox"))
        ctk.CTkOptionMenu(
            body,
            variable=self.env_var,
            values=["sandbox", "development", "production"],
            width=480,
        ).pack(fill="x")

        self.update_idletasks()
        self.grab_set()
        self.lift()
        self.wait_window(self)

    def _on_cancel(self) -> None:
        self.result = None
        self.grab_release()
        self.destroy()

    def _on_save(self) -> None:
        client_id = self.client_entry.get().strip()
        secret = self.secret_entry.get().strip()
        env = self.env_var.get().strip().lower()
        if not client_id or not secret:
            messagebox.showerror(
                "Invalid", "Client ID and secret are required.", parent=self
            )
            return
        self.result = PlaidCredentials(client_id=client_id, secret=secret, env=env)
        self.grab_release()
        self.destroy()


class FinanceApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Monthly Finance Tracker")
        self.geometry("780x720")
        self.minsize(680, 600)

        DEFAULT_SAVE_DIR.mkdir(parents=True, exist_ok=True)

        self.store: Optional[object] = None
        self.categories: List[Category] = list(DEFAULT_CATEGORIES)
        self.amount_vars: Dict[str, ctk.StringVar] = {}
        self.amount_entries: Dict[str, ctk.CTkEntry] = {}

        today = date.today()
        self.month_var = ctk.StringVar(value=MONTH_FULL[today.month - 1])
        self.year_var = ctk.StringVar(value=str(today.year))
        self.status_var = ctk.StringVar(
            value="Connect bank → Import month (Plaid categories) → Save to spreadsheet."
        )
        self.dest_var = ctk.StringVar(value="No destination selected")

        self._build_toolbar()
        self._build_period()
        self._build_form()
        self._build_footer()

    def _build_toolbar(self) -> None:
        bar = ctk.CTkFrame(self)
        bar.pack(fill="x", padx=16, pady=(16, 8))

        ctk.CTkButton(bar, text="New file", width=100, command=self._new_file).pack(
            side="left", padx=3
        )
        ctk.CTkButton(bar, text="Open .xlsx", width=100, command=self._open_file).pack(
            side="left", padx=3
        )
        ctk.CTkButton(
            bar, text="Google Sheet", width=110, command=self._connect_gsheets
        ).pack(side="left", padx=3)

        bank_bar = ctk.CTkFrame(self)
        bank_bar.pack(fill="x", padx=16, pady=(0, 8))
        ctk.CTkButton(
            bank_bar, text="Plaid settings…", width=130, command=self._plaid_settings
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            bank_bar, text="Connect bank…", width=130, command=self._connect_bank
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            bank_bar, text="Manage banks…", width=130, command=self._manage_banks
        ).pack(side="left", padx=3)
        ctk.CTkButton(
            bank_bar,
            text="Import month from bank",
            width=180,
            command=self._import_month_from_bank,
        ).pack(side="left", padx=3)

        ctk.CTkLabel(self, textvariable=self.dest_var, anchor="w").pack(
            fill="x", padx=20, pady=(0, 4)
        )

    def _build_period(self) -> None:
        period = ctk.CTkFrame(self, fg_color="transparent")
        period.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(period, text="Month").pack(side="left", padx=(0, 8))
        ctk.CTkOptionMenu(
            period,
            variable=self.month_var,
            values=MONTH_FULL,
            width=140,
            command=lambda _v: self._try_prefill(),
        ).pack(side="left", padx=(0, 16))

        ctk.CTkLabel(period, text="Year").pack(side="left", padx=(0, 8))
        years = [str(y) for y in range(date.today().year - 5, date.today().year + 3)]
        ctk.CTkOptionMenu(
            period,
            variable=self.year_var,
            values=years,
            width=100,
            command=lambda _v: self._try_prefill(),
        ).pack(side="left")

    def _build_form(self) -> None:
        self.form_frame = ctk.CTkScrollableFrame(self, label_text="Monthly amounts")
        self.form_frame.pack(fill="both", expand=True, padx=16, pady=8)
        self._rebuild_amount_fields()

    def _rebuild_amount_fields(self) -> None:
        for child in self.form_frame.winfo_children():
            child.destroy()
        self.amount_vars.clear()
        self.amount_entries.clear()

        if not self.categories:
            ctk.CTkLabel(
                self.form_frame,
                text="No categories yet.\nConnect a bank and click Import month from bank\nto load Plaid’s income/expense categories.",
                justify="left",
            ).pack(anchor="w", padx=8, pady=16)
            return

        columns = ctk.CTkFrame(self.form_frame, fg_color="transparent")
        columns.pack(fill="both", expand=True)

        income_col = ctk.CTkFrame(columns, fg_color="transparent")
        expense_col = ctk.CTkFrame(columns, fg_color="transparent")
        income_col.pack(side="left", fill="both", expand=True, padx=(0, 12))
        expense_col.pack(side="left", fill="both", expand=True, padx=(12, 0))

        ctk.CTkLabel(
            income_col, text="Income", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 8))
        ctk.CTkLabel(
            expense_col, text="Expenses", font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", pady=(0, 8))

        for cat in self.categories:
            parent = income_col if cat.type == CategoryType.INCOME else expense_col
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", pady=3)
            ctk.CTkLabel(row, text=cat.name, width=220, anchor="w").pack(side="left")
            var = ctk.StringVar(value="")
            entry = ctk.CTkEntry(row, textvariable=var, width=120)
            entry.pack(side="left")
            self.amount_vars[cat.name] = var
            self.amount_entries[cat.name] = entry

    def _build_footer(self) -> None:
        footer = ctk.CTkFrame(self, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(0, 8))

        ctk.CTkButton(
            footer, text="Save to spreadsheet", width=180, command=self._save
        ).pack(side="right")

        ctk.CTkLabel(
            self,
            textvariable=self.status_var,
            anchor="w",
            wraplength=720,
            justify="left",
        ).pack(fill="x", padx=20, pady=(0, 16))

    def _selected_month_number(self) -> int:
        return MONTH_FULL.index(self.month_var.get()) + 1

    def _selected_year(self) -> int:
        return int(self.year_var.get())

    def _entry_text(self, name: str) -> str:
        """Read the live text from a category field."""
        entry = self.amount_entries.get(name)
        if entry is not None:
            try:
                return entry.get().strip()
            except Exception:
                pass
        var = self.amount_vars.get(name)
        return var.get().strip() if var is not None else ""

    def _collect_amounts(self) -> Dict[str, float]:
        amounts: Dict[str, float] = {}
        for name in self.amount_vars:
            raw = self._entry_text(name)
            if not raw:
                continue
            try:
                value = float(raw.replace(",", "").replace("$", ""))
            except ValueError as exc:
                raise ValueError(f"Invalid amount for {name}: {raw}") from exc
            if value < 0:
                raise ValueError(f"Amount for {name} cannot be negative.")
            amounts[name] = value
        return amounts

    def _normalize_xlsx_path(self, path: str) -> Path:
        p = Path(path).expanduser()
        if p.suffix.lower() != ".xlsx":
            p = p.with_suffix(".xlsx")
        return p.resolve()

    def _set_store(self, store: object, label: str) -> None:
        self.store = store
        self.dest_var.set(label)
        year = self._selected_year()
        layout = store.load_year(year)  # type: ignore[attr-defined]
        if layout is None:
            years = store.list_years()  # type: ignore[attr-defined]
            if years:
                layout = store.load_year(years[-1])  # type: ignore[attr-defined]
        if layout and layout.categories:
            self.categories = list(layout.categories)
            self._rebuild_amount_fields()
        self._try_prefill()
        self.status_var.set(f"Ready: {label}")

    def _new_file(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Create finance workbook",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialdir=str(DEFAULT_SAVE_DIR),
            initialfile="finances.xlsx",
        )
        if not path:
            return

        target = self._normalize_xlsx_path(path)
        store = XlsxStore(target)
        self.categories = list(DEFAULT_CATEGORIES)
        self._rebuild_amount_fields()

        try:
            store.create_workbook(self._selected_year(), self.categories)
        except Exception as exc:
            messagebox.showerror(
                "Create failed",
                f"Could not create workbook:\n{target}\n\n{exc}",
                parent=self,
            )
            return

        self._set_store(store, f"New .xlsx → {store.describe()}")
        self.status_var.set(f"Created workbook at {store.describe()}")
        messagebox.showinfo(
            "Workbook created",
            f"Created:\n{store.describe()}\n\n"
            "Import month from bank to load Plaid categories, then Save to spreadsheet.",
            parent=self,
        )

    def _open_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Open finance workbook",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
            initialdir=str(DEFAULT_SAVE_DIR),
        )
        if not path:
            return
        store = XlsxStore(path)
        self._set_store(store, f"Open .xlsx → {store.describe()}")

    def _ensure_xlsx_destination(self) -> bool:
        """If no store is set, ask where to save a new workbook."""
        if self.store is not None:
            return True

        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save finance workbook",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialdir=str(DEFAULT_SAVE_DIR),
            initialfile="finances.xlsx",
        )
        if not path:
            return False

        target = self._normalize_xlsx_path(path)
        store = XlsxStore(target)
        try:
            if not target.exists():
                store.create_workbook(self._selected_year(), self.categories)
        except Exception as exc:
            messagebox.showerror(
                "Create failed",
                f"Could not create workbook:\n{target}\n\n{exc}",
                parent=self,
            )
            return False

        self._set_store(store, f".xlsx → {store.describe()}")
        return True

    def _connect_gsheets(self) -> None:
        dialog = GoogleConnectDialog(self)
        if not dialog.result:
            return
        info = dialog.result
        try:
            if info["auth_mode"] == "oauth":
                store = connect_with_oauth(info["credentials"], info["spreadsheet"])
            else:
                store = connect_with_service_account(
                    info["credentials"], info["spreadsheet"]
                )
            save_connection_info(
                store.spreadsheet_id, info["auth_mode"], info["credentials"]
            )
        except Exception as exc:
            messagebox.showerror("Google Sheets", f"Could not connect:\n{exc}", parent=self)
            return
        self._set_store(store, store.describe())

    def _apply_plaid_totals(self, category_totals: List[CategoryTotal]) -> None:
        """Replace form categories with Plaid totals from the import."""
        self.categories = [ct.category for ct in category_totals]
        self._rebuild_amount_fields()
        amounts = {ct.category.name: ct.amount for ct in category_totals}
        for name, var in self.amount_vars.items():
            val = amounts.get(name, 0.0)
            text = f"{val:g}" if val else ""
            var.set(text)
            entry = self.amount_entries.get(name)
            if entry is not None:
                entry.delete(0, tk.END)
                if text:
                    entry.insert(0, text)

    def _plaid_settings(self) -> None:
        dialog = PlaidSettingsDialog(self)
        if dialog.result is None:
            return
        try:
            save_credentials(dialog.result)
        except Exception as exc:
            messagebox.showerror("Plaid settings", str(exc), parent=self)
            return
        self.status_var.set(f"Saved Plaid credentials ({dialog.result.env}).")
        messagebox.showinfo(
            "Plaid settings",
            f"Saved credentials for env “{dialog.result.env}”.",
            parent=self,
        )

    def _manage_banks(self) -> None:
        ManageBanksDialog(self)
        self.status_var.set(
            f"Banks for import: {linked_institution_summary(enabled_only=True)}"
        )

    def _connect_bank(self) -> None:
        if load_credentials() is None:
            messagebox.showerror(
                "Plaid",
                "Add your Plaid client ID and secret under Plaid settings first.",
                parent=self,
            )
            return
        self.status_var.set("Starting Plaid Link in your browser…")
        self.update_idletasks()
        try:
            client = PlaidClient()
            link_token = client.create_link_token()
            public_token, institution, error = run_plaid_link(link_token)
            if not public_token:
                messagebox.showerror(
                    "Plaid Link",
                    error or "No public token received. Try Connect bank again.",
                    parent=self,
                )
                self.status_var.set("Bank connect cancelled or failed.")
                return
            item = client.exchange_public_token(public_token, institution_name=institution)
        except Exception as exc:
            messagebox.showerror("Plaid Link", str(exc), parent=self)
            self.status_var.set(f"Bank connect failed: {exc}")
            return

        summary = linked_institution_summary(enabled_only=False)
        self.status_var.set(f"Linked {item.institution_name}. Banks: {summary}")
        messagebox.showinfo(
            "Bank linked",
            f"Linked: {item.institution_name}\n\n"
            f"All linked banks: {summary}\n\n"
            "Use Manage banks to exclude a bank, then Import month from bank.",
            parent=self,
        )

    def _import_month_from_bank(self) -> None:
        if load_credentials() is None:
            messagebox.showerror(
                "Plaid",
                "Add your Plaid client ID and secret under Plaid settings first.",
                parent=self,
            )
            return
        if not load_items():
            messagebox.showerror(
                "Plaid",
                "No banks linked yet. Click Connect bank… first.",
                parent=self,
            )
            return
        if not load_enabled_items():
            messagebox.showerror(
                "Plaid",
                "All linked banks are excluded.\n\n"
                "Open Manage banks… and check at least one bank to include.",
                parent=self,
            )
            return

        year = self._selected_year()
        month = self._selected_month_number()
        month_name = self.month_var.get()
        self.status_var.set(f"Importing {month_name} {year} from bank…")
        self.update_idletasks()

        try:
            client = PlaidClient()
            txns = client.fetch_month_transactions(year, month)
            category_totals, count = sum_month_by_category(txns, year, month)
        except Exception as exc:
            messagebox.showerror("Bank import", str(exc), parent=self)
            self.status_var.set(f"Import failed: {exc}")
            return

        if count == 0 or not category_totals:
            messagebox.showinfo(
                "Bank import",
                f"No posted transactions found for {month_name} {year}.\n\n"
                "If you just linked, wait a minute and try again.",
                parent=self,
            )
            self.status_var.set(f"No transactions for {month_name} {year}.")
            return

        self._apply_plaid_totals(category_totals)
        banks = linked_institution_summary(enabled_only=True)
        summary = ", ".join(
            f"{ct.category.name} {ct.amount:g}" for ct in category_totals
        )
        self.status_var.set(f"Imported {count} txns from {banks} → {summary}")
        messagebox.showinfo(
            "Bank import",
            f"Imported {count} transactions for {month_name} {year}\n"
            f"from {banks}.\n\nCategories are from Plaid:\n{summary}\n\n"
            "Review the form, edit if needed, then Save to spreadsheet.",
            parent=self,
        )

    def _try_prefill(self) -> None:
        if self.store is None:
            return
        year = self._selected_year()
        month = self._selected_month_number()
        layout = self.store.load_year(year)  # type: ignore[attr-defined]
        if layout is None:
            for var in self.amount_vars.values():
                var.set("")
            return
        if layout.categories:
            self.categories = list(layout.categories)
            self._rebuild_amount_fields()

        amounts = layout.get_month_amounts(month)
        for name, var in self.amount_vars.items():
            if name in amounts:
                val = amounts[name]
                text = str(int(val)) if float(val).is_integer() else str(val)
            else:
                text = ""
            var.set(text)
            entry = self.amount_entries.get(name)
            if entry is not None:
                entry.delete(0, tk.END)
                if text:
                    entry.insert(0, text)

    def _save(self) -> None:
        # Capture typed values first, before any dialogs/UI refreshes.
        try:
            amounts = self._collect_amounts()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc), parent=self)
            return
        if not amounts:
            messagebox.showerror(
                "Invalid input",
                "Import month from bank first (or enter at least one amount), then save.",
                parent=self,
            )
            return

        if not self._ensure_xlsx_destination():
            return

        entry = MonthEntry(
            year=self._selected_year(),
            month=self._selected_month_number(),
            amounts=amounts,
        )
        try:
            layout = self.store.save_month(entry, categories=self.categories)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return

        month_name = self.month_var.get()
        dest = self.store.describe()  # type: ignore[attr-defined]
        written = ", ".join(f"{k}={v:g}" for k, v in sorted(amounts.items()))
        self.dest_var.set(f"Saved → {dest}")
        self.status_var.set(
            f"Wrote {month_name} {entry.year} ({written}) → {dest}"
        )
        # Refresh fields from disk so the UI matches the file.
        self._try_prefill()
        messagebox.showinfo(
            "Saved",
            f"Wrote {month_name} {entry.year} to sheet {layout.year}.\n\n"
            f"Values: {written}\n\nFile:\n{dest}",
            parent=self,
        )


def main() -> None:
    app = FinanceApp()
    app.mainloop()


if __name__ == "__main__":
    main()
