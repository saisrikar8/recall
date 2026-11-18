from datetime import datetime
import math

from sqlalchemy import (Boolean, CheckConstraint, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, String, Text,
                        UniqueConstraint, func, JSON, text, LargeBinary)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, validates



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
    extractions: Mapped[list["Extraction"]] = relationship(
        back_populates='file', cascade='all, delete-orphan', passive_deletes=True
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

class Extraction(Base):
    """One extraction attempt against identified source bytes, not a file copy."""
    __tablename__ = 'extractions'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'complete', 'failed')",
                        name='ck_extraction_status'),
        CheckConstraint("NOT is_active OR status = 'complete'",
                        name='ck_extraction_active_complete'),
        Index('uq_extraction_active_file', 'file_id', unique=True,
              sqlite_where=text('is_active = 1'), postgresql_where=text('is_active')),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    file_id: Mapped[int] = mapped_column(
        ForeignKey('files.id', ondelete='CASCADE'), nullable=False, index=True)
    file: Mapped[File] = relationship(back_populates='extractions')
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    extractor_name: Mapped[str] = mapped_column(String, nullable=False, default='default')
    extractor_version: Mapped[str] = mapped_column(String, nullable=False)
    chunker_version: Mapped[str | None] = mapped_column(String)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String, nullable=False, default='pending')
    # The serving pipeline will atomically switch this pointer after Gold is ready.
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    error: Mapped[str | None] = mapped_column(Text)
    entities: Mapped[list["Entity"]] = relationship(
        back_populates='extraction', cascade='all, delete-orphan', passive_deletes=True,
        foreign_keys='Entity.extraction_id', overlaps='parent,children')


def _location_checks(prefix):
    """One-based inclusive lines/pages; zero-based half-open character offsets."""
    return (
        CheckConstraint('(start_line IS NULL AND end_line IS NULL) OR '
                        '(start_line IS NOT NULL AND end_line IS NOT NULL AND '
                        'start_line >= 1 AND end_line >= start_line)', name=f'ck_{prefix}_lines'),
        CheckConstraint('(start_page IS NULL AND end_page IS NULL) OR '
                        '(start_page IS NOT NULL AND end_page IS NOT NULL AND '
                        'start_page >= 1 AND end_page >= start_page)', name=f'ck_{prefix}_pages'),
        CheckConstraint('(start_char IS NULL AND end_char IS NULL) OR '
                        '(start_char IS NOT NULL AND end_char IS NOT NULL AND '
                        'start_char >= 0 AND end_char >= start_char)', name=f'ck_{prefix}_chars'),
    )


class Entity(Base):
    """Structural item: file, class, method, section, or another supported kind."""
    __tablename__ = 'entities'
    __table_args__ = (
        UniqueConstraint('id', 'extraction_id', name='uq_entity_id_extraction'),
        UniqueConstraint('extraction_id', 'entity_key', name='uq_entity_extraction_key'),
        ForeignKeyConstraint(['parent_id', 'extraction_id'],
                             ['entities.id', 'entities.extraction_id'],
                             ondelete='CASCADE', name='fk_entity_parent_same_extraction'),
        CheckConstraint('parent_id IS NULL OR parent_id != id', name='ck_entity_not_own_parent'),
        CheckConstraint("length(kind) > 0", name='ck_entity_kind'),
        *_location_checks('entity'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    extraction_id: Mapped[int] = mapped_column(
        ForeignKey('extractions.id', ondelete='CASCADE'), nullable=False, index=True)
    extraction: Mapped[Extraction] = relationship(
        back_populates='entities', foreign_keys=[extraction_id], overlaps='parent,children')
    parent_id: Mapped[int | None] = mapped_column(Integer, index=True)
    parent: Mapped["Entity | None"] = relationship(
        remote_side=lambda: [Entity.id, Entity.extraction_id],
        foreign_keys=lambda: [Entity.parent_id, Entity.extraction_id],
        back_populates='children', overlaps='entities,extraction')
    children: Mapped[list["Entity"]] = relationship(
        back_populates='parent', cascade='all, delete-orphan', passive_deletes=True,
        foreign_keys=lambda: [Entity.parent_id, Entity.extraction_id],
        overlaps='entities,extraction')
    # Stable within an extraction; include source offsets to distinguish overloads.
    entity_key: Mapped[str] = mapped_column(String, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    qualified_name: Mapped[str | None] = mapped_column(String)
    language: Mapped[str | None] = mapped_column(String)
    docstring: Mapped[str] = mapped_column(Text, nullable=False, default='')
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    start_page: Mapped[int | None] = mapped_column(Integer)
    end_page: Mapped[int | None] = mapped_column(Integer)
    start_char: Mapped[int | None] = mapped_column(Integer)
    end_char: Mapped[int | None] = mapped_column(Integer)
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates='entity', cascade='all, delete-orphan', passive_deletes=True,
        order_by='Chunk.position')


class Chunk(Base):
    """Bounded retrieval text belonging to a structural entity (Silver)."""
    __tablename__ = 'chunks'
    __table_args__ = (
        UniqueConstraint('entity_id', 'position', name='uq_chunk_entity_position'),
        CheckConstraint('position >= 0', name='ck_chunk_position'),
        CheckConstraint("length(text) > 0", name='ck_chunk_text'),
        *_location_checks('chunk'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    entity_id: Mapped[int] = mapped_column(
        ForeignKey('entities.id', ondelete='CASCADE'), nullable=False, index=True)
    entity: Mapped[Entity] = relationship(back_populates='chunks')
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String, nullable=False, default='body')
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False)
    # Context can contain a path, class name, or heading; keep original text intact.
    context: Mapped[str] = mapped_column(Text, nullable=False, default='')
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    start_page: Mapped[int | None] = mapped_column(Integer)
    end_page: Mapped[int | None] = mapped_column(Integer)
    start_char: Mapped[int | None] = mapped_column(Integer)
    end_char: Mapped[int | None] = mapped_column(Integer)
    visual_embeddings: Mapped[list["VisualEmbedding"]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan", passive_deletes=True)
    embeddings: Mapped[list["Embedding"]] = relationship(
        back_populates='chunk', cascade='all, delete-orphan', passive_deletes=True)


class Embedding(Base):
    """Model-specific vector for a chunk (Gold); not itself a keyword index."""
    __tablename__ = 'embeddings'
    __table_args__ = (
        UniqueConstraint('chunk_id', 'model_key', name='uq_embedding_chunk_model'),
        CheckConstraint('dimensions > 0', name='ck_embedding_dimensions'),
        CheckConstraint('json_array_length(vector) = dimensions', name='ck_embedding_vector_length'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk: Mapped[Chunk] = relationship(back_populates='embeddings')
    # Fingerprint of model revision + preprocessing/config; generated by the pipeline.
    model_key: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_revision: Mapped[str | None] = mapped_column(String)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[list[float]] = mapped_column(JSON, nullable=False)
    # Hash of the exact embedding input, including context; separate from chunk hash.
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    @validates('vector')
    def validate_vector(self, key, value):
        if not isinstance(value, list) or not value:
            raise ValueError('Embedding vector must be a nonempty numeric list')
        if any(isinstance(number, bool) or not isinstance(number, (int, float))
               or not math.isfinite(number) for number in value):
            raise ValueError('Embedding vector must contain finite numbers')
        return value


class VisualEmbedding(Base):
    """ColBERT-style token vectors, packed as little-endian float16 (Gold)."""
    __tablename__ = 'visual_embeddings'
    __table_args__ = (
        UniqueConstraint('chunk_id', 'model_key', name='uq_visual_chunk_model'),
        CheckConstraint('dimensions > 0 AND token_count > 0', name='ck_visual_shape'),
        CheckConstraint('length(vectors) = token_count * dimensions * 2', name='ck_visual_bytes'),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    chunk_id: Mapped[int] = mapped_column(ForeignKey('chunks.id', ondelete='CASCADE'), nullable=False, index=True)
    chunk: Mapped[Chunk] = relationship(back_populates='visual_embeddings')
    model_key: Mapped[str] = mapped_column(String, nullable=False)
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_revision: Mapped[str] = mapped_column(String, nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    vectors: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    input_hash: Mapped[str] = mapped_column(String, nullable=False)
