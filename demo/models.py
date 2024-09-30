# models.py
# models.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from database import Base  # Import Base from database.py

class Voter(Base):
    __tablename__ = 'voters'
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)
    is_verified = Column(Boolean, default=False)
    has_voted = Column(Boolean, default=False)
    encrypted_id = Column(String)
    voted_at = Column(DateTime)  # Field to track when the voter last voted

class Candidate(Base):
    __tablename__ = 'candidates'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    position = Column(String, nullable=False)

class Vote(Base):
    __tablename__ = 'votes'
    id = Column(Integer, primary_key=True, index=True)
    encrypted_voter_id = Column(String)
    preferences = Column(String)  # JSON string of preferences
