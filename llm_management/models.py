from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as DBEnum
from sqlalchemy.sql import func
from database import Base
import enum


class SubmissionSource(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    WEBFORM = "web_form"
    OTHER = "other"

class IssueStatus(str, enum.Enum):
    NEW = "new"
    ANALYZED = "analyzed"
    PROCESSING = "processing"
    RESOLVED = "resolved"
    CLOSED = "closed"
    ANALYSIS_FAILED = "analysis_failed"

class UserSubmissionType(str, enum.Enum):
    COMPLAINT = "жалоба"
    REQUEST = "просьба"


class ComplaintAnalysis(Base):
    __tablename__ = "complaint_analyses"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)


    original_complaint = Column(Text, nullable=False)
    submission_type_by_user = Column(DBEnum(UserSubmissionType), nullable=True, index=True)
    source = Column(DBEnum(SubmissionSource), nullable=False, index=True)
    source_user_id = Column(String, nullable=False, index=True)
    source_username = Column(String, nullable=True)
    user_first_name = Column(String, nullable=True)


    responsible_department = Column(String, index=True, nullable=True)
    complaint_type = Column(String, index=True, nullable=True)
    address = Column(String, nullable=True)
    applicant_data = Column(String, nullable=True)
    other_details = Column(Text, nullable=True)
    llm_processing_error = Column(Text, nullable=True)


    status = Column(DBEnum(IssueStatus), default=IssueStatus.NEW, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<ComplaintAnalysis id={self.id} source_user_id='{self.source_user_id}' source='{self.source.value}'>"