"""The assistant's chats: one chat per conversation, kept per user and per client (the old chats list in the side
panel), with each message's model, tokens and estimated cost (tracked, no limit)."""

import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text

from backend.app.core.database import Base, create_table


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    engagement_id = Column(String(36), ForeignKey("client_engagements.id"), nullable=True, index=True)  # None: no client open
    title = Column(String(255), nullable=False, default="New chat")
    summary = Column(Text, nullable=True)                   # older messages summed up, for long chats
    summary_upto = Column(Integer, default=0)               # messages covered by the summary
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Numeric(12, 6), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, index=True)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    role = Column(String(20), nullable=False)               # user / assistant
    content = Column(Text, nullable=False, default="")
    steps = Column(Text, nullable=True)                     # JSON: what it looked at (tool names and labels)
    suggestions = Column(Text, nullable=True)               # JSON: follow-up questions, and option buttons
    model = Column(String(100), nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    cost_usd = Column(Numeric(12, 6), default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatFile(Base):
    """An Excel or PDF file the assistant made when asked; kept with the chat so it can be downloaded again."""
    __tablename__ = "chat_files"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id = Column(String(36), ForeignKey("chat_sessions.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    kind = Column(String(10), nullable=False)               # xlsx / pdf
    storage_path = Column(String(500), nullable=False)
    size_bytes = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class ChatUpload(Base):
    """A file the user attached to a question (a PDF, a photo or a screenshot), read when it was added: its text goes to
    the model with the question, its small preview shows on the tile. session_id is set when the question is sent."""
    __tablename__ = "chat_uploads"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(String(36), nullable=True, index=True)
    filename = Column(String(255), nullable=False)
    mime = Column(String(100), nullable=False)
    size_bytes = Column(Integer, default=0)
    storage_path = Column(String(500), nullable=False)
    thumb_path = Column(String(500), nullable=True)
    pages = Column(Integer, default=0)
    text = Column(Text, nullable=True)                      # what was read
    status = Column(String(12), nullable=False)             # READ / UNREADABLE
    note = Column(Text, nullable=True)                      # why it could not be read, in plain words
    read_by = Column(String(100), nullable=True)            # 'text' or the model that read the pictures
    created_at = Column(DateTime, default=datetime.utcnow)


class AssistantSpend(Base):
    """AI spend of the assistant outside the answers (those are on ChatMessage): a voice question written out, a
    picture or scan read when attached. For the cost meter and the test page's daily limit."""
    __tablename__ = "assistant_spend"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)               # voice / upload
    model = Column(String(100), nullable=True)
    tokens_in = Column(Integer, default=0)
    tokens_out = Column(Integer, default=0)
    seconds = Column(Numeric(10, 2), default=0)             # audio, for voice
    cost_usd = Column(Numeric(12, 6), default=0)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# New tables only: created on first use, leaving every existing table as it is
create_table(ChatSession.__table__)
create_table(ChatMessage.__table__)
create_table(ChatFile.__table__)
create_table(ChatUpload.__table__)
create_table(AssistantSpend.__table__)
