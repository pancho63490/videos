"""Ejecuta un agente y deja constancia en el registro (tabla agent_runs)."""
import logging

from ..db import SessionLocal
from ..models import Agent, AgentRun, utcnow
from . import llm, researcher, writer

logger = logging.getLogger("agentes")

# Agentes que ya hacen trabajo real.
IMPLEMENTED = {"researcher": researcher.run, "writer": writer.run}


def start_run(agent_code: str, trigger: str = "manual") -> int:
    """Crea el registro de la ejecución y devuelve su id."""
    with SessionLocal() as db:
        agent = db.query(Agent).filter(Agent.code == agent_code).one()
        run = AgentRun(agent_id=agent.id, trigger=trigger, status="running")
        db.add(run)
        db.commit()
        return run.id


def execute(run_id: int, agent_code: str, **params) -> None:
    """Hace el trabajo del agente. Pensada para correr en segundo plano."""
    lines: list[str] = []
    error = None
    with SessionLocal() as db:
        try:
            if not llm.is_configured():
                raise llm.LLMError(
                    "Falta la clave del modelo de IA. Agrega la variable de entorno ANTHROPIC_API_KEY."
                )
            IMPLEMENTED[agent_code](db, lines.append, **params)
        except Exception as exc:  # se registra cualquier fallo en lugar de perderlo
            db.rollback()
            error = str(exc)[:2000] or exc.__class__.__name__
            if not isinstance(exc, llm.LLMError):
                logger.exception("Fallo inesperado del agente %s", agent_code)

    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        agent = db.query(Agent).filter(Agent.code == agent_code).one()
        if run is not None:
            run.status = "failed" if error else "ok"
            run.finished_at = utcnow()
            run.log = "\n".join(lines) or None
            run.error = error
        if error:
            agent.status = "error"
        elif agent.status == "error":
            agent.status = "active"
        db.commit()
