import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging

logger = logging.getLogger(__name__)

# Get the database URL from environment variables
DB_URL = "postgresql://neondb_owner:npg_KOX91smlJnkW@ep-icy-heart-a8idixoq-pooler.eastus2.azure.neon.tech/neondb?sslmode=require"
if not DB_URL:
    raise ValueError("DATABASE_URL environment variable is not set.")

# Establishing a connection to Neon DB
def get_db_connection():
    return psycopg2.connect(DB_URL)
