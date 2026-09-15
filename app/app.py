from flask import Flask
import psycopg2
import os
import time

app = Flask(__name__)

def get_db_connection():
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "db"),
        database=os.environ.get("DB_NAME", "appdb"),
        user=os.environ.get("DB_USER", "appuser"),
        password=os.environ.get("DB_PASSWORD", "apppass")
    )
    return conn

@app.route("/")
def index():
    return "App is running. Try /db-check"

@app.route("/db-check")
def db_check():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        cur.close()
        conn.close()
        return f"Connected to DB: {version}"
    except Exception as e:
        return f"DB connection failed: {e}", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)