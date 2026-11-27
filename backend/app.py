
from flask import Flask, jsonify, request, send_from_directory, session
import sqlite3
import json
import re
import os
import hmac
import time
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-only-change-this-secret")

BASE_DIR = Path(__file__).resolve().parent.parent

BACKEND_DIR = Path(__file__).resolve().parent

# Load simple KEY=VALUE entries from backend/.env without requiring python-dotenv.
_env_file = BACKEND_DIR / ".env"
if _env_file.exists():
    for _line in _env_file.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if not _line or _line.startswith("#") or "=" not in _line:
            continue
        _key, _value = _line.split("=", 1)
        _key, _value = _key.strip(), _value.strip().strip('"').strip("'")
        if _key:
            os.environ.setdefault(_key, _value)


def _existing_database_score(path):
    """Prefer the existing database that already contains the most college tables."""
    if not path.exists():
        return -1
    try:
        with sqlite3.connect(path) as probe:
            names = probe.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
        return len(names)
    except sqlite3.Error:
        return -1


# Older copies of this project stored the DB in the project root; newer copies
# store it inside backend/. Reuse the populated file instead of silently opening
# a different, empty database after an update.
_db_candidates = [BACKEND_DIR / "lillian_college.db", BASE_DIR / "lillian_college.db"]
DB_PATH = max(_db_candidates, key=_existing_database_score)
if _existing_database_score(DB_PATH) < 0:
    DB_PATH = BACKEND_DIR / "lillian_college.db"


def ensure_core_schema(conn):
    """Create only missing core tables; never drop or overwrite existing records."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            password TEXT,
            department TEXT,
            year INTEGER
        );
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            password TEXT,
            designation TEXT,
            department TEXT
        );
        CREATE TABLE IF NOT EXISTS parents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            password TEXT,
            student_id INTEGER,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            date TEXT,
            status TEXT,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            subject TEXT,
            marks INTEGER,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );
        CREATE TABLE IF NOT EXISTS fees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            total_fee REAL,
            paid_fee REAL,
            balance REAL,
            FOREIGN KEY (student_id) REFERENCES students(id)
        );
    """)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    ensure_core_schema(conn)
    return conn



def ensure_academic_schema(conn):
    student_cols = [row["name"] for row in conn.execute("PRAGMA table_info(students)").fetchall()]
    if "student_id" not in student_cols:
        conn.execute("ALTER TABLE students ADD COLUMN student_id TEXT")
    employee_cols = [row["name"] for row in conn.execute("PRAGMA table_info(employees)").fetchall()]
    if "employee_code" not in employee_cols:
        conn.execute("ALTER TABLE employees ADD COLUMN employee_code TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_students_student_id ON students(student_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_employee_code ON employees(employee_code)")
    # Give existing students and employees stable IDs without changing their login credentials.
    for row in conn.execute("SELECT id FROM students WHERE student_id IS NULL OR student_id=''").fetchall():
        conn.execute("UPDATE students SET student_id=? WHERE id=?", (f"LIT-OLD-STU-{row['id']:04d}", row["id"]))
    for row in conn.execute("SELECT id FROM employees WHERE employee_code IS NULL OR employee_code=''").fetchall():
        conn.execute("UPDATE employees SET employee_code=? WHERE id=?", (f"LIT-EMP-{row['id']:04d}", row["id"]))


BE_COURSES = [
    ("CSE", "BE Computer Science & Engineering"),
    ("CIVIL", "BE Civil Engineering"),
    ("MECH", "BE Mechanical Engineering"),
    ("EC", "BE Electronics & Communication Engineering"),
    ("EEE", "BE Electrical & Electronics Engineering"),
]
ME_COURSES = [
    ("CSE", "ME Computer Science & Engineering"),
    ("CIVIL", "ME Civil Engineering"),
    ("MECH", "ME Mechanical Engineering"),
    ("EC", "ME Electronics & Communication Engineering"),
    ("EEE", "ME Electrical & Electronics Engineering"),
]
NAME_FIRST = ["Aadhavan","Aishwarya","Akash","Ananya","Arjun","Bhavani","Charan","Deepika","Dharun","Divya",
              "Gokul","Harini","Iniya","Janani","Karthik","Keerthana","Kavin","Lakshmi","Madhan","Meena",
              "Naveen","Nithya","Pranav","Priya","Rahul","Rithika","Sanjay","Shalini","Siva","Sneha",
              "Surya","Swetha","Tamilselvan","Varsha","Vignesh","Yazhini"]
NAME_LAST = ["Anand","Balan","Chandran","Devi","Gopal","Iyer","Kumar","Krishnan","Mani","Mohan",
             "Narayanan","Pandian","Prakash","Rajan","Raman","Ramesh","Ravi","Sekar","Shankar","Subramanian",
             "Varma","Vel","Venkatesh","Vijay"]
def seed_academic_students():
    conn = get_db_connection()
    ensure_academic_schema(conn)
    courses = [( "BE", code, title, 4) for code,title in BE_COURSES]
    courses += [( "ME", code, title, 2) for code,title in ME_COURSES]
    courses += [("MCA", "MCA", "Master of Computer Applications", 2), ("MBA", "MBA", "Master of Business Administration", 2)]
    inserted = 0
    for program, code, title, years in courses:
        for year in range(1, years + 1):
            for n in range(1, 21):
                first = NAME_FIRST[(n * 3 + year + len(code)) % len(NAME_FIRST)]
                last = NAME_LAST[(n * 5 + year + len(code)) % len(NAME_LAST)]
                name = f"{first} {last}"
                student_code = f"LIT-{program}-{code}-{year}-{n:03d}"
                email = f"{program.lower()}.{code.lower()}.y{year}.{n:03d}@students.lillian.edu"
                password_hash = generate_password_hash("Student@123")
                conn.execute("""
                    INSERT OR IGNORE INTO students
                    (name,email,password,department,year,student_id)
                    VALUES (?,?,?,?,?,?)
                """, (name,email,password_hash,title,year,student_code))
                inserted += conn.execute("SELECT changes()").fetchone()[0]
                # Keep already-created demo accounts aligned with the current course catalogue.
                conn.execute("UPDATE students SET department=?, year=? WHERE email=?",
                             (title, year, email))
    # Maintain a normalized course catalogue in SQLite for website/API consumers.
    conn.execute("""CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        program_code TEXT NOT NULL,
        department_code TEXT NOT NULL,
        course_name TEXT NOT NULL,
        duration_years INTEGER NOT NULL,
        UNIQUE(program_code, department_code)
    )""")
    conn.execute("DELETE FROM courses")
    for program, code, title, years in courses:
        conn.execute("INSERT INTO courses(program_code,department_code,course_name,duration_years) VALUES(?,?,?,?)",
                     (program, code, title, years))
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
    conn.close()
    return inserted, total


@app.route("/api/setup-academic-students", methods=["GET","POST"])
def setup_academic_students():
    inserted, total = seed_academic_students()
    return jsonify({"status":"success","new_records_added":inserted,
                    "total_student_accounts":total,
                    "expected_sample_accounts":680,
                    "default_student_password":"Student@123",
                    "student_id_format":"LIT-BE-CSE-1-001", "course_structure":"BE 4 years; ME, MCA, MBA 2 years", "course_structure":"BE 4 years; ME, MCA, MBA 2 years"})


@app.route("/api/courses")
def get_courses():
    conn = get_db_connection()
    rows = conn.execute("SELECT program_code, department_code, course_name, duration_years FROM courses ORDER BY CASE program_code WHEN 'BE' THEN 1 WHEN 'ME' THEN 2 WHEN 'MCA' THEN 3 ELSE 4 END, department_code").fetchall()
    conn.close()
    return jsonify({"status":"success", "courses":[dict(r) for r in rows]})



# ---------------- FRONTEND PAGES ----------------

@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/login.html")
def login_page():
    return send_from_directory(BASE_DIR, "login.html")


@app.route("/dashboard.html")
def dashboard_page():
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.route("/parent-dashboard.html")
def parent_dashboard_page():
    return send_from_directory(BASE_DIR, "parent-dashboard.html")


@app.route("/<path:filename>")
def frontend_asset(filename):
    # Serve root-level frontend assets such as style.css and script.js.
    target = (BASE_DIR / filename).resolve()
    if target.parent != BASE_DIR.resolve() or not target.is_file():
        return ("Not Found", 404)
    return send_from_directory(BASE_DIR, filename)




# ---------------- STUDENT DEMO ACCOUNT ----------------

@app.route("/api/setup-student")
def setup_student():
    conn = get_db_connection()
    cursor = conn.cursor()

    email = "student@lillian.edu"
    password = generate_password_hash("Student@123")

    cursor.execute("""
        INSERT OR IGNORE INTO students
        (name, email, password, department, year)
        VALUES (?, ?, ?, ?, ?)
    """, ("Demo Student", email, password, "Computer Science", 2))

    student = cursor.execute(
        "SELECT id FROM students WHERE email = ?", (email,)
    ).fetchone()

    student_id = student["id"]

    if cursor.execute(
        "SELECT COUNT(*) FROM attendance WHERE student_id = ?",
        (student_id,)
    ).fetchone()[0] == 0:

        for day, status in [
            ("2026-11-02", "Present"),
            ("2026-11-03", "Present"),
            ("2026-11-04", "Present"),
            ("2026-11-05", "Absent"),
            ("2026-11-06", "Present"),
            ("2026-11-09", "Present"),
            ("2026-11-10", "Present"),
            ("2026-11-11", "Present"),
            ("2026-11-12", "Absent"),
            ("2026-11-13", "Present")
        ]:
            cursor.execute("""
                INSERT INTO attendance (student_id, date, status)
                VALUES (?, ?, ?)
            """, (student_id, day, status))

    if cursor.execute(
        "SELECT COUNT(*) FROM marks WHERE student_id = ?",
        (student_id,)
    ).fetchone()[0] == 0:

        for subject, mark in [
            ("Mathematics", 86),
            ("Programming", 91),
            ("Database Systems", 84)
        ]:
            cursor.execute("""
                INSERT INTO marks (student_id, subject, marks)
                VALUES (?, ?, ?)
            """, (student_id, subject, mark))

    if cursor.execute(
        "SELECT COUNT(*) FROM fees WHERE student_id = ?",
        (student_id,)
    ).fetchone()[0] == 0:

        cursor.execute("""
            INSERT INTO fees
            (student_id, total_fee, paid_fee, balance)
            VALUES (?, ?, ?, ?)
        """, (student_id, 50000, 35000, 15000))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": "Student demo account is ready",
        "email": email
    })


# ---------------- EMPLOYEE DEMO ACCOUNT ----------------

@app.route("/api/setup-employee")
def setup_employee():
    conn = get_db_connection()

    email = "employee@lillian.edu"
    password = generate_password_hash("Employee@123")

    conn.execute("""
        INSERT OR IGNORE INTO employees
        (name, email, password, designation, department)
        VALUES (?, ?, ?, ?, ?)
    """, (
        "Demo Employee",
        email,
        password,
        "Assistant Professor",
        "Computer Science"
    ))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": "Employee demo account is ready",
        "email": email
    })


# ---------------- PARENT DEMO ACCOUNT ----------------

@app.route("/api/setup-parent")
def setup_parent():
    conn = get_db_connection()

    student = conn.execute(
        "SELECT id FROM students WHERE email = ?",
        ("student@lillian.edu",)
    ).fetchone()

    if not student:
        conn.close()
        return jsonify({
            "status": "error",
            "message": "Please run /api/setup-student first."
        }), 400

    student_id = student["id"]
    email = "parent@lillian.edu"
    password_hash = generate_password_hash("Parent@123")

    existing = conn.execute(
        "SELECT id FROM parents WHERE email = ?",
        (email,)
    ).fetchone()

    if existing is None:
        conn.execute("""
            INSERT INTO parents (name, email, password, student_id)
            VALUES (?, ?, ?, ?)
        """, ("Demo Parent", email, password_hash, student_id))
    else:
        conn.execute("""
            UPDATE parents
            SET password = ?, student_id = ?
            WHERE email = ?
        """, (password_hash, student_id, email))

    conn.commit()
    conn.close()

    return jsonify({
        "status": "success",
        "message": "Parent demo account is ready",
        "email": email
    })



# ---------------- FACULTY DEMO DATA ----------------

FACULTY_DEMO_RECORDS = [
    ("Dr. Meena Raj", "cse.hod@lillian.edu", "HOD", "CSE"),
    ("Prof. Ananya Krishnan", "cse.staff01@lillian.edu", "Assistant Professor", "CSE"),
    ("Mr. Arjun Prakash", "cse.staff02@lillian.edu", "Assistant Professor", "CSE"),
    ("Dr. Lakshmi Narayanan", "civil.hod@lillian.edu", "HOD", "Civil"),
    ("Prof. Gokul Raj", "civil.staff01@lillian.edu", "Assistant Professor", "Civil"),
    ("Ms. Aishwarya R", "civil.staff02@lillian.edu", "Assistant Professor", "Civil"),
    ("Dr. Suresh Balaji", "mech.hod@lillian.edu", "HOD", "Mechanical"),
    ("Prof. Karthik M", "mech.staff01@lillian.edu", "Assistant Professor", "Mechanical"),
    ("Ms. Janani Devi", "mech.staff02@lillian.edu", "Assistant Professor", "Mechanical"),
    ("Prof. Priya Nair", "ec.hod@lillian.edu", "HOD", "EC"),
    ("Dr. Sanjay Mohan", "ec.staff01@lillian.edu", "Assistant Professor", "EC"),
    ("Ms. Keerthana S", "ec.staff02@lillian.edu", "Assistant Professor", "EC"),
    ("Prof. Divya Menon", "eee.hod@lillian.edu", "HOD", "EEE"),
    ("Dr. Aravind Sekar", "eee.staff01@lillian.edu", "Assistant Professor", "EEE"),
    ("Mr. Sriram V", "eee.staff02@lillian.edu", "Assistant Professor", "EEE"),
    ("Dr. Revathi S", "mca.hod@lillian.edu", "HOD", "MCA"),
    ("Prof. Bala Murugan", "mca.staff01@lillian.edu", "Assistant Professor", "MCA"),
    ("Ms. Swetha Raj", "mca.staff02@lillian.edu", "Assistant Professor", "MCA"),
    ("Dr. Radhika Menon", "mba.hod@lillian.edu", "HOD", "MBA"),
    ("Prof. Prakash Anand", "mba.staff01@lillian.edu", "Assistant Professor", "MBA"),
    ("Ms. Farzana Ali", "mba.staff02@lillian.edu", "Assistant Professor", "MBA"),
]

@app.route("/api/setup-faculty")
def setup_faculty():
    """Synchronize the demo directory to the seven requested departments."""
    conn = get_db_connection()
    keep_emails = [r[1] for r in FACULTY_DEMO_RECORDS]
    # Remove only the previous generated faculty demo accounts, not unrelated employees.
    old_prefixes = ("cs.faculty", "it.faculty", "ece.faculty", "eee.faculty", "mech.faculty", "civil.faculty", "ds.faculty", "mca.faculty", "mba.faculty")
    for prefix in old_prefixes:
        conn.execute("DELETE FROM employees WHERE email LIKE ? AND email NOT IN (%s)" % (",".join("?" for _ in keep_emails)), (prefix + "%", *keep_emails))
    inserted = 0
    for name, email, designation, department in FACULTY_DEMO_RECORDS:
        cur = conn.execute("""INSERT INTO employees (name,email,password,designation,department)
            VALUES (?,?,?,?,?) ON CONFLICT(email) DO UPDATE SET name=excluded.name,
            designation=excluded.designation, department=excluded.department""",
            (name,email,generate_password_hash("Faculty@123"),designation,department))
        inserted += max(cur.rowcount, 0)
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM employees WHERE email IN (%s)" % ",".join("?" for _ in keep_emails), keep_emails).fetchone()[0]
    conn.close()
    return jsonify({"status":"success", "message":"Faculty directory synchronized.",
                    "total_faculty_records":total, "departments":7,
                    "staff_structure":"1 HOD + 2 staff per department"})


@app.route("/api/faculty")
def get_faculty():
    """Staff directory is available only to the authenticated administrator."""
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Administrator sign-in required."}), 401
    conn = get_db_connection()
    faculty = conn.execute("""
        SELECT id, name, email, designation, department
        FROM employees
        WHERE designation IN ('HOD', 'Professor', 'Assistant Professor')
          AND LOWER(email) != 'employee@lillian.edu'
          AND LOWER(name) != 'demo employee'
        ORDER BY department,
                 CASE designation
                     WHEN 'HOD' THEN 1
                     WHEN 'Professor' THEN 2
                     ELSE 3
                 END,
                 name
    """).fetchall()
    conn.close()

    return jsonify({
        "status": "success",
        "faculty": [dict(row) for row in faculty]
    })


@app.route("/api/public-faculty")
def get_public_faculty():
    """Public homepage directory: names, designations and departments only."""
    conn = get_db_connection()
    try:
        faculty = conn.execute("""
            SELECT name, designation, department
            FROM employees
            WHERE designation IN ('HOD', 'Professor', 'Assistant Professor')
              AND LOWER(email) != 'employee@lillian.edu'
              AND LOWER(name) != 'demo employee'
            ORDER BY department,
                     CASE designation
                         WHEN 'HOD' THEN 1
                         WHEN 'Professor' THEN 2
                         ELSE 3
                     END,
                     name
        """).fetchall()
        return jsonify({
            "status": "success",
            "faculty": [dict(row) for row in faculty]
        })
    finally:
        conn.close()



@app.route("/api/student-directory")
def student_directory():
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Administrator sign-in required."}), 401
    conn=get_db_connection()
    ensure_academic_schema(conn)
    rows=conn.execute("""
        SELECT student_id,name,email,department,year
        FROM students ORDER BY department,year,student_id
    """).fetchall()
    conn.close()
    return jsonify({"status":"success","students":[dict(r) for r in rows]})



# ---------------- STUDENT LOGIN ----------------

@app.route("/api/login", methods=["POST"])
def student_login():
    data = request.get_json(silent=True) or {}

    email = data.get("email", "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({
            "status": "error",
            "message": "Enter email and password."
        }), 400

    conn = get_db_connection()

    student = conn.execute("""
        SELECT id, name, email, password
        FROM students WHERE email = ?
    """, (email,)).fetchone()

    conn.close()

    if student and student["password"] and check_password_hash(
        student["password"], password
    ):
        session.clear()
        session["student_id"] = student["id"]
        session["role"] = "student"

        return jsonify({
            "status": "success",
            "role": "student",
            "name": student["name"]
        })

    return jsonify({
        "status": "error",
        "message": "Invalid student email or password."
    }), 401


# ---------------- EMPLOYEE LOGIN ----------------

@app.route("/api/employee-login", methods=["POST"])
def employee_login():
    """Authenticate employees with their registered email address and password."""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    password = data.get("password", "")
    if not email or "@" not in email or not password:
        return jsonify({"status": "error", "message": "Enter a valid employee email and password."}), 400

    conn = get_db_connection()
    try:
        employee = conn.execute("""
            SELECT id, name, email, password, designation, department, employee_code
            FROM employees
            WHERE LOWER(TRIM(email)) = ?
            LIMIT 1
        """, (email,)).fetchone()
    finally:
        conn.close()

    if employee and employee["password"] and check_password_hash(employee["password"], password):
        session.clear()
        session["employee_id"] = employee["id"]
        session["role"] = "employee"
        return jsonify({
            "status": "success",
            "role": "employee",
            "name": employee["name"],
            "email": employee["email"]
        })

    return jsonify({"status": "error", "message": "Invalid employee email or password."}), 401


# ---------------- PARENT LOGIN ----------------

@app.route("/api/parent-login", methods=["POST"])
def parent_login():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    student_code = str(data.get("student_id", "")).strip().upper()
    password = data.get("password", "")
    if not email or "@" not in email or "." not in email.split("@")[-1] or not student_code or not password:
        return jsonify({"status":"error","message":"Enter a valid parent email, Student ID and password."}), 400
    conn = get_db_connection()
    ensure_academic_schema(conn)
    student = conn.execute("SELECT id,name,student_id FROM students WHERE UPPER(student_id)=?", (student_code,)).fetchone()
    if not student:
        conn.close()
        return jsonify({"status":"error","message":"Student ID not found. Please check the Student ID."}), 404
    parent = conn.execute("SELECT id,password FROM parents WHERE email=?", (email,)).fetchone()
    if parent:
        if not parent["password"] or not check_password_hash(parent["password"], password):
            conn.close()
            return jsonify({"status":"error","message":"Incorrect parent password for this email."}), 401
        conn.execute("UPDATE parents SET student_id=? WHERE id=?", (student["id"],parent["id"]))
        parent_id=parent["id"]
    else:
        cursor=conn.execute("""
            INSERT INTO parents(name,email,password,student_id)
            VALUES(?,?,?,?)
        """, (f"Parent of {student['name']}",email,generate_password_hash(password),student["id"]))
        parent_id=cursor.lastrowid
    conn.commit()
    conn.close()
    session.clear()
    session["parent_id"]=parent_id
    session["student_id"]=student["id"]
    session["role"]="parent"
    return jsonify({"status":"success","role":"parent","name":f"Parent of {student['name']}"})


# ---------------- PARENT DASHBOARD DATA ----------------

@app.route("/api/parent-dashboard")
def parent_dashboard():

    if session.get("role") != "parent" or not session.get("student_id"):
        return jsonify({
            "status": "error",
            "message": "Please sign in as a parent."
        }), 401

    conn = get_db_connection()
    student_id = session["student_id"]

    student = conn.execute("""
        SELECT id, student_id, name, email, department, year
        FROM students WHERE id = ?
    """, (student_id,)).fetchone()

    attendance = conn.execute("""
        SELECT date, status
        FROM attendance
        WHERE student_id = ?
        ORDER BY date DESC
    """, (student_id,)).fetchall()

    marks = conn.execute("""
        SELECT subject, marks
        FROM marks
        WHERE student_id = ?
    """, (student_id,)).fetchall()

    fee = conn.execute("""
        SELECT total_fee, paid_fee, balance
        FROM fees
        WHERE student_id = ?
        ORDER BY id DESC LIMIT 1
    """, (student_id,)).fetchone()

    conn.close()

    if not student:
        return jsonify({
            "status": "error",
            "message": "Linked student not found."
        }), 404

    total_days = len(attendance)

    present_days = sum(
        1 for row in attendance
        if row["status"].lower() == "present"
    )

    attendance_percentage = (
        round((present_days / total_days) * 100, 1)
        if total_days else 0
    )

    mark_values = [row["marks"] for row in marks]

    average_marks = (
        round(sum(mark_values) / len(mark_values), 1)
        if mark_values else 0
    )

    return jsonify({
        "status": "success",
        "student": dict(student),

        "attendance": {
            "percentage": attendance_percentage,
            "present_days": present_days,
            "total_days": total_days,
            "records": [dict(row) for row in attendance]
        },

        "marks": {
            "average": average_marks,
            "records": [dict(row) for row in marks]
        },

        "fees": dict(fee) if fee else {
            "total_fee": 0,
            "paid_fee": 0,
            "balance": 0
        }
    })


# ---------------- STUDENT DASHBOARD DATA ----------------

@app.route("/api/student-dashboard")
def student_dashboard():

    if session.get("role") != "student":
        return jsonify({
            "status": "error",
            "message": "Please sign in."
        }), 401

    conn = get_db_connection()
    student_id = session["student_id"]

    student = conn.execute("""
        SELECT id, name, email, department, year
        FROM students WHERE id = ?
    """, (student_id,)).fetchone()

    attendance = conn.execute("""
        SELECT status
        FROM attendance
        WHERE student_id = ?
    """, (student_id,)).fetchall()

    marks = conn.execute("""
        SELECT subject, marks
        FROM marks
        WHERE student_id = ?
    """, (student_id,)).fetchall()

    fee = conn.execute("""
        SELECT total_fee, paid_fee, balance
        FROM fees
        WHERE student_id = ?
        ORDER BY id DESC LIMIT 1
    """, (student_id,)).fetchone()

    conn.close()

    if not student:
        return jsonify({
            "status": "error",
            "message": "Student not found."
        }), 404

    total = len(attendance)

    present = sum(
        1 for row in attendance
        if row["status"].lower() == "present"
    )

    percentage = round((present / total) * 100) if total else 0

    mark_values = [row["marks"] for row in marks]

    average = (
        round(sum(mark_values) / len(mark_values), 1)
        if mark_values else 0
    )

    return jsonify({
        "status": "success",
        "student": dict(student),

        "attendance": {
            "percentage": f"{percentage}%",
            "note": f"{present} present out of {total} recorded days"
        },

        "marks": {
            "average": f"{average}/100",
            "subject_count": len(marks)
        },

        "fees": {
            "balance": f"₹{fee['balance']:,.0f}" if fee else "₹0",
            "paid": f"₹{fee['paid_fee']:,.0f}" if fee else "₹0"
        }
    })


# ---------------- EMPLOYEE DASHBOARD DATA ----------------

@app.route("/api/employee-dashboard")
def employee_dashboard():

    if session.get("role") != "employee":
        return jsonify({
            "status": "error",
            "message": "Please sign in as an employee."
        }), 401

    conn = get_db_connection()

    employee = conn.execute("""
        SELECT id, name, email, designation, department
        FROM employees WHERE id = ?
    """, (session["employee_id"],)).fetchone()

    conn.close()

    if not employee:
        session.clear()
        return jsonify({
            "status": "error",
            "message": "Employee account not found."
        }), 404

    return jsonify({
        "status": "success",
        "employee": dict(employee),
        "message": "Employee information loaded from SQLite database."
    })




# ---------------- FACULTY MY CLASSES ----------------

DEPARTMENT_SUBJECTS = {
    "Computer Science": ["Data Structures", "Database Management Systems", "Operating Systems", "Python Programming"],
    "IT": ["Web Technology", "Computer Networks", "Cloud Computing", "Information Security"],
    "ECE": ["Digital Electronics", "Signals and Systems", "Microprocessors", "Communication Systems"],
    "EEE": ["Electrical Machines", "Power Systems", "Control Systems", "Power Electronics"],
    "Mechanical": ["Thermodynamics", "Fluid Mechanics", "Manufacturing Technology", "Machine Design"],
    "Civil": ["Structural Analysis", "Surveying", "Concrete Technology", "Geotechnical Engineering"],
    "EC": ["Electronic Devices", "Digital Communication", "Signals and Systems", "Embedded Systems"],
    "CSE": ["Data Structures", "Database Management", "Operating Systems", "Computer Networks"],
    "Civil": ["Structural Analysis", "Surveying", "Concrete Technology", "Geotechnical Engineering"],
    "Mechanical": ["Thermodynamics", "Manufacturing Technology", "Fluid Mechanics", "Machine Design"],
    "EEE": ["Electrical Machines", "Power Systems", "Control Systems", "Power Electronics"],
    "MCA": ["Advanced Java", "Software Engineering", "Data Mining", "Mobile Application Development"],
    "MBA": ["Marketing Management", "Financial Management", "Human Resource Management", "Business Analytics"]
}

@app.route("/api/employee-classes")
def employee_classes():
    if session.get("role") != "employee" or not session.get("employee_id"):
        return jsonify({
            "status": "error",
            "message": "Please sign in as a faculty member."
        }), 401

    conn = get_db_connection()
    try:
        # Create this feature's table safely without changing existing tables.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS faculty_classes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                class_name TEXT NOT NULL,
                year INTEGER NOT NULL,
                section TEXT NOT NULL,
                room TEXT NOT NULL,
                schedule TEXT NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id),
                UNIQUE(employee_id, subject, class_name)
            )
        """)

        # Add illustrative demo class allocations for the 36 demo faculty accounts.
        # Existing faculty/HOD and employee records are not overwritten.
        for faculty_index, (name, email, designation, department) in enumerate(FACULTY_DEMO_RECORDS):
            employee = conn.execute(
                "SELECT id FROM employees WHERE email = ?", (email,)
            ).fetchone()
            if not employee:
                continue

            subjects = DEPARTMENT_SUBJECTS.get(department, ["Core Subject", "Practical Session"])
            subject_pair = subjects[(faculty_index % 4 // 2) * 2 : (faculty_index % 4 // 2) * 2 + 2]
            if len(subject_pair) < 2:
                subject_pair = subjects[:2]

            for subject_index, subject in enumerate(subject_pair):
                year = 1 + ((faculty_index + subject_index) % 4)
                section = "A" if subject_index == 0 else "B"
                conn.execute("""
                    INSERT OR IGNORE INTO faculty_classes
                    (employee_id, subject, class_name, year, section, room, schedule)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    employee["id"],
                    subject,
                    f"{department} - Year {year}",
                    year,
                    section,
                    f"Block {['A', 'B', 'C', 'D'][faculty_index % 4]} - Room {101 + faculty_index % 20}",
                    ["Mon & Wed, 10:00-11:00 AM", "Tue & Thu, 2:00-3:00 PM"][subject_index]
                ))

        conn.commit()
        rows = conn.execute("""
            SELECT subject, class_name, year, section, room, schedule
            FROM faculty_classes
            WHERE employee_id = ?
            ORDER BY year, subject
        """, (session["employee_id"],)).fetchall()

        employee = conn.execute(
            "SELECT department FROM employees WHERE id = ?",
            (session["employee_id"],)
        ).fetchone()

        return jsonify({
            "status": "success",
            "department": employee["department"] if employee else "",
            "classes": [dict(row) for row in rows],
            "message": "Demo class allocations loaded from SQLite."
        })
    finally:
        conn.close()



# ---------------- EMPLOYEE ACTIVITY: SQLITE PERSISTENCE ----------------

def ensure_employee_activity_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS employee_attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            class_section TEXT NOT NULL,
            attendance_date TEXT NOT NULL,
            subject TEXT NOT NULL,
            attendance_status TEXT NOT NULL CHECK(attendance_status IN ('Present','Absent')),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
        );

        CREATE TABLE IF NOT EXISTS employee_marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            class_section TEXT NOT NULL,
            subject TEXT NOT NULL,
            assessment TEXT NOT NULL,
            register_number TEXT NOT NULL,
            marks REAL NOT NULL CHECK(marks >= 0),
            max_marks REAL NOT NULL DEFAULT 100 CHECK(max_marks > 0),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
        );

        CREATE TABLE IF NOT EXISTS employee_leave_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            from_date TEXT NOT NULL,
            to_date TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Pending',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (employee_id) REFERENCES employees(id)
        );
    """)


def employee_session_required():
    return session.get("role") == "employee" and session.get("employee_id")


@app.route("/api/employee-attendance", methods=["POST"])
def save_employee_attendance():
    if not employee_session_required():
        return jsonify({"status": "error", "message": "Please sign in as faculty."}), 401
    data = request.get_json(silent=True) or {}
    class_section = str(data.get("class_section", "")).strip()
    attendance_date = str(data.get("attendance_date", "")).strip()
    subject = str(data.get("subject", "")).strip()
    attendance_status = str(data.get("attendance_status", "")).strip()
    if not all([class_section, attendance_date, subject]) or attendance_status not in ("Present", "Absent"):
        return jsonify({"status": "error", "message": "Please complete all attendance fields."}), 400
    conn = get_db_connection()
    try:
        ensure_employee_activity_tables(conn)
        conn.execute("""
            INSERT INTO employee_attendance
            (employee_id, class_section, attendance_date, subject, attendance_status)
            VALUES (?, ?, ?, ?, ?)
        """, (session["employee_id"], class_section, attendance_date, subject, attendance_status))
        conn.commit()
        return jsonify({"status": "success", "message": "Attendance saved successfully in SQLite."})
    finally:
        conn.close()


@app.route("/api/employee-marks", methods=["POST"])
def save_employee_marks():
    if not employee_session_required():
        return jsonify({"status": "error", "message": "Please sign in as faculty."}), 401
    data = request.get_json(silent=True) or {}
    class_section = str(data.get("class_section", "")).strip()
    subject = str(data.get("subject", "")).strip()
    assessment = str(data.get("assessment", "")).strip()
    register_number = str(data.get("register_number", "")).strip()
    try:
        marks = float(data.get("marks"))
        max_marks = float(data.get("max_marks", 100))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Enter valid marks."}), 400
    if not all([class_section, subject, assessment, register_number]) or max_marks <= 0 or marks < 0 or marks > max_marks:
        return jsonify({"status": "error", "message": "Complete all fields. Marks must be between 0 and maximum marks."}), 400
    conn = get_db_connection()
    try:
        ensure_employee_activity_tables(conn)
        conn.execute("""
            INSERT INTO employee_marks
            (employee_id, class_section, subject, assessment, register_number, marks, max_marks)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (session["employee_id"], class_section, subject, assessment, register_number, marks, max_marks))
        conn.commit()
        return jsonify({"status": "success", "message": "Marks saved successfully in SQLite."})
    finally:
        conn.close()


@app.route("/api/employee-leave", methods=["POST"])
def save_employee_leave():
    if not employee_session_required():
        return jsonify({"status": "error", "message": "Please sign in as faculty."}), 401
    data = request.get_json(silent=True) or {}
    from_date = str(data.get("from_date", "")).strip()
    to_date = str(data.get("to_date", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if not all([from_date, to_date, reason]) or to_date < from_date:
        return jsonify({"status": "error", "message": "Enter valid dates and a reason. To date cannot be before From date."}), 400
    conn = get_db_connection()
    try:
        ensure_employee_activity_tables(conn)
        conn.execute("""
            INSERT INTO employee_leave_requests (employee_id, from_date, to_date, reason)
            VALUES (?, ?, ?, ?)
        """, (session["employee_id"], from_date, to_date, reason))
        conn.commit()
        return jsonify({"status": "success", "message": "Leave request saved in SQLite with Pending status."})
    finally:
        conn.close()


@app.route("/api/employee-records")
def get_employee_records():
    if not employee_session_required():
        return jsonify({"status": "error", "message": "Please sign in as faculty."}), 401
    conn = get_db_connection()
    try:
        ensure_employee_activity_tables(conn)
        employee_id = session["employee_id"]
        attendance = conn.execute("""
            SELECT class_section, attendance_date, subject, attendance_status, created_at
            FROM employee_attendance WHERE employee_id = ?
            ORDER BY id DESC LIMIT 20
        """, (employee_id,)).fetchall()
        marks = conn.execute("""
            SELECT class_section, subject, assessment, register_number, marks, max_marks, created_at
            FROM employee_marks WHERE employee_id = ?
            ORDER BY id DESC LIMIT 20
        """, (employee_id,)).fetchall()
        leaves = conn.execute("""
            SELECT from_date, to_date, reason, status, created_at
            FROM employee_leave_requests WHERE employee_id = ?
            ORDER BY id DESC LIMIT 20
        """, (employee_id,)).fetchall()
        conn.commit()
        return jsonify({
            "status": "success",
            "attendance": [dict(row) for row in attendance],
            "marks": [dict(row) for row in marks],
            "leaves": [dict(row) for row in leaves]
        })
    finally:
        conn.close()



# ---------------- GROQ-POWERED ROLE-AWARE CAMPUS AGENT ----------------
def get_my_campus_info(category, role):
    """Return only the authenticated user's own permitted campus records."""
    conn = get_db_connection()
    try:
        if role in ("student", "parent"):
            sid = session.get("student_id")
            student = conn.execute(
                "SELECT id, name, email, department, year FROM students WHERE id=?", (sid,)
            ).fetchone()
            if not student:
                return {"error": "Linked student account not found."}
            if category == "profile":
                return {"profile": dict(student)}
            if category == "attendance":
                rows = conn.execute("SELECT date,status FROM attendance WHERE student_id=? ORDER BY date DESC LIMIT 30", (sid,)).fetchall()
                total = len(rows); present = sum(1 for r in rows if str(r["status"]).lower() == "present")
                return {"attendance": [dict(r) for r in rows], "present_days": present, "recorded_days": total,
                        "percentage": round(present * 100 / total, 1) if total else 0}
            if category == "marks":
                rows = conn.execute("SELECT subject,marks FROM marks WHERE student_id=? ORDER BY subject", (sid,)).fetchall()
                return {"marks": [dict(r) for r in rows]}
            if category == "fees":
                row = conn.execute("SELECT total_fee,paid_fee,balance FROM fees WHERE student_id=? ORDER BY id DESC LIMIT 1", (sid,)).fetchone()
                return {"fees": dict(row) if row else None}
            if category == "announcements":
                # Announcements are general public campus information, not private student records.
                return {"announcements": "Please check the Announcements section of the portal for the latest notices."}
        elif role == "employee":
            ensure_employee_activity_tables(conn)
            employee = conn.execute("SELECT id,name,email,designation,department FROM employees WHERE id=?", (session.get("employee_id"),)).fetchone()
            if not employee:
                return {"error": "Employee account not found."}
            eid = employee["id"]
            if category == "profile":
                return {"profile": dict(employee)}
            if category == "attendance":
                rows = conn.execute("SELECT class_section,attendance_date,subject,attendance_status FROM employee_attendance WHERE employee_id=? ORDER BY id DESC LIMIT 20", (eid,)).fetchall()
                return {"attendance_entries": [dict(r) for r in rows]}
            if category == "marks":
                rows = conn.execute("SELECT class_section,subject,assessment,register_number,marks,max_marks FROM employee_marks WHERE employee_id=? ORDER BY id DESC LIMIT 20", (eid,)).fetchall()
                return {"marks_entries": [dict(r) for r in rows]}
            if category == "leave":
                rows = conn.execute("SELECT from_date,to_date,reason,status,created_at FROM employee_leave_requests WHERE employee_id=? ORDER BY id DESC LIMIT 20", (eid,)).fetchall()
                return {"leave_requests": [dict(r) for r in rows]}
        return {"message": "That category is not available for this portal role."}
    finally:
        conn.close()



def get_college_overview(topic, role):
    """Institution-wide, aggregate-only information. Never returns an individual's private record."""
    public_topics = {"students", "employees", "courses"}
    staff_topics = {"attendance_stats", "marks_stats", "fee_stats"}
    if topic in staff_topics and role != "employee":
        return {"message": "Detailed institution-wide statistics are available to signed-in employees only."}
    if topic not in public_topics | staff_topics:
        return {"message": "Unknown topic."}
    conn = get_db_connection()
    try:
        if topic == "students":
            total = conn.execute("SELECT COUNT(*) FROM students").fetchone()[0]
            by_dept = conn.execute("SELECT department, COUNT(*) c FROM students GROUP BY department ORDER BY department").fetchall()
            by_year = conn.execute("SELECT year, COUNT(*) c FROM students GROUP BY year ORDER BY year").fetchall()
            return {"total_students_registered_in_portal": total,
                    "by_department": {r["department"] or "Unknown": r["c"] for r in by_dept},
                    "by_year": {str(r["year"]): r["c"] for r in by_year},
                    "note": "Counts of students currently registered in the demo portal database. No alumni data is recorded."}
        if topic == "employees":
            total = conn.execute("SELECT COUNT(*) FROM employees WHERE LOWER(name) != 'demo employee'").fetchone()[0]
            by_desig = conn.execute("SELECT designation, COUNT(*) c FROM employees WHERE LOWER(name) != 'demo employee' GROUP BY designation").fetchall()
            by_dept = conn.execute("SELECT department, COUNT(*) c FROM employees WHERE LOWER(name) != 'demo employee' GROUP BY department ORDER BY department").fetchall()
            return {"total_employees": total,
                    "by_designation": {r["designation"] or "Unknown": r["c"] for r in by_desig},
                    "by_department": {r["department"] or "Unknown": r["c"] for r in by_dept}}
        if topic == "courses":
            try:
                rows = conn.execute("SELECT program_code, department_code, course_name, duration_years FROM courses ORDER BY program_code, department_code").fetchall()
                return {"courses": [dict(r) for r in rows], "total": len(rows)}
            except sqlite3.Error:
                return {"message": "Course table not available yet."}
        if topic == "attendance_stats":
            rows = conn.execute("""SELECT s.department d, COUNT(*) n, SUM(CASE WHEN LOWER(a.status)='present' THEN 1 ELSE 0 END) p
                                   FROM attendance a JOIN students s ON s.id=a.student_id GROUP BY s.department""").fetchall()
            tot = sum(r["n"] for r in rows); pres = sum(r["p"] or 0 for r in rows)
            return {"overall_attendance_percent": round(pres * 100 / tot, 1) if tot else None,
                    "by_department_percent": {r["d"] or "Unknown": round((r["p"] or 0) * 100 / r["n"], 1) for r in rows if r["n"]}}
        if topic == "marks_stats":
            by_sub = conn.execute("SELECT subject, ROUND(AVG(marks),1) a, COUNT(*) n FROM marks GROUP BY subject ORDER BY subject").fetchall()
            by_dept = conn.execute("SELECT s.department d, ROUND(AVG(m.marks),1) a FROM marks m JOIN students s ON s.id=m.student_id GROUP BY s.department").fetchall()
            return {"average_marks_by_subject": {r["subject"]: r["a"] for r in by_sub},
                    "average_marks_by_department": {r["d"] or "Unknown": r["a"] for r in by_dept}}
        if topic == "fee_stats":
            r = conn.execute("SELECT COALESCE(SUM(total_fee),0) t, COALESCE(SUM(paid_fee),0) p, COALESCE(SUM(balance),0) b, SUM(CASE WHEN balance>0 THEN 1 ELSE 0 END) pend, COUNT(*) n FROM fees").fetchone()
            return {"total_fee": r["t"], "collected": r["p"], "pending_balance": r["b"],
                    "students_with_pending_balance": r["pend"] or 0, "students_with_fee_record": r["n"]}
    finally:
        conn.close()


def load_extra_college_info():
    """Optional college_info.txt (edit in Notepad): fees, eligibility, placements, etc. Lines starting with # are ignored."""
    for folder in (BACKEND_DIR, BASE_DIR):
        path = folder / "college_info.txt"
        if path.exists():
            try:
                lines = [l.rstrip() for l in path.read_text(encoding="utf-8").splitlines() if l.strip() and not l.lstrip().startswith("#")]
            except OSError:
                return ""
            if lines:
                return "ADDITIONAL COLLEGE INFORMATION PROVIDED BY THE COLLEGE (treat as official):\n" + "\n".join(lines) + "\n"
    return ""


COLLEGE_FACTS = (
    "OFFICIAL PUBLISHED FACTS ABOUT LILLIAN INSTITUTE OF TECHNOLOGY (use these; they override general knowledge):\n"
    "- Programmes: BE (4 years) in CSE, Civil, Mechanical, Electronics & Communication (EC), Electrical & Electronics (EEE); "
    "ME (2 years) in the same five engineering branches; MCA (2 years); MBA (2 years). That is 12 programmes in total "
    "(5 BE + 5 ME + 1 MCA + 1 MBA) across 7 departments: CSE, Civil, Mechanical, EC, EEE, MCA, MBA.\n"
    "- The college does NOT list an IT department, a 3-year MCA, or any specialisations/eligibility percentages. Do not mention them.\n"
    "- Each department has 1 HOD and 2 faculty staff members.\n"
    "- Admissions are open for 2026-27. Contact: +91 98765 43210, info@lillian.edu.in.\n"
    "- Fees, eligibility, deadlines and placement figures are not published unless listed under ADDITIONAL COLLEGE INFORMATION below: if absent, say so and suggest contacting the college.\n"
)


def get_faculty_facts():
    """Faculty/HOD names from the database, so the assistant answers with real records."""
    try:
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT name, designation, department FROM employees "
            "WHERE designation IN ('HOD','Professor','Assistant Professor') AND LOWER(name) != 'demo employee' "
            "ORDER BY department, CASE designation WHEN 'HOD' THEN 1 ELSE 2 END, name"
        ).fetchall()
        conn.close()
    except Exception:
        return ""
    lines = [f"{r['department']}: {r['name']} ({r['designation']})" for r in rows]
    return "Faculty directory (demo records):\n" + "\n".join(lines) + "\n" if lines else ""



# ---------------- ADMIN LOGIN + ADMIN-ONLY DATA ----------------
_ADMIN_FAILS = {}  # ip -> [failed_count, first_failure_time]


@app.route("/api/admin-login", methods=["POST"])
def admin_login():
    expected_password = os.environ.get("ADMIN_PASSWORD", "")
    expected_user = os.environ.get("ADMIN_USERNAME", "admin")
    if not expected_password:
        return jsonify({"status": "error", "message": "Admin login is not configured. Add ADMIN_PASSWORD to backend/.env and restart the server."}), 503
    ip = request.remote_addr or "unknown"
    count, first = _ADMIN_FAILS.get(ip, [0, 0])
    if count >= 5 and time.time() - first < 300:
        return jsonify({"status": "error", "message": "Too many failed attempts. Please wait 5 minutes and try again."}), 429
    data = request.get_json(silent=True) or {}
    user_ok = hmac.compare_digest(str(data.get("username", "")).strip().encode(), expected_user.encode())
    pass_ok = hmac.compare_digest(str(data.get("password", "")).encode(), expected_password.encode())
    if user_ok and pass_ok:
        _ADMIN_FAILS.pop(ip, None)
        session.clear()
        session["role"] = "admin"
        return jsonify({"status": "success", "role": "admin", "name": "Administrator"})
    if count == 0 or time.time() - first >= 300:
        _ADMIN_FAILS[ip] = [1, time.time()]
    else:
        _ADMIN_FAILS[ip][0] += 1
    return jsonify({"status": "error", "message": "Invalid admin username or password."}), 401


def get_admin_data(topic, search="", threshold=75):
    """Full read-only access to student/staff records. Only ever called when the session role is admin."""
    conn = get_db_connection()
    LIMIT = 5000
    try:
        like = f"%{str(search).strip()}%"
        if topic == "students_list":
            rows = conn.execute("SELECT id,name,email,department,year FROM students ORDER BY department,year,name LIMIT ?", (LIMIT,)).fetchall()
            return {"students": [dict(r) for r in rows], "shown_max": LIMIT}
        if topic == "student_attendance":
            rows = conn.execute("""
                SELECT s.id, s.name, s.email, s.department, s.year,
                       a.date, a.status
                FROM attendance a JOIN students s ON s.id = a.student_id
                ORDER BY a.date DESC, s.department, s.name LIMIT ?
            """, (LIMIT,)).fetchall()
            return {"student_attendance": [dict(r) for r in rows], "shown_max": LIMIT}
        if topic == "student_marks":
            rows = conn.execute("""
                SELECT s.id, s.name, s.email, s.department, s.year,
                       m.subject, m.marks
                FROM marks m JOIN students s ON s.id = m.student_id
                ORDER BY s.department, s.name, m.subject LIMIT ?
            """, (LIMIT,)).fetchall()
            return {"student_marks": [dict(r) for r in rows], "shown_max": LIMIT}
        if topic == "student_fees":
            rows = conn.execute("""
                SELECT s.id, s.name, s.email, s.department, s.year,
                       f.total_fee, f.paid_fee, f.balance
                FROM fees f JOIN students s ON s.id = f.student_id
                ORDER BY f.balance DESC, s.name LIMIT ?
            """, (LIMIT,)).fetchall()
            return {"student_fees": [dict(r) for r in rows], "shown_max": LIMIT}
        if topic == "student_detail":
            students = conn.execute(
                "SELECT id,name,email,department,year FROM students WHERE name LIKE ? OR email LIKE ? OR CAST(id AS TEXT)=? LIMIT 3",
                (like, like, str(search).strip())).fetchall()
            out = []
            for st in students:
                att = conn.execute("SELECT COUNT(*) n, SUM(CASE WHEN LOWER(status)='present' THEN 1 ELSE 0 END) p FROM attendance WHERE student_id=?", (st["id"],)).fetchone()
                marks = conn.execute("SELECT subject,marks FROM marks WHERE student_id=? ORDER BY subject", (st["id"],)).fetchall()
                fee = conn.execute("SELECT total_fee,paid_fee,balance FROM fees WHERE student_id=? ORDER BY id DESC LIMIT 1", (st["id"],)).fetchone()
                out.append({"profile": dict(st),
                            "attendance": {"recorded_days": att["n"], "present_days": att["p"] or 0,
                                           "percentage": round((att["p"] or 0) * 100 / att["n"], 1) if att["n"] else None},
                            "marks": [dict(m) for m in marks], "fees": dict(fee) if fee else None})
            return {"matches": out} if out else {"message": "No student matched that search."}
        if topic == "employees_list":
            rows = conn.execute("SELECT id,name,email,designation,department FROM employees ORDER BY department, designation, name LIMIT ?", (LIMIT,)).fetchall()
            return {"employees": [dict(r) for r in rows]}
        if topic == "employee_attendance":
            ensure_employee_activity_tables(conn)
            rows = conn.execute("""
                SELECT e.id, e.name, e.email, e.designation, e.department,
                       a.class_section, a.attendance_date, a.subject, a.attendance_status
                FROM employee_attendance a JOIN employees e ON e.id = a.employee_id
                ORDER BY a.attendance_date DESC, e.department, e.name LIMIT ?
            """, (LIMIT,)).fetchall()
            return {"employee_attendance": [dict(r) for r in rows], "shown_max": LIMIT}
        if topic == "employee_marks":
            ensure_employee_activity_tables(conn)
            rows = conn.execute("""
                SELECT e.id, e.name, e.email, e.designation, e.department,
                       m.class_section, m.subject, m.assessment,
                       m.register_number, m.marks, m.max_marks
                FROM employee_marks m JOIN employees e ON e.id = m.employee_id
                ORDER BY e.department, e.name, m.created_at DESC LIMIT ?
            """, (LIMIT,)).fetchall()
            return {"employee_marks": [dict(r) for r in rows], "shown_max": LIMIT}
        if topic == "employee_activity":
            ensure_employee_activity_tables(conn)
            emps = conn.execute("SELECT id,name,email,designation,department FROM employees WHERE name LIKE ? OR email LIKE ? OR CAST(id AS TEXT)=? LIMIT 3",
                                (like, like, str(search).strip())).fetchall()
            out = []
            for e in emps:
                att = conn.execute("SELECT class_section,attendance_date,subject,attendance_status FROM employee_attendance WHERE employee_id=? ORDER BY id DESC LIMIT 15", (e["id"],)).fetchall()
                leave = conn.execute("SELECT from_date,to_date,reason,status FROM employee_leave_requests WHERE employee_id=? ORDER BY id DESC LIMIT 10", (e["id"],)).fetchall()
                nmarks = conn.execute("SELECT COUNT(*) FROM employee_marks WHERE employee_id=?", (e["id"],)).fetchone()[0]
                out.append({"profile": dict(e), "recent_attendance_entries": [dict(a) for a in att],
                            "leave_requests": [dict(l) for l in leave], "marks_entries_recorded": nmarks})
            return {"matches": out} if out else {"message": "No employee matched that search."}
        if topic == "low_attendance":
            rows = conn.execute("""SELECT s.id, s.name, s.department, s.year, COUNT(*) n,
                                   SUM(CASE WHEN LOWER(a.status)='present' THEN 1 ELSE 0 END) p
                                   FROM attendance a JOIN students s ON s.id=a.student_id GROUP BY s.id""").fetchall()
            low = sorted(({"name": r["name"], "department": r["department"], "year": r["year"],
                           "percentage": round((r["p"] or 0) * 100 / r["n"], 1)} for r in rows if r["n"]),
                         key=lambda x: x["percentage"])
            low = [x for x in low if x["percentage"] < float(threshold)]
            return {"threshold_percent": float(threshold), "students_below_threshold": low[:LIMIT], "count": len(low)}
        if topic == "fees_pending":
            rows = conn.execute("""SELECT s.name, s.department, s.year, f.total_fee, f.paid_fee, f.balance FROM fees f
                                   JOIN students s ON s.id=f.student_id WHERE f.balance>0 ORDER BY f.balance DESC LIMIT ?""", (LIMIT,)).fetchall()
            return {"students_with_pending_fees": [dict(r) for r in rows]}
        if topic == "department_summary":
            rows = conn.execute("""SELECT s.department d, COUNT(DISTINCT s.id) students,
                (SELECT ROUND(AVG(m.marks),1) FROM marks m JOIN students x ON x.id=m.student_id WHERE x.department=s.department) avg_marks,
                (SELECT COALESCE(SUM(f.balance),0) FROM fees f JOIN students x ON x.id=f.student_id WHERE x.department=s.department) pending_fees
                FROM students s GROUP BY s.department""").fetchall()
            return {"departments": [dict(r) for r in rows]}
        return {"message": "Unknown topic."}
    finally:
        conn.close()


@app.route("/api/admin-data", methods=["GET", "POST"])
def admin_data_api():
    """Admin Portal data API. All private college records require an admin session."""
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Administrator sign-in required."}), 401
    payload = request.get_json(silent=True) or {}
    topic = str(request.args.get("topic") or payload.get("topic") or "").strip()
    search = str(request.args.get("search") or payload.get("search") or "").strip()
    try:
        threshold = float(request.args.get("threshold") or payload.get("threshold") or 75)
    except (TypeError, ValueError):
        threshold = 75
    allowed_topics = {
        "students_list", "student_detail", "student_attendance", "student_marks", "student_fees",
        "employees_list", "employee_activity", "employee_attendance", "employee_marks",
        "low_attendance", "fees_pending", "department_summary"
    }
    if topic not in allowed_topics:
        return jsonify({"status": "error", "message": "Invalid Admin Portal data category."}), 400
    return jsonify({"status": "success", **get_admin_data(topic, search, threshold)})






def _admin_insights_fast_path(conn, question):
    """Handle common admin list/count questions directly and safely with SQLite."""
    q = re.sub(r"\s+", " ", question.lower()).strip()
    limit = 200

    def has_any(*terms):
        return any(term in q for term in terms)

    def table_columns(table):
        return {row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()}

    def response_for(title, rows, total, columns):
        if not rows:
            return jsonify({"status": "success", "reply": f"{title}\nNo matching records were found.", "source": "live_college_database", "returned_rows": 0})
        lines = [f"{title}", f"Total matching records: {total}", f"Showing: {len(rows)}", ""]
        for index, row in enumerate(rows, 1):
            parts = []
            for col in columns:
                value = row[col] if col in row.keys() else None
                if value not in (None, ""):
                    parts.append(f"{col.replace('_', ' ').title()}: {value}")
            lines.append(f"{index}. " + " | ".join(parts))
        if total > len(rows):
            lines.append(f"\nShowing the first {len(rows)} records. Ask for a specific department or year to narrow the list.")
        return jsonify({"status": "success", "reply": "\n".join(lines), "source": "live_college_database", "returned_rows": len(rows)})

    # Student listings, optionally filtered by department and/or year.
    if has_any("student", "students", "pupil", "pupils"):
        cols = table_columns("students")
        conditions, params = [], []
        # Programme filter: ME means the postgraduate ME programme, not all students.
        # Student IDs are generated as LIT-ME-<branch>-<year>-<number>.
        program_match = re.search(r"\b(be|me|mca|mba)\b", q)
        if program_match:
            program_code = program_match.group(1).upper()
            if "student_id" in cols:
                conditions.append("UPPER(student_id) LIKE ?")
                params.append(f"LIT-{program_code}-%")
            elif "department" in cols:
                conditions.append("UPPER(department) LIKE ?")
                params.append(f"{program_code} %")

        department_map = {
            "ec": ["%EC%", "%Electronics%"],
            "ece": ["%EC%", "%Electronics%"],
            "cse": ["%CSE%", "%Computer Science%"],
            "computer science": ["%Computer Science%", "%CSE%"],
            "mechanical": ["%Mechanical%", "%MECH%"],
            "mech": ["%Mechanical%", "%MECH%"],
            "civil": ["%Civil%"],
            "eee": ["%EEE%", "%Electrical%"],
        }
        matched_dept = next((key for key in sorted(department_map, key=len, reverse=True)
                             if re.search(rf"\b{re.escape(key)}\b", q)), None)
        if matched_dept and "department" in cols:
            choices = department_map[matched_dept]
            conditions.append("(" + " OR ".join(["LOWER(department) LIKE LOWER(?)"] * len(choices)) + ")")
            params.extend(choices)
        year_match = re.search(r"\b(first|1st|second|2nd|third|3rd|fourth|4th|[1-4])\s*[- ]?\s*(?:year|yr)\b|\byear\s*([1-4])\b", q)
        if year_match and "year" in cols:
            token = next((x for x in year_match.groups() if x), "")
            year = {"first":1, "1st":1, "second":2, "2nd":2, "third":3, "3rd":3, "fourth":4, "4th":4}.get(token, int(token) if token.isdigit() else None)
            if year:
                conditions.append("year = ?")
                params.append(year)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        selected = [c for c in ("student_id", "id", "name", "department", "year", "email") if c in cols]
        sql = f"SELECT {', '.join(selected)} FROM students{where} ORDER BY department, year, name LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        count = conn.execute(f"SELECT COUNT(*) FROM students{where}", params[:-1]).fetchone()[0]
        return response_for("Student Records", rows, count, selected)

    if has_any("attendance", "present", "absent"):
        sql = """SELECT a.id AS record_id, a.student_id,
                        COALESCE(s.name, 'Not available') AS student_name,
                        s.department, s.year, a.date, a.status
                 FROM attendance a LEFT JOIN students s ON s.id = a.student_id
                 ORDER BY a.date DESC, a.id DESC LIMIT ?"""
        rows = conn.execute(sql, (limit,)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM attendance").fetchone()[0]
        return response_for("Student Attendance Records", rows, total,
                            ["record_id", "student_id", "student_name", "department", "year", "date", "status"])

    if has_any("employee", "employees", "staff", "faculty", "hod", "professor", "teacher"):
        cols = table_columns("employees")
        selected = [c for c in ("id", "employee_code", "name", "designation", "department", "email") if c in cols]
        conditions, params = [], []

        # Apply department constraints when a department/programme is named.
        employee_department_map = {
            "computer science": ["%Computer Science%", "%CSE%"],
            "mechanical": ["%Mechanical%", "%MECH%"],
            "civil": ["%Civil%"],
            "cse": ["%CSE%", "%Computer Science%"],
            "mech": ["%Mechanical%", "%MECH%"],
            "ece": ["%EC%", "%Electronics%"],
            "ec": ["%EC%", "%Electronics%"],
            "eee": ["%EEE%", "%Electrical%"],
            "mca": ["%MCA%"],
            "mba": ["%MBA%"],
        }
        matched_dept = next(
            (key for key in sorted(employee_department_map, key=len, reverse=True)
             if re.search(rf"\b{re.escape(key)}\b", q)), None
        )
        if matched_dept and "department" in cols:
            choices = employee_department_map[matched_dept]
            conditions.append("(" + " OR ".join(["LOWER(department) LIKE LOWER(?)"] * len(choices)) + ")")
            params.extend(choices)

        if "designation" in cols:
            if has_any("hod", "head of department"):
                conditions.append("LOWER(designation) LIKE '%hod%'")
            elif has_any("assistant professor"):
                conditions.append("LOWER(designation) LIKE '%assistant professor%'")
            elif has_any("professor"):
                conditions.append("LOWER(designation) LIKE '%professor%'")
            elif has_any("principal"):
                conditions.append("LOWER(designation) LIKE '%principal%'")

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        rows = conn.execute(
            f"SELECT {', '.join(selected)} FROM employees{where} ORDER BY department, name LIMIT ?",
            (*params, limit)
        ).fetchall()
        total = conn.execute(f"SELECT COUNT(*) FROM employees{where}", params).fetchone()[0]
        return response_for("Employee Records", rows, total, selected)

    if has_any("mark", "marks", "score", "scores", "result", "results"):
        rows = conn.execute("""SELECT s.name, s.department, s.year, m.subject, m.marks
                               FROM marks m LEFT JOIN students s ON s.id=m.student_id
                               ORDER BY s.department, s.name, m.subject LIMIT ?""", (limit,)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM marks").fetchone()[0]
        return response_for("Student Marks Records", rows, total, ["name", "department", "year", "subject", "marks"])

    if has_any("fee", "fees", "payment", "payments", "pending balance"):
        rows = conn.execute("""SELECT s.name, s.department, s.year, f.total_fee, f.paid_fee, f.balance
                               FROM fees f LEFT JOIN students s ON s.id=f.student_id
                               ORDER BY f.balance DESC LIMIT ?""", (limit,)).fetchall()
        total = conn.execute("SELECT COUNT(*) FROM fees").fetchone()[0]
        return response_for("Student Fee Records", rows, total, ["name", "department", "year", "total_fee", "paid_fee", "balance"])

    return None


@app.route("/api/admin-insights", methods=["POST"])
def admin_insights_api():
    """Answer admin questions by translating them into read-only SQL over the live college DB."""
    if session.get("role") != "admin":
        return jsonify({"status": "error", "reply": "Administrator sign-in required."}), 401

    payload = request.get_json(silent=True) or {}
    question = str(payload.get("message") or "").strip()[:1200]
    if not question:
        return jsonify({"status": "error", "reply": "Please enter a question."}), 400

    conn = get_db_connection()
    try:
        fast_response = _admin_insights_fast_path(conn, question)
        if fast_response is not None:
            return fast_response
    except Exception:
        app.logger.exception("Admin Smart Insights direct database lookup failed")
        # Continue to the AI planner if a direct lookup cannot handle the request.

    allowed_tables = {"students", "employees", "parents", "attendance", "marks", "fees", "courses"}
    try:
        # Build the live schema dynamically. Never expose password/hash columns to the model.
        schema_lines = []
        for table in sorted(allowed_tables):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                continue
            cols = []
            for col in conn.execute(f'PRAGMA table_info("{table}")').fetchall():
                col_name = col["name"] if isinstance(col, sqlite3.Row) else col[1]
                if str(col_name).lower() not in {"password", "password_hash", "passwd", "token", "secret"}:
                    cols.append(str(col_name))
            schema_lines.append(f"{table}({', '.join(cols)})")
        schema = "\n".join(schema_lines)

        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            return jsonify({
                "status": "error",
                "reply": "AI query understanding is not configured. Add GROQ_API_KEY to backend/.env and restart the server. Your database records remain protected."
            }), 503

        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

        info_context = COLLEGE_FACTS + load_extra_college_info() + get_faculty_facts()
        sql_prompt = (
            "You are the Smart Insights assistant for Lillian Institute of Technology. Understand natural-language questions, follow-up questions, abbreviations, spelling variations, and requests phrased as counts, lists, explanations, comparisons, or summaries. "
            "Answer questions about the institute using the official context below when they are general/public institutional questions "
            "(departments, programmes, admission basics, contact, faculty/HOD directory, published information). "
            "For any question that needs private college records, counts, attendance, marks, fees, student/employee/parent/course details, filtering, comparisons, or summaries, "
            "generate a read-only SQLite query using the live schema. "
            "If an institutional question is answerable from the official context, return ONLY JSON: "
            "{\\\"mode\\\":\\\"info\\\",\\\"answer\\\":\\\"...\\\"}. "
            "Otherwise return ONLY JSON: {\\\"mode\\\":\\\"sql\\\",\\\"sql\\\":\\\"SELECT ...\\\"}. "
            "Use only actual columns and allowed tables; never query password/hash/token/secret columns. "
            "For student records select helpful fields and use flexible partial matching. "
            "Attendance, marks and fees join students via student_id when supported. "
            "For pending fees use balance > 0 if available; for attendance percentages calculate only if records support it. "
            "For lists limit to 200. SQL must be a single SELECT or WITH...SELECT. "
            "Department synonyms: mech=Mechanical, cse=Computer Science, civil=Civil, ece=Electronics/Communication, "
            "eee=Electrical/Electronics, mca=MCA, mba=MBA. Match case-insensitively with LIKE wildcards. "
            "Do not invent institutional information or database facts. If the question is unrelated to the institute or cannot be answered from the official context/database, politely say what information is available and ask a focused clarification when needed. Never return unrelated unfiltered records merely because a keyword matched. "
            "OFFICIAL INSTITUTE CONTEXT:\\n" + info_context + "\\n\\nLIVE DATABASE SCHEMA:\\n" + schema
        )
        plan = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": sql_prompt},
                {"role": "user", "content": question}
            ],
            max_tokens=500,
            temperature=0
        )
        raw_plan = (plan.choices[0].message.content or "").strip()
        raw_plan = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_plan, flags=re.I)
        match = re.search(r"\{.*\}", raw_plan, flags=re.S)
        if not match:
            raise ValueError("The AI did not return a valid database query.")
        plan_obj = json.loads(match.group(0))
        if str(plan_obj.get("mode", "")).lower() == "info":
            info_answer = str(plan_obj.get("answer") or "").strip()
            if not info_answer:
                raise ValueError("The AI returned an empty institutional answer.")
            return jsonify({"status": "success", "reply": info_answer, "source": "official_institute_context"})
        sql = str(plan_obj.get("sql") or "").strip().rstrip(";").strip()

        # Enforce a single read-only SELECT. SQLite's authorizer is an additional safety barrier.
        if not re.match(r"^(SELECT|WITH)\b", sql, flags=re.I):
            raise ValueError("Only read-only SELECT queries are permitted.")
        if ";" in sql or re.search(
            r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|ATTACH|DETACH|PRAGMA|VACUUM|"
            r"REINDEX|TRIGGER|VIEW|LOAD_EXTENSION)\b", sql, flags=re.I
        ):
            raise ValueError("The generated query was not read-only.")
        referenced = set(re.findall(r"\b(?:FROM|JOIN)\s+[`\"\[]?([A-Za-z_][A-Za-z0-9_]*)", sql, flags=re.I))
        if not referenced or not referenced.issubset(allowed_tables):
            raise ValueError("The query referenced a table outside the college database.")

        def authorize(action, arg1, arg2, dbname, source):
            if action == sqlite3.SQLITE_READ:
                return sqlite3.SQLITE_OK if arg1 in allowed_tables else sqlite3.SQLITE_DENY
            denied = {
                getattr(sqlite3, name) for name in (
                    "SQLITE_INSERT", "SQLITE_UPDATE", "SQLITE_DELETE", "SQLITE_CREATE_INDEX",
                    "SQLITE_CREATE_TABLE", "SQLITE_CREATE_TEMP_INDEX", "SQLITE_CREATE_TEMP_TABLE",
                    "SQLITE_CREATE_TEMP_TRIGGER", "SQLITE_CREATE_TEMP_VIEW", "SQLITE_CREATE_TRIGGER",
                    "SQLITE_CREATE_VIEW", "SQLITE_DROP_INDEX", "SQLITE_DROP_TABLE",
                    "SQLITE_DROP_TEMP_INDEX", "SQLITE_DROP_TEMP_TABLE", "SQLITE_DROP_TEMP_TRIGGER",
                    "SQLITE_DROP_TEMP_VIEW", "SQLITE_DROP_TRIGGER", "SQLITE_DROP_VIEW",
                    "SQLITE_ALTER_TABLE", "SQLITE_ATTACH", "SQLITE_DETACH", "SQLITE_PRAGMA"
                ) if hasattr(sqlite3, name)
            }
            return sqlite3.SQLITE_DENY if action in denied else sqlite3.SQLITE_OK

        conn.set_authorizer(authorize)
        cursor = conn.execute(sql)
        colnames = [d[0] for d in (cursor.description or [])]
        rows = cursor.fetchmany(201)
        if len(rows) > 200:
            rows = rows[:200]
        result_rows = [dict(zip(colnames, tuple(row))) for row in rows]
        conn.set_authorizer(None)

        if not result_rows:
            return jsonify({
                "status": "success",
                "reply": "No matching records were found in the database for this question. Try a different name, department, course, or year."
            })

        # Let the model explain ONLY the SQL result; it cannot access any other records.
        answer_prompt = (
            "You are Lillian Institute Admin Smart Insights. Answer the administrator's question "
            "in clear, professional English only, regardless of the language used in the question. "
            "Use ONLY the database query results supplied below. Do not guess, infer missing records, "
            "or claim information that is not present. Clearly state if a field is absent. "
            "For lists, show names and relevant identifiers/department/year. "
            "If there are many rows, summarize the total and show the returned rows. "
            "Never reveal passwords or authentication secrets. Keep the answer readable."
        )
        answer = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": answer_prompt},
                {"role": "user", "content": (
                    "Administrator question:\n" + question +
                    "\n\nDatabase query results (JSON):\n" +
                    json.dumps(result_rows, ensure_ascii=False, default=str)
                )}
            ],
            max_tokens=1800,
            temperature=0.2
        )
        reply = (answer.choices[0].message.content or "").strip()
        if not reply:
            reply = json.dumps(result_rows, ensure_ascii=False, default=str)
        return jsonify({
            "status": "success",
            "reply": reply,
            "source": "live_college_database",
            "returned_rows": len(result_rows)
        })
    except ImportError:
        return jsonify({
            "status": "error",
            "reply": "AI package missing. Run: py -m pip install openai"
        }), 503
    except Exception:
        app.logger.exception("Admin Smart Insights database query failed")
        return jsonify({
            "status": "error",
            "reply": "I could not safely run that question against the database. Try a simpler question such as 'list Mechanical students' or 'show pending fees'. The error is recorded in the Flask server log."
        }), 500
    finally:
        conn.close()


@app.route("/api/admin-create", methods=["POST"])
def admin_create_record():
    """Create student or employee records from the authenticated Admin Portal."""
    if session.get("role") != "admin":
        return jsonify({"status": "error", "message": "Administrator sign-in required."}), 401
    payload = request.get_json(silent=True) or {}
    record_type = str(payload.get("type") or "").strip().lower()
    name = str(payload.get("name") or "").strip()
    email = str(payload.get("email") or "").strip().lower()
    department = str(payload.get("department") or "").strip()
    if not name or not email or not department:
        return jsonify({"status": "error", "message": "Name, email and department are required."}), 400
    conn = get_db_connection()
    try:
        ensure_academic_schema(conn)
        if record_type == "student":
            student_id = str(payload.get("student_id") or "").strip()
            year = payload.get("year")
            if not student_id or not year:
                return jsonify({"status": "error", "message": "Register number and year are required."}), 400
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(students)").fetchall()]
            fields = ["name", "email", "password", "department", "year"]
            values = [name, email, generate_password_hash("Student@123"), department, int(year)]
            if "student_id" in cols:
                fields.append("student_id"); values.append(student_id)
            marks = ",".join("?" for _ in fields)
            cur = conn.execute(f"INSERT INTO students ({','.join(fields)}) VALUES ({marks})", values)
            conn.commit()
            return jsonify({"status": "success", "message": f"Student {name} added successfully. Default password: Student@123", "id": cur.lastrowid})
        if record_type == "employee":
            designation = str(payload.get("designation") or "").strip()
            if not designation:
                return jsonify({"status": "error", "message": "Designation is required."}), 400
            cur = conn.execute(
                "INSERT INTO employees (name,email,password,designation,department) VALUES (?,?,?,?,?)",
                (name, email, generate_password_hash("Faculty@123"), designation, department))
            conn.commit()
            return jsonify({"status": "success", "message": f"Employee {name} added successfully. Default password: Faculty@123", "id": cur.lastrowid})
        return jsonify({"status": "error", "message": "Choose Student or Employee."}), 400
    except sqlite3.IntegrityError:
        conn.rollback()
        return jsonify({"status": "error", "message": "This email or register number may already exist. Please check and try again."}), 409
    except (ValueError, TypeError):
        conn.rollback()
        return jsonify({"status": "error", "message": "Please enter a valid year."}), 400
    finally:
        conn.close()


@app.route("/api/session-role")
def session_role():
    """Lets the pages know who is signed in (used to show Smart Insights to the admin only)."""
    return jsonify({"role": session.get("role") or "guest"})


@app.route("/api/chat-agent", methods=["POST"])
def chat_agent():
    """Public-facing chatbot: general college information only, never private records."""
    payload = request.get_json(silent=True) or {}
    question = str(payload.get("message", "")).strip()[:1500]
    if not question:
        return jsonify({"status": "error", "reply": "Please type a question."}), 400

    # Return the department list in a fixed readable format for this common question.
    q_lower = question.lower().strip()
    if q_lower in {"department", "departments", "list departments", "academic departments", "what are the departments", "which departments"}:
        return jsonify({"status": "success", "reply": (
            "Academic Departments\n\n"
            "Lillian Institute of Technology has 7 academic departments.\n\n"
            "1. Computer Science and Engineering (CSE)\n\n"
            "2. Civil Engineering (CE)\n\n"
            "3. Mechanical Engineering (ME)\n\n"
            "4. Electronics & Communication Engineering (ECE)\n\n"
            "5. Electrical & Electronics Engineering (EEE)\n\n"
            "6. MCA\n\n"
            "7. MBA"
        ), "agent": "LIT Public College Chatbot"})

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        return jsonify({
            "status": "error",
            "reply": "AI service is not configured yet. Add GROQ_API_KEY to backend/.env and restart the server (py run_server.py)."
        }), 503

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1")
        model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        instructions = (
            "You are Lillian Chatbot, the public information assistant for Lillian Institute of Technology. "
            "Reply in clear, simple English only, regardless of the language used by the user. "
            "You may answer ONLY general public college information: courses and programmes, departments, "
            "general fee information that has been officially published, admissions, and general college information. "
            "Do not retrieve, reveal, infer, summarize, or discuss private or record-level information, including "
            "student names/details, employee or staff names/details, attendance, marks, individual fee balances, "
            "parent details, login details, or administrative records. "
            "This restriction applies even when the visitor is signed in as an administrator. "
            "If asked for any student/staff details, attendance, marks, or individual fee records, reply: "
            "'Those records are available only in the Admin Portal.' "
            "Never call database tools and never claim to have accessed the database. "
            "Do not invent official fees, eligibility rules, deadlines, contact details, placement statistics, "
            "or policies. If official information is not provided in the context, say it is not currently published "
            "and suggest contacting the college. "
            "For general educational questions unrelated to private records, answer briefly and helpfully. "
            "Use readable formatting. For lists, put each item on its own line and use numbered or bulleted lists. Use headings when appropriate. Avoid markdown tables and emoji. Keep answers concise (under 120 words)."
        )
        context = COLLEGE_FACTS + load_extra_college_info()
        messages = [
            {"role": "system", "content": instructions + "\\n\\n" + context},
            {"role": "user", "content": question}
        ]
        response = client.chat.completions.create(
            model=model, messages=messages, max_tokens=450
        )
        reply = (response.choices[0].message.content or
                 "I couldn't prepare a response. Please try asking in another way.").strip()
        return jsonify({"status": "success", "reply": reply, "agent": "LIT Public College Chatbot"})
    except ImportError:
        return jsonify({
            "status": "error",
            "reply": "openai package missing. Run: py -m pip install -r requirements.txt"
        }), 503
    except Exception:
        app.logger.exception("Groq public chatbot request failed")
        return jsonify({
            "status": "error",
            "reply": "AI service request failed. Check the API key, model access, internet connection, and server terminal."
        }), 502


# ---------------- LOGOUT ----------------

@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()

    return jsonify({
        "status": "success",
        "message": "Logged out successfully"
    })


# ---------------- DATABASE STATUS ----------------

@app.route("/api/database-status")
def database_status():

    conn = get_db_connection()

    rows = conn.execute("""
        SELECT name
        FROM sqlite_master
        WHERE type='table'
    """).fetchall()

    conn.close()

    tables = [
        row["name"] for row in rows
        if row["name"] != "sqlite_sequence"
    ]

    return jsonify({
        "status": "success",
        "database": "Connected",
        "tables": tables
    })


# ---------------- RUN FLASK APP ----------------

if __name__ == "__main__":
    app.run(debug=True)
