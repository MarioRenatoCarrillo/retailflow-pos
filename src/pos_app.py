import argparse
import sys
import os
import csv
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# -----------------------------
# Data models
# -----------------------------
@dataclass
class Item:
    upc: str
    description: str
    max_qty: int
    order_threshold: int
    replenishment_qty: int
    on_hand: int
    unit_price: float

    def update_on_hand(self, delta: int) -> None:
        self.on_hand += delta


@dataclass
class SaleLine:
    upc: str
    description: str
    unit_price: float
    qty: int


# -----------------------------
# Storage (SQLite) for receipts/sales
# -----------------------------
class SalesStore:
    def __init__(self, db_path: str = "pos.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS receipts (
                    receipt_no INTEGER PRIMARY KEY AUTOINCREMENT,
                    canceled INTEGER NOT NULL DEFAULT 0
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS receipt_lines (
                    receipt_no INTEGER NOT NULL,
                    upc TEXT NOT NULL,
                    description TEXT NOT NULL,
                    unit_price REAL NOT NULL,
                    qty INTEGER NOT NULL,
                    FOREIGN KEY(receipt_no) REFERENCES receipts(receipt_no)
                )
            """)
            conn.commit()

    def create_receipt(self, lines: List[SaleLine]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO receipts(canceled) VALUES (0)")
            receipt_no = cur.lastrowid
            cur.executemany(
                "INSERT INTO receipt_lines(receipt_no, upc, description, unit_price, qty) VALUES (?, ?, ?, ?, ?)",
                [(receipt_no, l.upc, l.description, l.unit_price, l.qty) for l in lines]
            )
            conn.commit()
            return int(receipt_no)

    def get_receipt(self, receipt_no: int) -> Tuple[bool, List[SaleLine]]:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("SELECT canceled FROM receipts WHERE receipt_no = ?", (receipt_no,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Receipt not found")
            canceled = bool(row[0])

            cur.execute("""
                SELECT upc, description, unit_price, qty
                FROM receipt_lines
                WHERE receipt_no = ?
            """, (receipt_no,))
            lines = [SaleLine(upc=r[0], description=r[1], unit_price=float(r[2]), qty=int(r[3]))
                     for r in cur.fetchall()]
            return canceled, lines

    def set_canceled(self, receipt_no: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute("UPDATE receipts SET canceled = 1 WHERE receipt_no = ?", (receipt_no,))
            conn.commit()

    def update_line_qty(self, receipt_no: int, upc: str, new_qty: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            if new_qty <= 0:
                cur.execute(
                    "DELETE FROM receipt_lines WHERE receipt_no = ? AND upc = ?",
                    (receipt_no, upc)
                )
            else:
                cur.execute(
                    "UPDATE receipt_lines SET qty = ? WHERE receipt_no = ? AND upc = ?",
                    (new_qty, receipt_no, upc)
                )
            conn.commit()


# -----------------------------
# POS App
# -----------------------------
class POSApp:
    def __init__(self, users_csv: str, inventory_csv: str, db_path: str = "pos.db") -> None:
        self.users = self.load_users(users_csv)
        self.inventory = self.load_inventory(inventory_csv)
        self.inventory_csv = inventory_csv
        self.sales_store = SalesStore(db_path=db_path)

    # Req 2.1/2.2
    def load_inventory(self, filename: str) -> Dict[str, Item]:
        inv: Dict[str, Item] = {}
        with open(filename, "r", newline="") as f:
            reader = csv.DictReader(f)
            for line_num, row in enumerate(reader, start=2):
                try:
                    upc = row["Item_UPC"].strip()
                    desc = row["Item_Description"].strip()
                    max_qty = int(row["Item_Max_Qty"].strip())
                    threshold = int(row["Item_Order_Threshold"].strip())
                    repl = int(row["Item_Replenishment_Order_Qty"].strip())
                    on_hand = int(row["Item_On_Hand"].strip())
                    price = float(row["Item_Unit_Price"].strip())
                except Exception:
                    # keep it simple: skip bad row
                    continue
                inv[upc] = Item(upc, desc, max_qty, threshold, repl, on_hand, price)
        return inv

    def save_inventory(self) -> None:
        """Optional: persist updated on-hand values back to CSV."""
        fieldnames = [
            "Item_UPC","Item_Description","Item_Max_Qty","Item_Order_Threshold",
            "Item_Replenishment_Order_Qty","Item_On_Hand","Item_Unit_Price"
        ]
        with open(self.inventory_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for it in self.inventory.values():
                writer.writerow({
                    "Item_UPC": it.upc,
                    "Item_Description": it.description,
                    "Item_Max_Qty": it.max_qty,
                    "Item_Order_Threshold": it.order_threshold,
                    "Item_Replenishment_Order_Qty": it.replenishment_qty,
                    "Item_On_Hand": it.on_hand,
                    "Item_Unit_Price": it.unit_price,
                })

    # Users
    def load_users(self, filename: str) -> Dict[str, str]:
        users: Dict[str, str] = {}
        with open(filename, "r", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                users[row["User_ID"].strip()] = row["Password"].strip()
        return users

    # Req 1.1/1.2
    def login(self) -> bool:
        MAX_TRIES = 3
        tries = 0
        while tries < MAX_TRIES:
            print("=== POS SYSTEM LOGIN ===")
            user_id = input("Enter User ID: ").strip()
            password = input("Enter Password: ").strip()
            if user_id in self.users and self.users[user_id] == password:
                print(f"Login successful. Welcome, {user_id}")
                return True
            tries += 1
            print(f"Wrong User ID or password. Attempts left: {MAX_TRIES - tries}")
        print("Too many failed attempts. Locked out.")
        return False

    # Req 3.1 helper
    def show_inventory(self) -> None:
        print("\n=== CURRENT INVENTORY ===")
        print("UPC       | Description                | Price   | On Hand")
        print("--------------------------------------------------------")
        for it in self.inventory.values():
            print(f"{it.upc:9} | {it.description:25} | ${it.unit_price:6.2f} | {it.on_hand:7}")

    # Req 3.1/3.2 helper
    def calc_total(self, lines: List[SaleLine]) -> float:
        return sum(l.unit_price * l.qty for l in lines)

    # Req 3.1/3.2
    def start_sale(self) -> None:
        sale_lines: List[SaleLine] = []

        while True:
            print("\n=== NEW SALE MENU ===")
            print("1. Add item")
            print("2. Remove item")
            print("3. Checkout")
            print("0. Cancel")
            choice = input("Choose: ").strip()

            if choice == "1":
                self.show_inventory()
                upc = input("UPC to add: ").strip()
                if upc not in self.inventory:
                    print("UPC not found.")
                    continue
                item = self.inventory[upc]
                try:
                    qty = int(input("Qty: "))
                except ValueError:
                    print("Qty must be a number.")
                    continue
                if qty <= 0:
                    print("Qty must be positive.")
                    continue
                sale_lines.append(SaleLine(item.upc, item.description, item.unit_price, qty))
                print(f"Running total: ${self.calc_total(sale_lines):.2f}")

            elif choice == "2":
                if not sale_lines:
                    print("No lines to remove.")
                    continue
                for i, l in enumerate(sale_lines, start=1):
                    print(f"{i}. {l.qty} x {l.description} @ ${l.unit_price:.2f}")
                try:
                    idx = int(input("Line # to remove: ")) - 1
                    sale_lines.pop(idx)
                except Exception:
                    print("Invalid selection.")
                print(f"Running total: ${self.calc_total(sale_lines):.2f}")

            elif choice == "3":
                if not sale_lines:
                    print("Empty sale.")
                    return
                total = self.calc_total(sale_lines)
                print(f"Total due: ${total:.2f}")
                while True:
                    try:
                        cash = float(input("Cash received: $"))
                    except ValueError:
                        print("Invalid cash amount.")
                        continue
                    if cash < total:
                        print("Not enough cash.")
                        continue
                    break

                # update inventory
                for l in sale_lines:
                    self.inventory[l.upc].update_on_hand(-l.qty)

                receipt_no = self.sales_store.create_receipt(sale_lines)
                change = cash - total
                print(f"Receipt: {receipt_no} | Change: ${change:.2f}")

                # optional: persist inventory updates
                self.save_inventory()
                return

            elif choice == "0":
                print("Sale canceled.")
                return

            else:
                print("Invalid option.")

    # Req 3.3
    def process_return(self) -> None:
        try:
            receipt_no = int(input("Receipt number: "))
        except ValueError:
            print("Invalid receipt number.")
            return

        try:
            canceled, lines = self.sales_store.get_receipt(receipt_no)
        except ValueError:
            print("Receipt not found.")
            return

        if canceled:
            print("Receipt already fully returned/canceled.")
            return

        print("\nReturn Options:")
        print("1. Cancel entire sale")
        print("2. Return one item")
        choice = input("Choose: ").strip()

        if choice == "1":
            for l in lines:
                self.inventory[l.upc].update_on_hand(l.qty)
            self.sales_store.set_canceled(receipt_no)
            self.save_inventory()
            print("Full return completed.")
            return

        if choice == "2":
            for i, l in enumerate(lines, start=1):
                print(f"{i}. {l.qty} x {l.description} @ ${l.unit_price:.2f} (UPC {l.upc})")
            try:
                idx = int(input("Line # to return from: ")) - 1
                line = lines[idx]
                return_qty = int(input("Qty to return: "))
            except Exception:
                print("Invalid input.")
                return

            if return_qty <= 0 or return_qty > line.qty:
                print("Invalid return quantity.")
                return

            # inventory gets stock back
            self.inventory[line.upc].update_on_hand(return_qty)

            # update receipt line qty
            new_qty = line.qty - return_qty
            self.sales_store.update_line_qty(receipt_no, line.upc, new_qty)

            self.save_inventory()
            print("Partial return completed.")
            return

        print("Invalid option.")

    def run(self) -> None:
        if not self.login():
            return

        while True:
            print("\n=== MAIN MENU ===")
            print("1. Start New Sale")
            print("2. View Inventory")
            print("3. Process Return")
            print("0. Exit")
            choice = input("Choose: ").strip()

            if choice == "1":
                self.start_sale()
            elif choice == "2":
                self.show_inventory()
            elif choice == "3":
                self.process_return()
            elif choice == "0":
                print("Goodbye.")
                break
            else:
                print("Invalid option.")
    
    def demo(self) -> None:
        """Non-interactive demo for ECS/CloudWatch. No input() calls."""
        print("=== RETAILFLOW POS | DEMO MODE ===")

        sample = list(self.inventory.values())[:3]
        print(f"Inventory sample count: {len(sample)}")
        for it in sample:
            print(f"- {it.upc} | {it.description} | ${it.unit_price:.2f} | on_hand={it.on_hand}")

        first = list(self.inventory.values())[0]
        qty = 1
        if first.on_hand <= 0:
            print("Demo cannot run: first item out of stock.")
            return

        line = SaleLine(first.upc, first.description, first.unit_price, qty)
        total = self.calc_total([line])
        cash = total + 1.00
        change = cash - total

        self.inventory[first.upc].update_on_hand(-qty)
        receipt_no = self.sales_store.create_receipt([line])
        self.save_inventory()

        print(f"SALE: {qty} x {first.description} | total=${total:.2f} | cash=${cash:.2f} | change=${change:.2f}")
        print(f"RECEIPT: {receipt_no}")

        self.inventory[first.upc].update_on_hand(1)
        self.sales_store.update_line_qty(receipt_no, first.upc, 0)
        self.save_inventory()

        print(f"RETURN: 1 x {first.description} | receipt={receipt_no}")
        print("=== DEMO COMPLETE ===")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="Run non-interactive demo and exit")
    parser.add_argument("--users", default="data/UsersData.csv")
    parser.add_argument("--inventory", default="data/RetailStoreItemData.txt")
    parser.add_argument("--db", default="data/pos.db")
    args = parser.parse_args()

    app = POSApp(users_csv=args.users, inventory_csv=args.inventory, db_path=args.db)

    if args.demo:
        print("RetailFlow POS demo starting...")
        print("ARGV:", sys.argv)  # <- this proves ECS passed --demo
        app.demo()
        print("Demo complete. Exiting normally.")
        return

    app.run()

if __name__ == "__main__":
    main()
