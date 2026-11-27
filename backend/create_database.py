
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "lillian_college.db"
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# Student details
cursor.execute("""
CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    password TEXT,
    department TEXT,
    year INTEGER
)
""")

# Employee details
cursor.execute("""
CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    password TEXT,
    designation TEXT,
    department TEXT
)
""")

# Parent details
cursor.execute("""
CREATE TABLE IF NOT EXISTS parents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE,
    password TEXT,
    student_id INTEGER,
    FOREIGN KEY (student_id) REFERENCES students(id)
)
""")

# Attendance details
cursor.execute("""
CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    date TEXT,
    status TEXT,
    FOREIGN KEY (student_id) REFERENCES students(id)
)
""")

# Marks details
cursor.execute("""
CREATE TABLE IF NOT EXISTS marks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    subject TEXT,
    marks INTEGER,
    FOREIGN KEY (student_id) REFERENCES students(id)
)
""")

# Fee details
cursor.execute("""
CREATE TABLE IF NOT EXISTS fees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER,
    total_fee REAL,
    paid_fee REAL,
    balance REAL,
    FOREIGN KEY (student_id) REFERENCES students(id)
)
""")

conn.commit()
conn.close()

print("Lillian College Database Created Successfully!")
