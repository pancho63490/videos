"""Modelos de la base de datos (SQLAlchemy 2.0).

Las fechas se guardan en UTC, sin zona horaria. El panel las convierte a la
zona horaria configurada en Ajustes al mostrarlas.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Platform(Base):
    __tablename__ = "platforms"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))

    accounts: Mapped[list["PlatformAccount"]] = relationship(back_populates="platform")


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (UniqueConstraint("platform_id", "handle"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    platform_id: Mapped[int] = mapped_column(ForeignKey("platforms.id"))
    handle: Mapped[Optional[str]] = mapped_column(String(128))
    # pending | connected | expired | error
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # Nombre de la variable de entorno que guarda el token. Nunca el token.
    credential_env: Mapped[Optional[str]] = mapped_column(String(64))
    connected_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    platform: Mapped[Platform] = relationship(back_populates="accounts")


class ServiceConnection(Base):
    __tablename__ = "service_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    # pending | connected | error
    status: Mapped[str] = mapped_column(String(16), default="pending")
    credential_env: Mapped[Optional[str]] = mapped_column(String(64))
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    last_error: Mapped[Optional[str]] = mapped_column(Text)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    run_order: Mapped[int] = mapped_column(Integer)
    # active | paused | error
    status: Mapped[str] = mapped_column(String(16), default="paused")
    config_json: Mapped[str] = mapped_column(Text, default="{}")

    runs: Mapped[list["AgentRun"]] = relationship(
        back_populates="agent", order_by="AgentRun.started_at.desc()"
    )


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    video_id: Mapped[Optional[int]] = mapped_column(ForeignKey("videos.id", ondelete="SET NULL"))
    # schedule | manual
    trigger: Mapped[str] = mapped_column(String(16), default="manual")
    # running | ok | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    cost_usd: Mapped[Optional[float]] = mapped_column(Float)
    log: Mapped[Optional[str]] = mapped_column(Text)
    error: Mapped[Optional[str]] = mapped_column(Text)

    agent: Mapped[Agent] = relationship(back_populates="runs")


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    # agent | manual
    origin: Mapped[str] = mapped_column(String(16), default="manual")
    # proposed | discarded | used
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime)

    facts: Mapped[list["Fact"]] = relationship(
        back_populates="topic", cascade="all, delete-orphan", order_by="Fact.id"
    )
    videos: Mapped[list["Video"]] = relationship(back_populates="topic")

    @property
    def total_facts(self) -> int:
        return len(self.facts)

    @property
    def unverified_facts(self) -> int:
        return sum(1 for f in self.facts if not f.verified)

    @property
    def is_verified(self) -> bool:
        return self.total_facts > 0 and self.unverified_facts == 0


class Fact(Base):
    __tablename__ = "facts"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id", ondelete="CASCADE"), index=True)
    claim: Mapped[str] = mapped_column(Text)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)

    topic: Mapped[Topic] = relationship(back_populates="facts")
    sources: Mapped[list["Source"]] = relationship(
        back_populates="fact", cascade="all, delete-orphan", order_by="Source.id"
    )


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    fact_id: Mapped[int] = mapped_column(ForeignKey("facts.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(String(300))
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    fact: Mapped[Fact] = relationship(back_populates="sources")


class OpinionBank(Base):
    __tablename__ = "opinion_bank"

    id: Mapped[int] = mapped_column(primary_key=True)
    text: Mapped[str] = mapped_column(Text)
    tag: Mapped[Optional[str]] = mapped_column(String(64))
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    topic_id: Mapped[Optional[int]] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(300))
    # short | long
    format: Mapped[str] = mapped_column(String(8), default="short")
    # in_production | pending_review | approved | rejected | scheduled | published | failed
    status: Mapped[str] = mapped_column(String(24), default="in_production", index=True)
    duration_s: Mapped[Optional[int]] = mapped_column(Integer)
    scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, index=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    topic: Mapped[Optional[Topic]] = relationship(back_populates="videos")
    scripts: Mapped[list["Script"]] = relationship(
        back_populates="video", cascade="all, delete-orphan", order_by="Script.version.desc()"
    )
    assets: Mapped[list["Asset"]] = relationship(back_populates="video", cascade="all, delete-orphan")
    publications: Mapped[list["Publication"]] = relationship(
        back_populates="video", cascade="all, delete-orphan"
    )

    @property
    def current_script(self) -> Optional["Script"]:
        return self.scripts[0] if self.scripts else None

    @property
    def is_verified(self) -> bool:
        return bool(self.topic and self.topic.is_verified)

    @property
    def unverified_facts(self) -> int:
        return self.topic.unverified_facts if self.topic else 0

    @property
    def total_facts(self) -> int:
        return self.topic.total_facts if self.topic else 0


class Script(Base):
    __tablename__ = "scripts"
    __table_args__ = (UniqueConstraint("video_id", "version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    hook: Mapped[str] = mapped_column(Text, default="")
    proof: Mapped[str] = mapped_column(Text, default="")
    twist: Mapped[str] = mapped_column(Text, default="")
    opinion: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    video: Mapped[Video] = relationship(back_populates="scripts")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    # voice | image | clip | music | subtitles | render_vertical | render_horizontal | thumbnail
    kind: Mapped[str] = mapped_column(String(24))
    path: Mapped[str] = mapped_column(Text)
    license: Mapped[Optional[str]] = mapped_column(String(128))
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    video: Mapped[Video] = relationship(back_populates="assets")


class Publication(Base):
    __tablename__ = "publications"
    __table_args__ = (UniqueConstraint("video_id", "platform_account_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    video_id: Mapped[int] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    platform_account_id: Mapped[int] = mapped_column(ForeignKey("platform_accounts.id"))
    # queued | uploading | published | failed | removed
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    external_id: Mapped[Optional[str]] = mapped_column(String(128))
    url: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    video: Mapped[Video] = relationship(back_populates="publications")
    metrics: Mapped[list["Metric"]] = relationship(back_populates="publication", cascade="all, delete-orphan")


class Metric(Base):
    __tablename__ = "metrics"

    id: Mapped[int] = mapped_column(primary_key=True)
    publication_id: Mapped[int] = mapped_column(ForeignKey("publications.id", ondelete="CASCADE"), index=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    views: Mapped[int] = mapped_column(Integer, default=0)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    comments: Mapped[int] = mapped_column(Integer, default=0)
    shares: Mapped[int] = mapped_column(Integer, default=0)
    avg_watch_s: Mapped[Optional[float]] = mapped_column(Float)
    retention_pct: Mapped[Optional[float]] = mapped_column(Float)
    revenue_usd: Mapped[Optional[float]] = mapped_column(Float)

    publication: Mapped[Publication] = relationship(back_populates="metrics")
