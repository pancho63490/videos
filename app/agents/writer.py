"""Agente guionista: escribe el guion con gancho, prueba, giro y opinión."""
from typing import Callable, Optional

from sqlalchemy.orm import Session

from ..models import OpinionBank, Script, Setting, Video, utcnow
from . import llm

SYSTEM = """Eres el guionista de un canal de videos de curiosidades en español de México. El narrador habla en primera persona, con tono cercano y claro, sin exagerar.

Escribes guiones con cuatro partes:
1. gancho: una sola frase que suene imposible y dé ganas de seguir viendo.
2. prueba: el dato principal con sus fechas o cifras.
3. giro: un segundo dato que lo hace más sorprendente.
4. opinion: lo que piensa el narrador, y al final una pregunta para los comentarios.

Reglas:
- Usa ÚNICAMENTE los datos verificados que se te entregan. No agregues cifras, fechas ni hechos que no estén en la lista.
- Frases cortas, pensadas para decirse en voz alta. Sin emojis, sin etiquetas, sin indicaciones de cámara.
- No prometas nada falso en el gancho: debe ser cierto según los datos.
- En la opinión, si se te dan frases del narrador, apóyate en su estilo y sus ideas. No inventes anécdotas personales.

Responde SOLO con un objeto JSON, sin texto antes ni después:
{"gancho": "...", "prueba": "...", "giro": "...", "opinion": "..."}"""

LENGTH = {
    "short": "Video corto de 60 a 75 segundos: entre 150 y 190 palabras en total.",
    "long": "Video largo de 8 a 10 minutos: entre 1,100 y 1,400 palabras en total; la prueba y el giro deben desarrollarse con detalle.",
}


def _write_one(db: Session, video: Video, opinions: list, publish_mode: str, log: Callable[[str], None]) -> bool:
    topic = video.topic
    facts = [f for f in topic.facts if f.verified] if topic else []
    if not facts:
        log(f"Omitido: «{video.title}» no tiene datos verificados. Agrega datos con dos fuentes.")
        return False

    facts_text = "\n".join(f"- {f.claim}" for f in facts)
    opinions_text = "\n".join(f"- {o.text}" for o in opinions) or "(el narrador aún no ha dado frases)"
    user = (
        f"Tema: {video.title}\n\n"
        f"{LENGTH.get(video.format, LENGTH['short'])}\n\n"
        f"Datos verificados (los únicos que puedes usar):\n{facts_text}\n\n"
        f"Frases y posturas del narrador:\n{opinions_text}"
    )
    result = llm.complete(SYSTEM, user, max_tokens=4096)
    data = llm.extract_json(result.text, "gancho")
    parts = [str((data or {}).get(k) or "").strip() for k in ("gancho", "prueba", "giro", "opinion")]
    if data is None or not all(parts):
        log(f"Error: el guion de «{video.title}» no llegó con las cuatro partes.")
        return False

    current = video.current_script
    if current is not None and not any([current.hook, current.proof, current.twist, current.opinion]):
        script = current  # el guion vacío se llena en su lugar
    else:
        script = Script(version=(current.version + 1) if current else 1)
        video.scripts.append(script)
    script.hook, script.proof, script.twist, script.opinion = parts
    script.created_at = utcnow()

    for opinion in opinions:
        opinion.used_count += 1

    if video.status in ("in_production", "rejected"):
        if publish_mode == "automatic":
            video.status = "scheduled" if video.scheduled_at else "approved"
            video.reviewed_at = utcnow()
        else:
            video.status = "pending_review"
    db.commit()
    words = sum(len(p.split()) for p in parts)
    log(f"Guion escrito: «{video.title}» ({words} palabras, versión {script.version}).")
    return True


def run(db: Session, log: Callable[[str], None], video_id: Optional[int] = None, limit: int = 5) -> None:
    setting = db.get(Setting, "publish_mode")
    publish_mode = setting.value if setting else "approval"
    opinions = db.query(OpinionBank).order_by(OpinionBank.used_count, OpinionBank.id).limit(8).all()

    if video_id is not None:
        video = db.get(Video, video_id)
        if video is None:
            raise llm.LLMError("El video ya no existe.")
        videos = [video]
    else:
        # Videos en producción cuyo guion sigue vacío.
        candidates = db.query(Video).filter(Video.status == "in_production").order_by(Video.id).all()
        videos = []
        for video in candidates:
            script = video.current_script
            if script is None or not any([script.hook, script.proof, script.twist, script.opinion]):
                videos.append(video)
        videos = videos[: max(1, min(10, int(limit)))]

    if not videos:
        log("No hay videos en producción con el guion vacío.")
        return

    log(f"Modelo: {llm.model_name()}. Videos por escribir: {len(videos)}.")
    written = sum(1 for video in videos if _write_one(db, video, opinions, publish_mode, log))
    if written == 0:
        raise llm.LLMError("No se pudo escribir ningún guion. Revisa el detalle del registro.")
    log(f"Listo: {written} de {len(videos)} guiones escritos.")
