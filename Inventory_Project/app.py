from flask import Flask, render_template, request, redirect, send_file, url_for
import csv
import sqlite3
from datetime import datetime

app = Flask(__name__)

DB_PATH = "inventory.db"

# ------------- DB helpers -------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # enable foreign keys (good practice)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # products
    cur.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            price REAL NOT NULL
        )
    """)

    # vendors
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_name TEXT NOT NULL,
            contact TEXT
        )
    """)

    # purchase orders
    cur.execute("""
        CREATE TABLE IF NOT EXISTS purchase_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER,
            vendor_id INTEGER,
            quantity INTEGER,
            date TEXT,
            status TEXT DEFAULT 'Pending',
            FOREIGN KEY (product_id) REFERENCES products(id),
            FOREIGN KEY (vendor_id) REFERENCES vendors(id)
        )
    """)

    # Lightweight migration guard (adds missing columns if DB is old)
    cur.execute("PRAGMA table_info(purchase_orders)")
    cols = {row[1] for row in cur.fetchall()}
    needed = [
        ("product_id", "INTEGER"),
        ("vendor_id", "INTEGER"),
        ("quantity", "INTEGER"),
        ("date", "TEXT"),
        ("status", "TEXT DEFAULT 'Pending'"),
    ]
    for name, ddl in needed:
        if name not in cols:
            try:
                cur.execute(f"ALTER TABLE purchase_orders ADD COLUMN {ddl}")
            except sqlite3.OperationalError:
                pass

    conn.commit()
    conn.close()

init_db()

# ------------- Routes -------------

@app.route("/")
def welcome():
    return render_template("welcome.html")

# Optional alias if you also visit /welcome directly
@app.route("/welcome")
def welcome_alias():
    return render_template("welcome.html")

# Inventory dashboard (moved to /dashboard)
@app.route("/dashboard")
def index():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()

    cur.execute("SELECT * FROM vendors ORDER BY id DESC")
    vendors = cur.fetchall()

    total_value = sum(p["quantity"] * p["price"] for p in products)
    conn.close()
    return render_template("index.html", products=products, vendors=vendors, total_value=total_value)

# Add Product
@app.route("/add", methods=["POST"])
def add_product():
    product_name = request.form["product_name"]
    quantity = int(request.form["quantity"])
    rate = float(request.form["rate"])

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO products (product_name, quantity, price) VALUES (?, ?, ?)",
        (product_name, quantity, rate),
    )
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

# Delete Product
@app.route("/delete/<int:product_id>")
def delete_product(product_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

# Update Quantity (sets absolute quantity)
@app.route("/update/<int:product_id>", methods=["POST"])
def update_quantity(product_id):
    new_qty = int(request.form["quantity"])
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE products SET quantity = ? WHERE id = ?", (new_qty, product_id))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))

# Export Inventory to CSV
@app.route("/export")
def export_csv():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, product_name, quantity, price FROM products ORDER BY id")
    rows = cur.fetchall()
    conn.close()

    filepath = "inventory.csv"
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ID", "Product", "Quantity", "Price"])
        for r in rows:
            w.writerow([r["id"], r["product_name"], r["quantity"], r["price"]])
    return send_file(filepath, as_attachment=True)

# Purchase Order page (vendors & products from DB)
@app.route("/po")
def purchase_order_page():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, product_name FROM products ORDER BY product_name")
    products = cur.fetchall()
    cur.execute("SELECT id, vendor_name FROM vendors ORDER BY vendor_name")
    vendors = cur.fetchall()
    conn.close()
    return render_template("purchase_order.html", products=products, vendors=vendors)

# Create Purchase Order
@app.route("/create_po", methods=["POST"])
def create_po():
    product_id = int(request.form["product_id"])
    vendor_id = int(request.form["vendor_id"])
    quantity = int(request.form["quantity"])
    today = datetime.today().strftime("%Y-%m-%d")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO purchase_orders (product_id, vendor_id, quantity, date, status)
        VALUES (?, ?, ?, ?, 'Pending')
    """, (product_id, vendor_id, quantity, today))
    conn.commit()
    conn.close()
    return redirect(url_for("po_history"))

# Purchase Order History (joined with names)
@app.route("/po_history")
def po_history():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT po.id as po_id, po.quantity, po.date, po.status,
               p.product_name, v.vendor_name
        FROM purchase_orders po
        LEFT JOIN products p ON p.id = po.product_id
        LEFT JOIN vendors v ON v.id = po.vendor_id
        ORDER BY po.id DESC
    """)
    orders = cur.fetchall()
    conn.close()
    return render_template("po_history.html", purchase_orders=orders)

# Receive Purchase Order (increments stock + marks received)
@app.route("/receive_po/<int:po_id>")
def receive_po(po_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT product_id, quantity, status FROM purchase_orders WHERE id = ?", (po_id,))
    po = cur.fetchone()
    if po and po["status"] == "Pending":
        cur.execute("UPDATE products SET quantity = quantity + ? WHERE id = ?", (po["quantity"], po["product_id"]))
        cur.execute("UPDATE purchase_orders SET status = 'Received' WHERE id = ?", (po_id,))
        conn.commit()
    conn.close()
    return redirect(url_for("po_history"))

# Vendor Management
@app.route("/vendors")
def vendor_page():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM vendors ORDER BY id DESC")
    vendors = cur.fetchall()
    conn.close()
    return render_template("vendors.html", vendors=vendors)

# Add Vendor
@app.route("/add_vendor", methods=["POST"])
def add_vendor():
    vendor_name = request.form["vendor_name"]
    contact = request.form.get("contact")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO vendors (vendor_name, contact) VALUES (?, ?)", (vendor_name, contact))
    conn.commit()
    conn.close()
    return redirect(url_for("vendor_page"))

# Delete Vendor
@app.route("/delete_vendor/<int:vendor_id>")
def delete_vendor(vendor_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("vendor_page"))

if __name__ == "__main__":
    app.run(debug=True)