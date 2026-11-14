"""Agente investigador: propone temas y verifica cada dato en dos fuentes."""
from typing import Callable
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ..models import Fact, Source, Topic
from . import llm

SYSTEM = """Eres el investigador de un canal de videos cortos de curiosidades en español, para público general de México y Latinoamérica.

Tu trabajo es proponer temas sorprendentes y VERDADEROS, y comprobar cada dato con la búsqueda web.

Reglas:
- Usa la búsqueda web para comprobar cada afirmación en al menos dos fuentes independientes y confiables (enciclopedias, universidades, museos, organismos oficiales, medios reconocidos). No uses foros ni redes sociales.
- Si no encuentras dos fuentes que respalden un dato, no lo incluyas.
- Prefiere datos con fechas, cifras o nombres concretos. Evita mitos populares y datos disputados.
- Nada de chismes, rumores sobre personas, política partidista ni temas médicos delicados.
- Cada tema lleva de 2 a 3 afirmaciones: el dato principal y uno o dos datos que lo hagan más sorprendente.
- En "fuentes" copia las direcciones EXACTAS de las páginas que encontraste con la búsqueda. No inventes ni recortes enlaces.

Al terminar responde SOLO con un objeto JSON, sin texto antes ni después, con esta forma:
{"temas": [{"titulo": "...", "datos": [{"afirmacion": "...", "fuentes": ["https://...", "https://..."]}]}]}"""


def _normalize(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path.rstrip('/')}"


def _domain(url: str) -> str:
    return urlsplit(url.strip()).netloc.lower().removeprefix("www.")


def run(db: Session, log: Callable[[str], None], count: int = 5) -> None:
    count = max(1, min(10, int(count)))
    existing = [t.title for t in db.query(Topic).order_by(Topic.id.desc()).limit(300).all()]
    avoid = "\n".join(f"- {title}" for title in existing) or "(ninguno)"

    user = (
        f"Propón {count} temas nuevos de curiosidades.\n\n"
        f"No repitas ni te parezcas a estos temas que ya tenemos:\n{avoid}"
    )
    log(f"Modelo: {llm.model_name()}. Se pidieron {count} temas.")
    result = llm.complete(SYSTEM, user, max_tokens=8000, web_searches=count * 4)
    log(
        f"Búsquedas web: {result.searches}. Tokens: {result.input_tokens} de entrada, "
        f"{result.output_tokens} de salida."
    )

    data = llm.extract_json(result.text, "temas")
    if data is None or not isinstance(data.get("temas"), list):
        raise llm.LLMError("El investigador no devolvió una lista de temas con el formato esperado.")

    searched = {_normalize(u) for u in result.urls}
    known = {t.strip().lower() for t in existing}
    saved = 0
    for item in data["temas"]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("titulo") or "").strip()[:300]
        if not title or title.lower() in known:
            continue
        topic = Topic(title=title, origin="agent")
        for raw in item.get("datos") or []:
            if not isinstance(raw, dict):
                continue
            claim = str(raw.get("afirmacion") or "").strip()
            if not claim:
                continue
            fact = Fact(claim=claim)
            seen_domains = set()
            for url in raw.get("fuentes") or []:
                url = str(url).strip()
                if not url.lower().startswith(("http://", "https://")):
                    continue
                # Solo se aceptan enlaces que la búsqueda web devolvió de verdad.
                if _normalize(url) not in searched:
                    log(f"Fuente descartada (no apareció en la búsqueda): {url}")
                    continue
                if _domain(url) in seen_domains:
                    continue
                seen_domains.add(_domain(url))
                fact.sources.append(Source(url=url))
            # Verificado solo con dos fuentes de sitios distintos.
            fact.verified = len(seen_domains) >= 2
            topic.facts.append(fact)
        if not topic.facts:
            continue
        db.add(topic)
        known.add(title.lower())
        saved += 1
        verified = sum(1 for f in topic.facts if f.verified)
        log(f"Tema guardado: {title} ({verified} de {len(topic.facts)} datos verificados)")

    db.commit()
    if saved == 0:
        raise llm.LLMError("El investigador no produjo ningún tema nuevo utilizable.")
    log(f"Listo: {saved} temas nuevos en la lista de propuestos.")
