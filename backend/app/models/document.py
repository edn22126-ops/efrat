"""ORM models: Document, Tag, AuditLog."""
import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    ForeignKey,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.orm import relationship

from app.models.base import Base


class OcrStatus(enum.StrEnum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class Document(Base):
    __tablename__ = "documents"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(512), nullable=False)
    s3_key = Column(String(1024), nullable=False, unique=True)
    content_type = Column(String(256), nullable=True)
    sha256 = Column(String(64), nullable=True)
    ocr_status = Column(Enum(OcrStatus), default=OcrStatus.pending, nullable=False)
    ocr_text = Column(Text, nullable=True)
    category = Column(String(256), nullable=True)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tags = relationship("Tag", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(256), nullable=False)

    document = relationship("Document", back_populates="tags")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(128), nullable=False)
    detail = Column(Text, nullable=True)
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    document = relationship("Document", back_populates="audit_logs")
