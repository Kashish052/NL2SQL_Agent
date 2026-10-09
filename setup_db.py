from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Any


DB_PATH = Path("data") / "enterprise.db"
SEED = 42


def _date_str(base: date, offset_days: int) -> str:
    return (base + timedelta(days=offset_days)).isoformat()


def _build_schema(cursor: sqlite3.Cursor) -> None:
    cursor.executescript(
        """
        PRAGMA foreign_keys = ON;

        DROP TABLE IF EXISTS employee_trainings;
        DROP TABLE IF EXISTS trainings;
        DROP TABLE IF EXISTS performance_reviews;
        DROP TABLE IF EXISTS project_assignments;
        DROP TABLE IF EXISTS salaries;
        DROP TABLE IF EXISTS projects;
        DROP TABLE IF EXISTS employees;
        DROP TABLE IF EXISTS departments;
        DROP TABLE IF EXISTS locations;

        CREATE TABLE locations (
            location_id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL,
            state TEXT NOT NULL,
            country TEXT NOT NULL,
            address TEXT NOT NULL UNIQUE,
            zip_code TEXT NOT NULL
        );

        CREATE TABLE departments (
            department_id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_name TEXT NOT NULL UNIQUE,
            location_id INTEGER NOT NULL,
            cost_center TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (location_id) REFERENCES locations (location_id)
        );

        CREATE TABLE employees (
            employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            manager_id INTEGER,
            first_name TEXT NOT NULL,
            last_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            job_title TEXT NOT NULL,
            hire_date TEXT NOT NULL,
            birth_date TEXT NOT NULL,
            employment_status TEXT NOT NULL,
            FOREIGN KEY (department_id) REFERENCES departments (department_id),
            FOREIGN KEY (manager_id) REFERENCES employees (employee_id)
        );

        CREATE TABLE salaries (
            salary_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL UNIQUE,
            base_salary REAL NOT NULL,
            bonus REAL NOT NULL,
            effective_date TEXT NOT NULL,
            pay_grade TEXT NOT NULL,
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        );

        CREATE TABLE projects (
            project_id INTEGER PRIMARY KEY AUTOINCREMENT,
            department_id INTEGER NOT NULL,
            project_name TEXT NOT NULL,
            budget REAL NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT,
            status TEXT NOT NULL,
            FOREIGN KEY (department_id) REFERENCES departments (department_id)
        );

        CREATE TABLE project_assignments (
            assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            allocation_pct REAL NOT NULL,
            assigned_on TEXT NOT NULL,
            released_on TEXT,
            FOREIGN KEY (project_id) REFERENCES projects (project_id),
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
        );

        CREATE TABLE performance_reviews (
            review_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            reviewer_id INTEGER NOT NULL,
            review_date TEXT NOT NULL,
            rating INTEGER NOT NULL,
            comments TEXT,
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
            FOREIGN KEY (reviewer_id) REFERENCES employees (employee_id)
        );

        CREATE TABLE trainings (
            training_id INTEGER PRIMARY KEY AUTOINCREMENT,
            training_name TEXT NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            duration_hours INTEGER NOT NULL
        );

        CREATE TABLE employee_trainings (
            completion_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            training_id INTEGER NOT NULL,
            completion_date TEXT NOT NULL,
            score REAL,
            FOREIGN KEY (employee_id) REFERENCES employees (employee_id),
            FOREIGN KEY (training_id) REFERENCES trainings (training_id)
        );
        """
    )


def _seed_locations(cursor: sqlite3.Cursor) -> list[int]:
    locations = [
        ("Bengaluru", "Karnataka", "India", "123 Tech Park", "560001"),
        ("Pune", "Maharashtra", "India", "456 Info Avenue", "411057"),
        ("Hyderabad", "Telangana", "India", "789 Cyber Road", "500081"),
        ("San Francisco", "California", "USA", "101 Innovation Way", "94105"),
    ]
    cursor.executemany(
        "INSERT INTO locations (city, state, country, address, zip_code) VALUES (?, ?, ?, ?, ?)",
        locations,
    )
    cursor.execute("SELECT location_id FROM locations ORDER BY location_id")
    return [row[0] for row in cursor.fetchall()]


def _seed_departments(cursor: sqlite3.Cursor, location_ids: list[int]) -> list[int]:
    departments = [
        ("Human Resources", "CC-100", "2023-01-05"),
        ("Finance", "CC-110", "2023-01-05"),
        ("Engineering", "CC-120", "2023-01-05"),
        ("Sales", "CC-130", "2023-01-05"),
        ("Marketing", "CC-140", "2023-01-05"),
        ("Operations", "CC-150", "2023-01-05"),
        ("Customer Success", "CC-160", "2023-01-05"),
        ("Product", "CC-170", "2023-01-05"),
    ]
    
    rows = [(d[0], random.choice(location_ids), d[1], d[2]) for d in departments]
    
    cursor.executemany(
        "INSERT INTO departments (department_name, location_id, cost_center, created_at) VALUES (?, ?, ?, ?)",
        rows,
    )
    cursor.execute("SELECT department_id FROM departments ORDER BY department_id")
    return [row[0] for row in cursor.fetchall()]


def _seed_employees(cursor: sqlite3.Cursor, department_ids: list[int]) -> list[int]:
    first_names = [
        "Aarav", "Diya", "Kabir", "Isha", "Rohan", "Meera", "Vihaan", "Anaya",
        "Arjun", "Saanvi", "Reyansh", "Pari", "Ishaan", "Khushi", "Aditya", "Naina",
    ]
    last_names = [
        "Sharma", "Verma", "Gupta", "Mehta", "Agarwal", "Singh", "Kapoor", "Malhotra",
        "Bansal", "Jain", "Khan", "Patel", "Reddy", "Nair", "Iyer", "Chopra",
    ]
    job_titles = [
        "Analyst", "Senior Analyst", "Software Engineer", "Product Manager", "Account Executive",
        "HR Specialist", "Finance Associate", "Operations Lead", "Support Engineer", "Marketing Manager",
        "Data Scientist", "Engineering Manager", "Director", "VP",
    ]
    statuses = ["Active", "Active", "Active", "Active", "Leave", "Probation"]
    hire_anchor = date(2019, 1, 1)
    birth_anchor = date(1985, 1, 1)

    rows: list[tuple[Any, ...]] = []
    for index in range(250):
        department_id = random.choice(department_ids)
        first_name = random.choice(first_names)
        last_name = random.choice(last_names)
        email = f"{first_name.lower()}.{last_name.lower()}.{index + 1}@example.com"
        job_title = random.choice(job_titles)
        hire_date = _date_str(hire_anchor, random.randint(0, 2400))
        birth_date = _date_str(birth_anchor, random.randint(0, 12000))
        employment_status = random.choice(statuses)
        rows.append(
            (
                department_id,
                None,  # manager_id placeholder
                first_name,
                last_name,
                email,
                job_title,
                hire_date,
                birth_date,
                employment_status,
            )
        )

    cursor.executemany(
        """
        INSERT INTO employees (
            department_id, manager_id, first_name, last_name, email, job_title,
            hire_date, birth_date, employment_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    cursor.execute("SELECT employee_id FROM employees ORDER BY employee_id")
    employee_ids = [row[0] for row in cursor.fetchall()]

    # Assign managers
    for employee_id in employee_ids:
        possible_managers = [m_id for m_id in employee_ids if m_id != employee_id]
        if possible_managers:
            manager_id = random.choice(possible_managers)
            cursor.execute("UPDATE employees SET manager_id = ? WHERE employee_id = ?", (manager_id, employee_id))

    return employee_ids


def _seed_salaries(cursor: sqlite3.Cursor, employee_ids: list[int]) -> None:
    rows: list[tuple[Any, ...]] = []
    pay_grades = ["G1", "G2", "G3", "G4", "G5"]
    effective_anchor = date(2024, 1, 1)

    for employee_id in employee_ids:
        base_salary = round(random.uniform(45000.0, 250000.0), 2)
        bonus = round(base_salary * random.uniform(0.05, 0.25), 2)
        rows.append(
            (
                employee_id,
                base_salary,
                bonus,
                _date_str(effective_anchor, random.randint(0, 300)),
                random.choice(pay_grades),
            )
        )

    cursor.executemany(
        """
        INSERT INTO salaries (employee_id, base_salary, bonus, effective_date, pay_grade)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


def _seed_projects(cursor: sqlite3.Cursor, department_ids: list[int]) -> list[int]:
    project_names = [
        "Atlas Migration", "North Star CRM", "Pulse Analytics", "Mercury Refresh", "Vertex Portal",
        "Nimbus Support", "Orion Launch", "Summit Automation", "Apex Dashboard", "Fusion Data Hub",
        "Crescent Enablement", "Halo Onboarding", "Quantum Revamp", "Eclipse Insights", "Aurora Tracker",
    ]
    statuses = ["Planning", "Active", "Active", "Active", "Completed", "On Hold"]
    start_anchor = date(2023, 1, 1)

    rows: list[tuple[Any, ...]] = []
    for index in range(40):
        department_id = random.choice(department_ids)
        start_date = _date_str(start_anchor, random.randint(0, 800))
        end_date = None if random.choice([True, False]) else _date_str(start_anchor, random.randint(900, 1400))
        rows.append(
            (
                department_id,
                f"{project_names[index % len(project_names)]} {index + 1}",
                round(random.uniform(50000.0, 1000000.0), 2),
                start_date,
                end_date,
                random.choice(statuses),
            )
        )

    cursor.executemany(
        """
        INSERT INTO projects (department_id, project_name, budget, start_date, end_date, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    cursor.execute("SELECT project_id FROM projects ORDER BY project_id")
    return [row[0] for row in cursor.fetchall()]


def _seed_project_assignments(
    cursor: sqlite3.Cursor,
    employee_ids: list[int],
    project_ids: list[int],
) -> None:
    roles = ["Owner", "Contributor", "Reviewer", "Lead", "Coordinator"]
    assigned_anchor = date(2023, 2, 1)

    rows: list[tuple[Any, ...]] = []
    for project_id in project_ids:
        assigned_employees = random.sample(employee_ids, k=random.randint(8, 20))
        for employee_id in assigned_employees:
            assigned_on = _date_str(assigned_anchor, random.randint(0, 700))
            released_on = None if random.choice([True, False, False]) else _date_str(assigned_anchor, random.randint(701, 1100))
            rows.append(
                (
                    project_id,
                    employee_id,
                    random.choice(roles),
                    round(random.uniform(20.0, 100.0), 1),
                    assigned_on,
                    released_on,
                )
            )

    cursor.executemany(
        """
        INSERT INTO project_assignments (
            project_id, employee_id, role, allocation_pct, assigned_on, released_on
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _seed_performance_reviews(cursor: sqlite3.Cursor, employee_ids: list[int]) -> None:
    rows: list[tuple[Any, ...]] = []
    review_anchor = date(2023, 6, 1)
    comments = [
        "Exceeds expectations in all areas.",
        "Meets expectations consistently.",
        "Needs improvement in communication.",
        "A strong team player with great potential.",
        "Struggles with deadlines but delivers high-quality work.",
    ]

    for employee_id in employee_ids:
        cursor.execute("SELECT manager_id FROM employees WHERE employee_id = ?", (employee_id,))
        result = cursor.fetchone()
        if result and result[0]:
            reviewer_id = result[0]
            num_reviews = random.randint(1, 3)
            for _ in range(num_reviews):
                rows.append(
                    (
                        employee_id,
                        reviewer_id,
                        _date_str(review_anchor, random.randint(0, 500)),
                        random.randint(2, 5),
                        random.choice(comments),
                    )
                )

    cursor.executemany(
        """
        INSERT INTO performance_reviews (employee_id, reviewer_id, review_date, rating, comments)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )


def _seed_trainings(cursor: sqlite3.Cursor) -> list[int]:
    trainings = [
        ("Advanced Python Programming", "Internal", 40),
        ("Cloud Architecture (AWS)", "External", 24),
        ("Effective Project Management", "Internal", 16),
        ("Cybersecurity Fundamentals", "External", 32),
        ("Data Science with Pandas", "Internal", 20),
    ]
    cursor.executemany(
        "INSERT INTO trainings (training_name, provider, duration_hours) VALUES (?, ?, ?)",
        trainings,
    )
    cursor.execute("SELECT training_id FROM trainings ORDER BY training_id")
    return [row[0] for row in cursor.fetchall()]


def _seed_employee_trainings(
    cursor: sqlite3.Cursor,
    employee_ids: list[int],
    training_ids: list[int],
) -> None:
    rows: list[tuple[Any, ...]] = []
    completion_anchor = date(2023, 4, 1)

    for employee_id in employee_ids:
        num_trainings = random.randint(0, 3)
        if num_trainings > 0:
            completed_trainings = random.sample(training_ids, k=num_trainings)
            for training_id in completed_trainings:
                rows.append(
                    (
                        employee_id,
                        training_id,
                        _date_str(completion_anchor, random.randint(0, 600)),
                        round(random.uniform(75.0, 99.0), 1),
                    )
                )

    cursor.executemany(
        """
        INSERT INTO employee_trainings (employee_id, training_id, completion_date, score)
        VALUES (?, ?, ?, ?)
        """,
        rows,
    )


def create_database(db_path: Path = DB_PATH) -> None:
    random.seed(SEED)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    connection = sqlite3.connect(db_path)
    try:
        cursor = connection.cursor()
        _build_schema(cursor)
        location_ids = _seed_locations(cursor)
        department_ids = _seed_departments(cursor, location_ids)
        employee_ids = _seed_employees(cursor, department_ids)
        _seed_salaries(cursor, employee_ids)
        project_ids = _seed_projects(cursor, department_ids)
        _seed_project_assignments(cursor, employee_ids, project_ids)
        _seed_performance_reviews(cursor, employee_ids)
        training_ids = _seed_trainings(cursor)
        _seed_employee_trainings(cursor, employee_ids, training_ids)
        connection.commit()
    finally:
        connection.close()

    print("Database created successfully:")
    print(f"- Path: {db_path}")
    print("- Tables: locations, departments, employees, salaries, projects, project_assignments, performance_reviews, trainings, employee_trainings")
    print("- Rows: 4 locations, 8 departments, 250 employees, 250 salaries, 40 projects, and many more relational rows.")


if __name__ == "__main__":
    create_database()
