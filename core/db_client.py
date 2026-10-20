"""
PostgreSQL Database connection utility for JobHunterKit.
"""

import logging
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load env file from the JobHunterKit directory
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)

DB_URL = os.getenv("DB_URL")


def get_connection():
    """Establish and return a connection to the PostgreSQL database."""
    if not DB_URL:
        raise ValueError("DB_URL environment variable is missing or empty in .env")

    conn = psycopg2.connect(DB_URL)
    return conn
