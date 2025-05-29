from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as DBEnum, Float, Boolean
from sqlalchemy.sql import func
from database import Base
import enum
from typing import Optional




class SubmissionSource(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    WEBFORM = "web_form"
    OTHER = "other"


class UserSubmissionType(str, enum.Enum):
    COMPLAINT = "жалоба"
    REQUEST = "просьба"


class IssueStatus(str, enum.Enum):
    NEW = "new"
    PENDING_ANALYSIS = "pending_analysis"
    ANALYZED = "analyzed"
    ANALYSIS_FAILED = "analysis_failed"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    REJECTED = "rejected"
    CLOSED_UNRESOLVED = "closed_unresolved"
    PENDING_USER_FEEDBACK = "pending_user_feedback"


class SeverityLevel(str, enum.Enum):
    LOW = "низкий"
    MEDIUM = "средний"
    HIGH = "высокий"
    CRITICAL = "критический"


class ComplaintAnalysis(Base):
    __tablename__ = "complaint_analyses_v2"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)


    original_complaint_text = Column(Text, nullable=False)
    submission_type_by_user = Column(DBEnum(UserSubmissionType), nullable=True, index=True)
    source = Column(DBEnum(SubmissionSource), nullable=False, index=True)
    source_user_id = Column(String, nullable=False, index=True)
    source_username = Column(String, nullable=True)
    user_first_name = Column(String, nullable=True)

    responsible_department = Column(String, index=True, nullable=True)
    complaint_type = Column(String, index=True, nullable=True)

    complaint_category = Column(String, index=True, nullable=True)
    complaint_subcategory = Column(String, index=True, nullable=True)

    address_text = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    district = Column(String, nullable=True)

    severity_level = Column(DBEnum(SeverityLevel), nullable=True, index=True)
    applicant_data = Column(Text, nullable=True)
    other_details = Column(Text, nullable=True)

    llm_processing_error = Column(Text, nullable=True)


    status = Column(DBEnum(IssueStatus), default=IssueStatus.NEW, nullable=False, index=True)


    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolution_details = Column(Text, nullable=True)
    user_feedback_on_resolution = Column(Text, nullable=True)

    def __repr__(self):
        return f"<ComplaintAnalysis id={self.id} status='{self.status.value}'>"