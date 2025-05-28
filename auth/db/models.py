from sqlalchemy import Column, Integer, String, Boolean, Enum as SAEnum
from auth.db.database import Base
from auth.schemas.user_schemas import UserRole

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    full_name = Column(String, index=True, nullable=True)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=False) # Default to inactive until confirmed
    is_confirmed_by_admin = Column(Boolean, default=False)
    role = Column(SAEnum(UserRole, name="user_role_enum_type"), nullable=False, default=UserRole.WORKER)