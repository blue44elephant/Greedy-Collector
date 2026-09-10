#!/usr/bin/env python
"""Verify standalone database schema."""

import sqlite3

conn = sqlite3.connect('data/greedy_collector.db')
conn.execute('PRAGMA foreign_keys=ON')

# Get tables
cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [row[0] for row in cursor.fetchall()]
print(f"✓ Database has {len(tables)} tables")
print("Tables:", ', '.join(tables))

# Check foreign keys
fk_violations = conn.execute('PRAGMA foreign_key_check').fetchall()
print(f"✓ Foreign key violations: {len(fk_violations)}")

# Check alembic version
try:
    cursor = conn.execute("SELECT version_num FROM alembic_version")
    version = cursor.fetchone()
    if version:
        print(f"✓ Alembic revision: {version[0]}")
except:
    print("✗ No alembic_version table found")

conn.close()
