# kopuro_bot/models.py
from sqlalchemy import Column, Integer, String, DateTime, Enum as SAEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
import enum

Base = declarative_base()

class SubmissionType(enum.Enum):
    COMPLAINT = "жалоба"
    REQUEST = "просьба"

class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    submission_type = Column(SAEnum(SubmissionType), nullable=False)
    text = Column(String, nullable=False)
    status = Column(String, default="new", nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Submission(id={self.id}, user_id='{self.user_id}', type='{self.submission_type.value}', text='{self.text[:30]}...')>"