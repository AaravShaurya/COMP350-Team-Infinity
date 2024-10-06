# database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
#from sqlalchemy.orm import declarative_base
from sqlalchemy.orm import sessionmaker
import sqlite3
import os

# Database URL
# Use an absolute path to ensure consistency across scripts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SQLALCHEMY_DATABASE_URL = f"sqlite:///{os.path.join(BASE_DIR, 'easemyvote.db')}"

# Create the SQLAlchemy engine with increased timeout and WAL mode
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={
        "check_same_thread": False,  
        "timeout": 30,             
    },
    pool_pre_ping=True,           
)

# Create a configured "SessionLocal" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Create a base class for declarative class definitions
Base = declarative_base()

# Enable WAL mode
with engine.connect() as connection:
    connection.execute("PRAGMA journal_mode=WAL;")
    connection.execute("PRAGMA synchronous=NORMAL;")
