"""Datos iniciales: ajustes, plataformas, servicios, agentes y los primeros temas."""
from sqlalchemy.orm import Session

from .models import Agent, Platform, PlatformAccount, ServiceConnection, Setting, Topic

DEFAULT_SETTINGS = {
    "channel_name": "",
    "publish_mode": "approval",  # approval | automatic
    "shorts_per_week": "5",
    "longs_per_week": "1",
    "publish_time_local": "18:00",
    "timezone": "America/Ciudad_Juarez",
}

PLATFORMS = [
    ("youtube", "YouTube"),
    ("tiktok", "TikTok"),
    ("facebook", "Facebook"),
    ("instagram", "Instagram"),
]

SERVICES = [
    ("voice", "Clon de voz"),
    ("llm", "Modelo de IA"),
    ("stock_media", "Imágenes y clips con licencia libre"),
]

AGENTS = [
    ("researcher", "Investigador", "Busca temas y verifica cada dato en dos fuentes"),
    ("writer", "Guionista", "Escribe con el formato de gancho, prueba, giro y opinión"),
    ("voice", "Voz", "Narra con el clon de tu voz"),
    ("visuals", "Visuales", "Reúne imágenes y clips con licencia libre"),
    ("editor", "Editor", "Arma el video con subtítulos, en vertical y horizontal"),
    ("publisher", "Publicador", "Sube lo aprobado a cada plataforma a su hora"),
    ("analyst", "Analista", "Revisa retención y vistas, y ajusta los temas siguientes"),
]

FIRST_TOPICS = [
    "Una universidad más antigua que el Imperio azteca",
    "Cleopatra y el viaje a la Luna",
    "La miel que no se echa a perder",
    "El plátano es una baya y la fresa no",
    "Los pulpos tienen tres corazones",
    "En Venus un día dura más que un año",
    "Los tiburones son más antiguos que los árboles",
    "La Torre Eiffel crece en verano",
    "El primer bug fue un insecto de verdad",
    "La Ciudad de México se hunde",
]


def seed(db: Session) -> None:
    """Crea los datos base que falten. Se puede ejecutar muchas veces sin duplicar."""
    existing = {s.key for s in db.query(Setting).all()}
    first_run = "seeded" not in existing

    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(Setting(key=key, value=value))

    platform_codes = {p.code for p in db.query(Platform).all()}
    for code, name in PLATFORMS:
        if code not in platform_codes:
            platform = Platform(code=code, name=name)
            platform.accounts.append(PlatformAccount(status="pending"))
            db.add(platform)

    service_codes = {s.code for s in db.query(ServiceConnection).all()}
    for code, name in SERVICES:
        if code not in service_codes:
            db.add(ServiceConnection(code=code, name=name))

    agent_codes = {a.code for a in db.query(Agent).all()}
    for order, (code, name, description) in enumerate(AGENTS, start=1):
        if code not in agent_codes:
            db.add(Agent(code=code, name=name, description=description, run_order=order))

    if first_run:
        for title in FIRST_TOPICS:
            db.add(Topic(title=title, origin="manual"))
        db.add(Setting(key="seeded", value="1"))

    db.commit()
