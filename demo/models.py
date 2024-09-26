# models.py

from sqlalchemy import Column, Integer, String, Boolean, Text
from database import Base

class Voter(Base):
    __tablename__ = 'voters'
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True)  # Added email field
    is_verified = Column(Boolean, default=False)      # Added is_verified field
    has_voted = Column(Boolean, default=False)
    encrypted_id = Column(String)

class Vote(Base):
    __tablename__ = 'votes'
    id = Column(Integer, primary_key=True, index=True)
    encrypted_voter_id = Column(String)
    preferences = Column(Text)  # Store preferences as JSON string
