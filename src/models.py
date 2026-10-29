from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from dataclasses import dataclass


class Base(DeclarativeBase):
    pass


class Collection(Base):
    __tablename__ = 'collections'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_path: Mapped[str] = mapped_column(String, unique=True)
    files: Mapped[list["File"]] = relationship(
        back_populates='collection'
    )


class File(Base):
    __tablename__ = 'files'
    __table_args__ = (
        UniqueConstraint('collection_id', 'relative_path'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    collection_id: Mapped[int] = mapped_column(Integer, ForeignKey('collections.id'), nullable=False)
    collection: Mapped["Collection"] = relationship(
        foreign_keys=[collection_id],
        back_populates='files'
    )
    functions: Mapped[list["Function"]] = relationship(
        back_populates='file'
    )
    relative_path: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)


class Function(Base):
    __tablename__ = 'functions'
    __table_args__ = (
        UniqueConstraint('file_id', 'start_line', 'end_line'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_id: Mapped[int] = mapped_column(Integer, ForeignKey('files.id'), nullable=False)
    file: Mapped[File] = relationship(
        foreign_keys=[file_id],
        back_populates='functions'
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    start_line: Mapped[int] = mapped_column(Integer, nullable=False)
    end_line: Mapped[int] = mapped_column(Integer, nullable=False)
    docstring: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON)
    embedding_model: Mapped[str | None] = mapped_column(String)


@dataclass(frozen=True)
class DirectoryDecision:
    skip: bool
    reason: str | None = None
    rule: str | None = None