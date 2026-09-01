from pathlib import Path


APP = Path(__file__).with_name("app.py")


CHECKS = {
    "invoice reminder route": '"/send_invoice_payment_reminder/<int:invoice_id>"',
    "invoice reminder action": "Email reminder",
    "invoice edit route": '"/edit_invoice/<int:invoice_id>"',
    "payment edit route": '"/edit_payment/<int:payment_id>"',
    "ledger edit route": '"/edit_ledger_entry/<int:ledger_id>"',
    "ledger action column": "<th>Action</th>",
    "family workspace label": "Family Workspace",
    "parent billing add entry": "Add billing",
    "messages mark all read": "/messages/mark_all_read",
}


def main():
    source = APP.read_text(encoding="utf-8")
    missing = [name for name, needle in CHECKS.items() if needle not in source]
    if missing:
        print("Regression check failed. Missing:")
        for name in missing:
            print(f"- {name}: {CHECKS[name]}")
        raise SystemExit(1)
    print(f"Regression check passed: {len(CHECKS)} billing/family/message entrypoints present.")


if __name__ == "__main__":
    main()
