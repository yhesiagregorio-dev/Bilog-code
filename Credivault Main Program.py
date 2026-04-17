import sys
import sqlite3
import random
import string
import os


from PySide6.QtCore import QFile, QObject, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QPixmap, QPalette, QBrush
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QPushButton,
    QDialog,
    QTableWidgetItem,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QWidget,
    QScrollArea,
    QFrame,
    QCheckBox,
    QInputDialog,
    QLineEdit
)

DB_NAME = "credivault.db"


# ================= DATABASE =================
def create_connection():
    return sqlite3.connect(DB_NAME)


def create_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password TEXT NOT NULL,
        hint TEXT NOT NULL DEFAULT ''
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS app_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL DEFAULT ''
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS creditors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creditor_code TEXT UNIQUE,
        name TEXT NOT NULL UNIQUE,
        contact TEXT NOT NULL,
        address TEXT NOT NULL,
        balance REAL NOT NULL DEFAULT 0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS credits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creditor_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        amount REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'unpaid',
        FOREIGN KEY (creditor_id) REFERENCES creditors(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS paid_credits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_credit_id INTEGER,
        creditor_id INTEGER NOT NULL,
        creditor_name TEXT NOT NULL,
        contact TEXT NOT NULL,
        address TEXT NOT NULL,
        product_name TEXT NOT NULL,
        amount REAL NOT NULL,
        paid_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()


def set_app_state(conn, key, value):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO app_state (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, value))
    conn.commit()


def get_app_state(conn, key):
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM app_state WHERE key = ?", (key,))
    row = cursor.fetchone()
    return row[0] if row else ""

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS  # for EXE
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def set_background(widget, image_path):
    full_path = resource_path(image_path)

    # 🔍 DEBUG HERE
    print("FULL PATH:", full_path)
    print("EXISTS:", os.path.exists(full_path))
    print("FILES INSIDE Images:", os.listdir(resource_path("Images")) if os.path.exists(resource_path("Images")) else "Images folder not found")

    if not os.path.exists(full_path):
        print("❌ IMAGE NOT FOUND:", full_path)
        return

    from PySide6.QtGui import QPixmap, QPalette, QBrush

    pixmap = QPixmap(full_path)

    if pixmap.isNull():
        print("❌ FAILED TO LOAD IMAGE:", full_path)
        return

    palette = QPalette()
    palette.setBrush(QPalette.Window, QBrush(pixmap))

    widget.setAutoFillBackground(True)
    widget.setPalette(palette)

# ================= LOAD UI =================
def load_ui(filename):
    loader = QUiLoader()
    file = QFile(filename)

    if not file.exists():
        raise FileNotFoundError(f"UI file not found: {filename}")

    if not file.open(QFile.ReadOnly):
        raise RuntimeError(f"Could not open UI file: {filename}")

    ui = loader.load(file)
    file.close()

    if ui is None:
        raise RuntimeError(f"Could not load UI file: {filename}")

    return ui


# ================= LIST DIALOG =================
class CreditBrowserDialog(QDialog):
    def __init__(self, app_ref):
        super().__init__()
        set_background(self, "Images/3.png")
        self.app_ref = app_ref
        self.setWindowTitle("Creditor Ledger")
        self.resize(850, 550)

        self.selected_checkboxes = []

        layout = QVBoxLayout(self)

        # TITLE
        title = QLabel("Creditor Ledger System")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:18px; font-weight:bold;")
        layout.addWidget(title)

        # SEARCH
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search creditor name...")
        self.search_bar.textChanged.connect(self.show_unpaid_section)
        layout.addWidget(self.search_bar)

        # DASHBOARD
        self.dashboard_label = QLabel()
        self.dashboard_label.setAlignment(Qt.AlignCenter)
        self.dashboard_label.setStyleSheet("font-size:13px; font-weight:bold; margin:6px;")
        layout.addWidget(self.dashboard_label)

        # BUTTONS
        btn_layout = QHBoxLayout()

        self.unpaid_btn = QPushButton("All Credits")
        self.unpaid_btn.clicked.connect(self.show_unpaid_section)
        btn_layout.addWidget(self.unpaid_btn)

        self.paid_btn = QPushButton("Paid List")
        self.paid_btn.clicked.connect(self.show_paid)
        btn_layout.addWidget(self.paid_btn)

        layout.addLayout(btn_layout)

        # SCROLL
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)

        self.container = QWidget()
        self.container_layout = QVBoxLayout(self.container)
        self.scroll.setWidget(self.container)

        layout.addWidget(self.scroll)

        # DELETE BUTTON
        self.delete_btn = QPushButton("Delete Selected Paid")
        self.delete_btn.clicked.connect(self.delete_paid)
        layout.addWidget(self.delete_btn)

        self.show_unpaid_section()

    # ================= HELPERS =================
    def clear(self):
        self.selected_checkboxes = []
        while self.container_layout.count():
            item = self.container_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def make_mark_all_handler(self, creditor_id):
        return lambda: self.mark_all_paid(creditor_id)

    # ================= DASHBOARD =================
    def update_dashboard(self):
        cursor = self.app_ref.conn.cursor()

        cursor.execute("""
            SELECT SUM(amount) FROM credits
            WHERE status IS NULL OR status='' OR LOWER(status)='unpaid'
        """)
        unpaid = cursor.fetchone()[0] or 0

        cursor.execute("SELECT SUM(amount) FROM paid_credits")
        paid = cursor.fetchone()[0] or 0

        total = unpaid + paid

        self.dashboard_label.setText(
            f"Unpaid: ₱{unpaid}   |   Paid: ₱{paid}   |   Total: ₱{total}"
        )

    # ================= UNPAID =================
    def show_unpaid_section(self):
        self.delete_btn.hide()
        self.clear()
        self.update_dashboard()

        cursor = self.app_ref.conn.cursor()

        cursor.execute("UPDATE credits SET status='unpaid' WHERE status IS NULL OR status=''")
        self.app_ref.conn.commit()

        cursor.execute("""
            SELECT id, creditor_code, name, contact, address
            FROM creditors
            ORDER BY name
        """)
        creditors = cursor.fetchall()

        search_text = self.search_bar.text().lower()

        title = QLabel("All Credits")
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        self.container_layout.addWidget(title)

        for cid, code, name, contact, address in creditors:
            if search_text and search_text not in name.lower():
                continue

            frame = QFrame()
            frame.setStyleSheet("margin-bottom:10px;")
            layout = QVBoxLayout(frame)

            # TOTAL
            cursor.execute("""
                SELECT SUM(amount) FROM credits
                WHERE creditor_id=? 
                AND (status IS NULL OR status='' OR LOWER(status)='unpaid')
            """, (cid,))
            total = cursor.fetchone()[0] or 0

            header = QLabel(
                f"{name}\n"
                f"ID: {code}\n"
                f"Contact: {contact}\n"
                f"Address: {address}\n"
                f"Total: ₱{total}"
            )
            header.setStyleSheet("font-size:12px; font-weight:bold;")
            layout.addWidget(header)

            # LOAD CREDITS
            cursor.execute("""
                SELECT id, product_name, amount, status
                FROM credits
                WHERE creditor_id=?
                ORDER BY id DESC
            """, (cid,))
            credits = cursor.fetchall()

            unpaid_exists = False

            for _, product, amount, status in credits:
                if status and status.lower() == "paid":
                    continue

                unpaid_exists = True

                row = QLabel(f"{product} | ₱{amount}")
                row.setStyleSheet("font-size:11px;")
                layout.addWidget(row)

            # 🔥 ONE BUTTON PER CREDITOR
            if unpaid_exists:
                button_row = QWidget()
                button_layout = QHBoxLayout(button_row)
                button_layout.setContentsMargins(0, 0, 0, 0)
                button_layout.setSpacing(10)

                # FULL PAYMENT BUTTON
                btn_full = QPushButton("Mark All as Paid")
                btn_full.setFixedHeight(28)
                btn_full.clicked.connect(self.make_mark_all_handler(cid))
                button_layout.addWidget(btn_full)

                # PARTIAL PAYMENT BUTTON
                btn_partial = QPushButton("Partial Payment")
                btn_partial.setFixedHeight(28)
                btn_partial.clicked.connect(lambda _, x=cid: self.partial_payment(x))
                button_layout.addWidget(btn_partial)

                layout.addWidget(button_row)
            
            self.container_layout.addWidget(frame)

        self.container_layout.addStretch()

    # ================= MARK ALL PAID =================
    def mark_all_paid(self, creditor_id):
        try:
            cursor = self.app_ref.conn.cursor()

            cursor.execute("""
                SELECT
                    credits.id,
                    creditors.name,
                    creditors.contact,
                    creditors.address,
                    credits.product_name,
                    credits.amount
                FROM credits
                JOIN creditors ON credits.creditor_id = creditors.id
                WHERE credits.creditor_id = ?
                AND (credits.status IS NULL OR credits.status='' OR LOWER(credits.status)='unpaid')
            """, (creditor_id,))
            rows = cursor.fetchall()

            if not rows:
                QMessageBox.information(self, "Info", "No unpaid credits.")
                return

            for credit_id, name, contact, address, product, amount in rows:
                cursor.execute("""
                    INSERT INTO paid_credits (
                        original_credit_id, creditor_id, creditor_name,
                        contact, address, product_name, amount
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (credit_id, creditor_id, name, contact, address, product, amount))

                cursor.execute("UPDATE credits SET status='paid' WHERE id=?", (credit_id,))

            self.app_ref.conn.commit()

            self.update_dashboard()
            self.show_unpaid_section()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def partial_payment(self, creditor_id):
        try:
            cursor = self.app_ref.conn.cursor()

            # GET TOTAL UNPAID
            cursor.execute("""
                SELECT SUM(amount) FROM credits
                WHERE creditor_id=? 
                AND (status IS NULL OR status='' OR LOWER(status)='unpaid')
            """, (creditor_id,))
            total = cursor.fetchone()[0] or 0

            if total <= 0:
                QMessageBox.information(self, "Info", "No unpaid balance.")
                return

            # ASK USER INPUT
            amount, ok = QInputDialog.getDouble(
                self,
                "Partial Payment",
                f"Enter amount to pay (Total: ₱{total}):",
                0, 0, total, 2
            )

            if not ok or amount <= 0:
                return

            remaining = amount

            # GET UNPAID CREDITS (OLDEST FIRST)
            cursor.execute("""
                SELECT id, product_name, amount
                FROM credits
                WHERE creditor_id=? 
                AND (status IS NULL OR status='' OR LOWER(status)='unpaid')
                ORDER BY id ASC
            """, (creditor_id,))
            credits = cursor.fetchall()

            for credit_id, product, credit_amount in credits:
                if remaining <= 0:
                    break

                if remaining >= credit_amount:
                    # FULLY PAY THIS CREDIT
                    cursor.execute("""
                        INSERT INTO paid_credits (
                            original_credit_id, creditor_id, creditor_name,
                            contact, address, product_name, amount
                        )
                        SELECT credits.id, creditors.id, creditors.name,
                            creditors.contact, creditors.address,
                            credits.product_name, credits.amount
                        FROM credits
                        JOIN creditors ON credits.creditor_id = creditors.id
                        WHERE credits.id=?
                    """, (credit_id,))

                    cursor.execute("UPDATE credits SET status='paid' WHERE id=?", (credit_id,))
                    remaining -= credit_amount

                else:
                    # PARTIAL SPLIT
                    paid_part = remaining
                    unpaid_part = credit_amount - remaining

                    # INSERT PAID PART
                    cursor.execute("""
                        INSERT INTO paid_credits (
                            original_credit_id, creditor_id, creditor_name,
                            contact, address, product_name, amount
                        )
                        SELECT credits.id, creditors.id, creditors.name,
                            creditors.contact, creditors.address,
                            credits.product_name, ?
                        FROM credits
                        JOIN creditors ON credits.creditor_id = creditors.id
                        WHERE credits.id=?
                    """, (paid_part, credit_id))

                    # UPDATE REMAINING CREDIT
                    cursor.execute("""
                        UPDATE credits SET amount=? WHERE id=?
                    """, (unpaid_part, credit_id))

                    remaining = 0

            self.app_ref.conn.commit()

            QMessageBox.information(self, "Success", "Partial payment applied.")

            self.update_dashboard()
            self.show_unpaid_section()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    # ================= PAID =================
    def show_paid(self):
        self.delete_btn.show()
        self.clear()
        self.update_dashboard()

        cursor = self.app_ref.conn.cursor()

        title = QLabel("Paid Credits")
        title.setStyleSheet("font-size:14px; font-weight:bold;")
        self.container_layout.addWidget(title)

        cursor.execute("""
            SELECT id, creditor_name, product_name, amount, paid_date
            FROM paid_credits
            ORDER BY paid_date DESC
        """)
        data = cursor.fetchall()

        if not data:
            self.container_layout.addWidget(QLabel("No paid credits"))
            return

        for pid, name, product, amount, date in data:
            row = QWidget()
            row_layout = QHBoxLayout(row)

            checkbox = QCheckBox()
            checkbox.setProperty("id", pid)
            self.selected_checkboxes.append(checkbox)
            row_layout.addWidget(checkbox)

            label = QLabel(f"{name} | {product} | ₱{amount} | {date}")
            label.setStyleSheet("font-size:11px;")
            row_layout.addWidget(label)

            self.container_layout.addWidget(row)

        self.container_layout.addStretch()

    # ================= DELETE =================
    def delete_paid(self):
        ids = [cb.property("id") for cb in self.selected_checkboxes if cb.isChecked()]

        if not ids:
            QMessageBox.warning(self, "Error", "Select items first")
            return

        cursor = self.app_ref.conn.cursor()
        placeholders = ",".join("?" * len(ids))
        cursor.execute(f"DELETE FROM paid_credits WHERE id IN ({placeholders})", ids)
        self.app_ref.conn.commit()

        self.update_dashboard()
        self.show_paid()

# ================= APP =================
class App(QObject):
    def __init__(self):
        super().__init__()
        self.conn = create_connection()
        create_tables(self.conn)

        self.main = None
        self.register = None
        self.credit = None
        self.credit_data = None
        self.add_credit_ui = None

        self.login_attempts = {}

        self.open_main_window()

    def disconnect_button(self, btn):
        try:
            btn.clicked.disconnect()
        except Exception:
            pass

    def generate_creditor_code(self):
        cursor = self.conn.cursor()

        while True:
            code = "CR-" + "".join(random.choices(string.digits, k=6))
            cursor.execute("SELECT id FROM creditors WHERE creditor_code = ?", (code,))
            if not cursor.fetchone():
                return code

    def show_only(self, window_to_show, windows_to_hide=None):
        if windows_to_hide:
            for w in windows_to_hide:
                if w is not None:
                    w.hide()

        if window_to_show is not None:
            window_to_show.show()
            window_to_show.raise_()
            window_to_show.activateWindow()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Close:
            if obj == self.credit_data:
                obj.hide()                 # ✅ hide instead of close
                self.credit.show()         # ✅ show existing window
                return True

            if obj == self.add_credit_ui:
                obj.hide()
                self.credit.show()
                return True

        return super().eventFilter(obj, event)

    def exit_app(self):
        reply = QMessageBox.question(
            self.credit if self.credit is not None else None,
            "Exit",
            "Are you sure you want to exit?",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            QApplication.quit()

    # ================= MAIN WINDOW =================
    def open_main_window(self):
        self.main = load_ui("CrediVault_MainWindow.ui")
        set_background(self.main, "Images/3.png")
        self.main.pushButton.clicked.connect(self.open_registration)
        self.main.show()

    # ================= REGISTRATION =================
    def open_registration(self):
        self.register = load_ui("Registration.ui")
        set_background(self.register, "Images/3.png")

        all_buttons = self.register.findChildren(QPushButton)

        for btn in all_buttons:
            self.disconnect_button(btn)
            text = btn.text().strip().lower()

            if "sign in" in text:
                btn.clicked.connect(self.register_user)
            elif "log in" in text or "login" in text:
                btn.clicked.connect(self.login_user)
            elif "forgot" in text:
                btn.clicked.connect(self.forgot_password_flow)

        self.show_only(self.register, [self.main])

    def register_user(self):
        try:
            username = self.register.LE1.text().strip()
            password = self.register.LE1_2.text()

            if not username or not password:
                QMessageBox.warning(self.register, "Error", "Please fill in username and password.")
                return

            hint, ok = QInputDialog.getText(
                self.register,
                "Password Hint",
                "Enter a hint for your password:"
            )

            if not ok or not hint.strip():
                QMessageBox.warning(self.register, "Error", "Password hint is required.")
                return

            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            existing = cursor.fetchone()

            if existing:
                QMessageBox.warning(self.register, "Error", "Username already exists.")
                return

            cursor.execute(
                "INSERT INTO users (username, password, hint) VALUES (?, ?, ?)",
                (username, password, hint.strip())
            )
            self.conn.commit()

            QMessageBox.information(self.register, "Success", "User registered successfully.")
            self.register.LE1.clear()
            self.register.LE1_2.clear()

        except Exception as e:
            QMessageBox.critical(self.register, "Error", str(e))

    def login_user(self):
        try:
            username = self.register.LE1.text().strip()
            password = self.register.LE1_2.text()

            if not username or not password:
                QMessageBox.warning(self.register, "Error", "Please enter username and password.")
                return

            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT password, hint FROM users WHERE username = ?",
                (username,)
            )
            row = cursor.fetchone()

            if not row:
                QMessageBox.warning(self.register, "Login Failed", "Username not found.")
                return

            saved_password, hint = row

            if password == saved_password:
                self.login_attempts[username] = 0
                set_app_state(self.conn, "last_signed_in_user", username)
                QMessageBox.information(self.register, "Success", "Login successful.")
                self.open_credit_management()
                return

            self.login_attempts[username] = self.login_attempts.get(username, 0) + 1
            attempts = self.login_attempts[username]

            if attempts >= 3:
                QMessageBox.warning(
                    self.register,
                    "Login Failed",
                    f"Wrong password.\nPassword hint: {hint}"
                )
            else:
                QMessageBox.warning(
                    self.register,
                    "Login Failed",
                    f"Wrong password. Attempt {attempts} of 3."
                )

        except Exception as e:
            QMessageBox.critical(self.register, "Error", str(e))

    def forgot_password_flow(self):
        try:
            last_logged_in = get_app_state(self.conn, "last_signed_in_user")

            if not last_logged_in:
                QMessageBox.warning(
                    self.register,
                    "Forgot Password",
                    "No previous logged-in account found."
                )
                return

            previous_login_name, ok = QInputDialog.getText(
                self.register,
                "Forgot Password",
                "Enter the previous logged-in account name:"
            )
            if not ok or not previous_login_name.strip():
                return

            if previous_login_name.strip() != last_logged_in:
                QMessageBox.warning(
                    self.register,
                    "Access Denied",
                    "The account name does not match the previous logged-in account."
                )
                return

            recovery_account_name, ok = QInputDialog.getText(
                self.register,
                "Forgot Password",
                "Enter the account name to recover:"
            )
            if not ok or not recovery_account_name.strip():
                return

            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT password, hint FROM users WHERE username = ?",
                (recovery_account_name.strip(),)
            )
            row = cursor.fetchone()

            if not row:
                QMessageBox.warning(
                    self.register,
                    "Not Found",
                    "That account name does not exist."
                )
                return

            password, hint = row

            QMessageBox.information(
                self.register,
                "Recovered Password",
                f"Account: {recovery_account_name.strip()}\nPassword: {password}\nHint: {hint}"
            )

        except Exception as e:
            QMessageBox.critical(self.register, "Error", str(e))

    # ================= CREDIT MANAGEMENT =================
    def open_credit_management(self):
        try:
            file_path = "Credit_Management.ui"

            print("Looking for:", file_path)
            print("Exists:", os.path.exists(file_path))

            self.credit = load_ui(file_path)
            set_background(self.credit, "Images/3.png")

               
            self.credit.pushButton_2.clicked.connect(self.open_credit_data)    
            self.credit.pushButton_3.clicked.connect(self.open_add_credit)    
            self.credit.pushButton.clicked.connect(self.show_list) 
            self.credit.pushButton_5.clicked.connect(self.exit_app)        
            
            self.credit.show()
            self.register.hide()

        except Exception as e:
            QMessageBox.critical(None, "Error", f"FAILED TO LOAD UI:\n{e}")

    # ================= CREDITOR DATA =================
    def open_add_credit(self):
        try:
            self.add_credit_ui = load_ui("add credits.ui")
            set_background(self.add_credit_ui, "Images/3.png")

            buttons = self.add_credit_ui.findChildren(QPushButton)
            add_button = buttons[0] if buttons else None

            if add_button is None:
                QMessageBox.critical(self.credit, "Error", "No Add button found")
                return

            self.disconnect_button(add_button)
            add_button.clicked.connect(self.save_added_credit)

            # 🔥 INSTALL EVENT FILTER
            self.add_credit_ui.installEventFilter(self)

            self.show_only(self.add_credit_ui, [self.credit])

        except Exception as e:
            QMessageBox.critical(self.credit, "Error", str(e))
    
    def save_creditor(self):
        try:
            name = self.credit_data.LE1.text().strip()

            if hasattr(self.credit_data, "LE1_4"):
                contact_number = self.credit_data.LE1_2.text().strip()
                address = self.credit_data.LE1_3.text().strip()
                balance_text = self.credit_data.LE1_4.text().strip()
            else:
                address = self.credit_data.LE1_2.text().strip()
                contact_number = self.credit_data.LE1_3.text().strip()
                balance_text = "0"

            if not name or not contact_number or not address:
                QMessageBox.warning(self.credit_data, "Error", "Please fill in all fields.")
                return

            try:
                balance = float(balance_text)
            except ValueError:
                QMessageBox.warning(self.credit_data, "Error", "Balance must be a valid number.")
                return

            cursor = self.conn.cursor()
            cursor.execute("SELECT id FROM creditors WHERE lower(name) = lower(?)", (name,))
            existing = cursor.fetchone()

            if existing:
                cursor.execute("""
                    UPDATE creditors
                    SET contact = ?, address = ?, balance = ?
                    WHERE lower(name) = lower(?)
                """, (contact_number, address, balance, name))
                self.conn.commit()

                QMessageBox.information(
                    self.credit_data,
                    "Success",
                    "Creditor data updated successfully."
                )
            else:
                creditor_code = self.generate_creditor_code()

                cursor.execute("""
                    INSERT INTO creditors (creditor_code, name, contact, address, balance)
                    VALUES (?, ?, ?, ?, ?)
                """, (creditor_code, name, contact_number, address, balance))
                self.conn.commit()

                QMessageBox.information(
                    self.credit_data,
                    "Success",
                    f"Creditor saved successfully.\nCreditor ID: {creditor_code}"
                )

            self.credit_data.close()
            self.show_only(self.credit)

        except Exception as e:
            QMessageBox.critical(self.credit_data, "Error", str(e))

    # ================= ADD CREDIT =================
    def open_credit_data(self):
        try:
            self.credit_data = load_ui("Creditor Data.ui")
            set_background(self.credit_data, "Images/3.png")

            buttons = self.credit_data.findChildren(QPushButton)
            add_button = buttons[0] if buttons else None

            if add_button is None:
                QMessageBox.critical(self.credit, "Error", "No Add button found in Creditor Data.ui")
                return

            self.disconnect_button(add_button)
            add_button.clicked.connect(self.save_creditor)

            # 🔥 INSTALL EVENT FILTER
            self.credit_data.installEventFilter(self)

            self.show_only(self.credit_data, [self.credit])

        except Exception as e:
            QMessageBox.critical(self.credit, "Error", str(e))
            
    def save_added_credit(self):
        try:
            creditor_name = self.add_credit_ui.LE1.text().strip()
            product_name = self.add_credit_ui.LE1_2.text().strip()
            amount_text = self.add_credit_ui.LE1_3.text().strip()

            if not creditor_name or not product_name or not amount_text:
                QMessageBox.warning(self.add_credit_ui, "Error", "Please fill in all fields.")
                return

            try:
                amount = float(amount_text)
            except ValueError:
                QMessageBox.warning(self.add_credit_ui, "Error", "Cost of product must be a valid number.")
                return

            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT id, balance
                FROM creditors
                WHERE lower(name) = lower(?)
            """, (creditor_name,))
            result = cursor.fetchone()

            if not result:
                QMessageBox.warning(
                    self.add_credit_ui,
                    "Not Found",
                    "Creditor not found.\nPlease add the creditor first in Creditor Data."
                )
                return

            creditor_id, old_balance = result
            new_balance = old_balance + amount

            cursor.execute("""
                INSERT INTO credits (creditor_id, product_name, amount, status)
                VALUES (?, ?, ?, 'unpaid')
            """, (creditor_id, product_name, amount))

            cursor.execute("""
                UPDATE creditors
                SET balance = ?
                WHERE id = ?
            """, (new_balance, creditor_id))

            self.conn.commit()

            QMessageBox.information(
                self.add_credit_ui,
                "Success",
                f"Credit added successfully.\nCreditor: {creditor_name}\nProduct: {product_name}"
            )

            self.add_credit_ui.close()
            self.show_only(self.credit)

        except Exception as e:
            QMessageBox.critical(self.add_credit_ui, "Error", str(e))

    # ================= LIST =================
    def show_list(self):
        try:
            self.dialog = CreditBrowserDialog(self)
            self.dialog.exec()
        except Exception as e:
            QMessageBox.critical(self.credit, "Error", str(e))

# ================= RUN APP =================
if __name__ == "__main__":
    app = QApplication(sys.argv)

    try:
        system = App()
        sys.exit(app.exec())
    except Exception as e:
        QMessageBox.critical(None, "Startup Error", str(e))
        sys.exit(1)