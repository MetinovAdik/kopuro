# news_monitor/models.py
import enum
from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as DBEnum
from sqlalchemy.sql import func
from database import Base


class CommentSentiment(str, enum.Enum):
    POSITIVE = "ПОЗИТИВНЫЙ"
    NEGATIVE = "НЕГАТИВНЫЙ"
    NEUTRAL = "НЕЙТРАЛЬНЫЙ"
    FRUSTRATED = "РАЗОЧАРОВАННЫЙ"
    ANGRY = "ЗЛОЙ"
    EXCITED = "ВОСТОРЖЕННЫЙ"
    SAD = "ГРУСТНЫЙ"
    GRATEFUL = "БЛАГОДАРНЫЙ"
    CONFUSED = "НЕДОУМЕВАЮЩИЙ"
    SARCASTIC = "САРКАСТИЧНЫЙ"
    UNKNOWN = "НЕОПРЕДЕЛЕНО"


class YoutubeComment(Base):
    __tablename__ = "youtube_comments"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    youtube_username = Column(String, nullable=False, index=True)
    comment_text = Column(Text, nullable=False)
    opinion_text = Column(Text, nullable=True)
    topic = Column(String, nullable=True, index=True)
    youtube_comment_id = Column(String, nullable=False, unique=True, index=True)
    youtube_video_id = Column(String, nullable=True, index=True)
    youtube_channel_id = Column(String, nullable=True, index=True)
    youtube_channel_title = Column(String, nullable=True, index=True)
    comment_published_at = Column(DateTime(timezone=True), nullable=True)
    sentiment = Column(DBEnum(CommentSentiment), default=CommentSentiment.UNKNOWN, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<YoutubeComment id={self.id} channel='{self.youtube_channel_title}' video_id='{self.youtube_video_id}' comment_id='{self.youtube_comment_id}'>"