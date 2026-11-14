"""Panel de administración del canal de curiosidades (FastAPI)."""
import os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload
from starlette.middleware.sessions import SessionMiddleware

from .agents import llm, runner
from .db import Base, SessionLocal, engine, get_db
from .models import (
    Agent,
    AgentRun,
    Fact,
    OpinionBank,
    PlatformAccount,
    Script,
    ServiceConnection,
    Setting,
    Source,
    Topic,
    Video,
    utcnow,
)
from .seed import DEFAULT_SETTINGS, seed

BASE_DIR = Path(__file__).resolve().parent

VIDEO_STATUS = {
    "in_production": ("En producción", "gris"),
    "pending_review": ("Por aprobar", "ambar"),
    "approved": ("Aprobado", "verde"),
    "scheduled": ("Programado", "verde"),
    "published": ("Publicado", "verde"),
    "rejected": ("Rechazado", "rojo"),
    "failed": ("Con error", "rojo"),
}
AGENT_STATUS = {
    "active": ("Activo", "verde"),
    "paused": ("Pausado", "gris"),
    "error": ("Con error", "rojo"),
}
CONNECTION_STATUS = {
    "pending": ("Pendiente de conectar", "ambar"),
    "connected": ("Conectado", "verde"),
    "expired": ("Sesión vencida", "ambar"),
    "error": ("Con error", "rojo"),
}
RUN_STATUS = {
    "running": "en curso",
    "ok": "correcta",
    "failed": "con error",
    "cancelled": "cancelada",
}
DAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
MONTH_NAMES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="Panel del canal de curiosidades", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY") or secrets.token_urlsafe(32),
    session_cookie="panel_sesion",
    same_site="lax",
    https_only=bool(os.getenv("RENDER")),
    max_age=60 * 60 * 24 * 14,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------
def get_settings(db: Session) -> dict:
    values = dict(DEFAULT_SETTINGS)
    values.update({s.key: s.value for s in db.query(Setting).all()})
    return values


def get_tz(settings: dict) -> ZoneInfo:
    try:
        return ZoneInfo(settings.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_local(dt: Optional[datetime], tz: ZoneInfo) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).astimezone(tz)


def to_utc(local_naive: datetime, tz: ZoneInfo) -> datetime:
    return local_naive.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)


def fmt_datetime(dt: Optional[datetime], tz: ZoneInfo) -> str:
    local = to_local(dt, tz)
    if local is None:
        return "Sin fecha"
    return f"{DAY_NAMES[local.weekday()]} {local.day} {MONTH_NAMES[local.month - 1]}, {local:%H:%M}"


def fmt_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "Sin duración"
    return f"{seconds // 60}:{seconds % 60:02d}"


def flash(request: Request, message: str) -> None:
    request.session["flash"] = message


def redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=303)


def render(request: Request, db: Session, template: str, **context) -> HTMLResponse:
    settings = get_settings(db)
    tz = get_tz(settings)
    pending = db.query(func.count(Video.id)).filter(Video.status == "pending_review").scalar() or 0
    context.update(
        settings=settings,
        channel_name=settings.get("channel_name") or "Canal de curiosidades",
        pending_count=pending,
        flash=request.session.pop("flash", None),
        path=request.url.path,
        video_status=VIDEO_STATUS,
        agent_status=AGENT_STATUS,
        connection_status=CONNECTION_STATUS,
        fmt_datetime=lambda dt: fmt_datetime(dt, tz),
        fmt_duration=fmt_duration,
    )
    return templates.TemplateResponse(request, template, context)


def get_video(db: Session, video_id: int) -> Video:
    video = db.get(Video, video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video no encontrado")
    return video


def get_topic(db: Session, topic_id: int) -> Topic:
    topic = db.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Tema no encontrado")
    return topic


def approve(video: Video) -> None:
    video.status = "scheduled" if video.scheduled_at else "approved"
    video.reviewed_at = utcnow()


# --------------------------------------------------------------------------
# Inicio de sesión
# --------------------------------------------------------------------------
class NotAuthenticated(Exception):
    pass


def require_login(request: Request) -> None:
    if not request.session.get("user"):
        raise NotAuthenticated()


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request: Request, _: NotAuthenticated):
    return redirect("/login")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get("user"):
        return redirect("/cola")
    configured = bool(os.getenv("ADMIN_EMAIL") and os.getenv("ADMIN_PASSWORD"))
    return templates.TemplateResponse(request, "login.html", {"error": None, "configured": configured})


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(""), password: str = Form("")):
    admin_email = os.getenv("ADMIN_EMAIL", "")
    admin_password = os.getenv("ADMIN_PASSWORD", "")
    configured = bool(admin_email and admin_password)
    ok = (
        configured
        and secrets.compare_digest(email.strip().lower().encode(), admin_email.strip().lower().encode())
        and secrets.compare_digest(password.encode(), admin_password.encode())
    )
    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Correo o contraseña incorrectos.", "configured": configured},
            status_code=401,
        )
    request.session["user"] = admin_email
    return redirect("/cola")


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return redirect("/login")


panel = APIRouter(dependencies=[Depends(require_login)])


@panel.get("/")
def home():
    return redirect("/cola")


# --------------------------------------------------------------------------
# Cola de aprobación
# --------------------------------------------------------------------------
@panel.get("/cola", response_class=HTMLResponse)
def queue(request: Request, db: Session = Depends(get_db)):
    videos = (
        db.query(Video)
        .options(selectinload(Video.topic).selectinload(Topic.facts))
        .filter(Video.status == "pending_review")
        .order_by(Video.scheduled_at.is_(None), Video.scheduled_at, Video.id)
        .all()
    )
    verified = sum(1 for v in videos if v.is_verified)
    return render(request, db, "cola.html", videos=videos, verified_count=verified)


@panel.post("/videos/{video_id}/aprobar")
def approve_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    approve(video)
    db.commit()
    flash(request, f"Aprobado: {video.title}")
    return redirect("/cola")


@panel.post("/videos/{video_id}/rechazar")
def reject_video(video_id: int, request: Request, nota: str = Form(""), db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    video.status = "rejected"
    video.reviewed_at = utcnow()
    video.review_note = nota.strip() or None
    db.commit()
    flash(request, f"Rechazado: {video.title}")
    return redirect("/cola")


@panel.post("/cola/aprobar-verificados")
def approve_verified(request: Request, db: Session = Depends(get_db)):
    videos = (
        db.query(Video)
        .options(selectinload(Video.topic).selectinload(Topic.facts))
        .filter(Video.status == "pending_review")
        .all()
    )
    count = 0
    for video in videos:
        if video.is_verified:
            approve(video)
            count += 1
    db.commit()
    flash(request, f"Se aprobaron {count} videos verificados.")
    return redirect("/cola")


# --------------------------------------------------------------------------
# Calendario
# --------------------------------------------------------------------------
@panel.get("/calendario", response_class=HTMLResponse)
def calendar(request: Request, semana: int = 0, db: Session = Depends(get_db)):
    settings = get_settings(db)
    tz = get_tz(settings)
    semana = max(-520, min(520, semana))
    today = datetime.now(tz).date()
    monday = today - timedelta(days=today.weekday()) + timedelta(weeks=semana)
    start_utc = to_utc(datetime.combine(monday, time.min), tz)
    end_utc = to_utc(datetime.combine(monday + timedelta(days=7), time.min), tz)

    videos = (
        db.query(Video)
        .filter(Video.scheduled_at >= start_utc, Video.scheduled_at < end_utc)
        .order_by(Video.scheduled_at)
        .all()
    )
    days = []
    for offset in range(7):
        date = monday + timedelta(days=offset)
        items = []
        for video in videos:
            local = to_local(video.scheduled_at, tz)
            if local.date() == date:
                items.append({"video": video, "hora": f"{local:%H:%M}"})
        days.append({"label": f"{DAY_NAMES[offset]} {date.day}", "items": items, "is_today": date == today})

    sunday = monday + timedelta(days=6)
    title = f"Semana del {monday.day} de {MONTH_NAMES[monday.month - 1]} al {sunday.day} de {MONTH_NAMES[sunday.month - 1]}"
    shorts = sum(1 for v in videos if v.format == "short")
    longs = sum(1 for v in videos if v.format == "long")
    return render(
        request, db, "calendario.html", days=days, title=title, semana=semana, shorts=shorts, longs=longs
    )


# --------------------------------------------------------------------------
# Temas
# --------------------------------------------------------------------------
@panel.get("/temas", response_class=HTMLResponse)
def topics(request: Request, estado: str = "proposed", db: Session = Depends(get_db)):
    if estado not in ("proposed", "used", "discarded"):
        estado = "proposed"
    items = (
        db.query(Topic)
        .options(selectinload(Topic.facts).selectinload(Fact.sources))
        .filter(Topic.status == estado)
        .order_by(Topic.created_at.desc(), Topic.id.desc())
        .all()
    )
    return render(request, db, "temas.html", topics=items, estado=estado)


@panel.post("/temas")
def add_topic(request: Request, titulo: str = Form(""), db: Session = Depends(get_db)):
    title = titulo.strip()
    if not title:
        flash(request, "Escribe un tema antes de agregarlo.")
    else:
        db.add(Topic(title=title[:300], origin="manual"))
        db.commit()
        flash(request, "Tema agregado.")
    return redirect("/temas")


@panel.post("/temas/pedir")
def request_topics(request: Request, background: BackgroundTasks, cantidad: int = Form(5)):
    count = max(1, min(10, cantidad))
    launch_agent(
        background, request, "researcher",
        f"El investigador está buscando {count} temas. Tarda uno o dos minutos; recarga esta página.",
        count=count,
    )
    return redirect("/temas")


@panel.get("/temas/{topic_id}", response_class=HTMLResponse)
def topic_detail(topic_id: int, request: Request, db: Session = Depends(get_db)):
    return render(request, db, "tema_detalle.html", topic=get_topic(db, topic_id))


@panel.post("/temas/{topic_id}/descartar")
def discard_topic(topic_id: int, request: Request, db: Session = Depends(get_db)):
    topic = get_topic(db, topic_id)
    topic.status = "discarded"
    topic.decided_at = utcnow()
    db.commit()
    flash(request, f"Tema descartado: {topic.title}")
    return redirect("/temas")


@panel.post("/temas/{topic_id}/recuperar")
def restore_topic(topic_id: int, request: Request, db: Session = Depends(get_db)):
    topic = get_topic(db, topic_id)
    topic.status = "proposed"
    topic.decided_at = None
    db.commit()
    flash(request, f"Tema recuperado: {topic.title}")
    return redirect("/temas")


@panel.post("/temas/{topic_id}/video")
def topic_to_video(
    topic_id: int, request: Request, formato: str = Form("short"), db: Session = Depends(get_db)
):
    topic = get_topic(db, topic_id)
    video = Video(topic_id=topic.id, title=topic.title, format="long" if formato == "long" else "short")
    video.scripts.append(Script(version=1))
    topic.status = "used"
    topic.decided_at = utcnow()
    db.add(video)
    db.commit()
    flash(request, "Video creado. Completa el guion y envíalo a revisión.")
    return redirect(f"/videos/{video.id}")


@panel.post("/temas/{topic_id}/datos")
def add_fact(
    topic_id: int,
    request: Request,
    dato: str = Form(""),
    fuente1: str = Form(""),
    fuente2: str = Form(""),
    volver: str = Form(""),
    db: Session = Depends(get_db),
):
    topic = get_topic(db, topic_id)
    claim = dato.strip()
    if claim:
        fact = Fact(claim=claim)
        # Solo se aceptan enlaces web normales.
        urls = [
            u.strip()
            for u in (fuente1, fuente2)
            if u.strip().lower().startswith(("http://", "https://"))
        ]
        urls = list(dict.fromkeys(urls))  # dos veces el mismo enlace cuenta como una fuente
        for url in urls:
            fact.sources.append(Source(url=url))
        # Un dato solo cuenta como verificado con dos fuentes.
        fact.verified = len(urls) >= 2
        topic.facts.append(fact)
        db.commit()
        flash(request, "Dato agregado." if fact.verified else "Dato agregado. Faltan fuentes para verificarlo.")
    return redirect(volver if volver.startswith("/") else f"/temas/{topic.id}")


@panel.post("/datos/{fact_id}/eliminar")
def delete_fact(fact_id: int, request: Request, volver: str = Form(""), db: Session = Depends(get_db)):
    fact = db.get(Fact, fact_id)
    if fact is None:
        raise HTTPException(status_code=404, detail="Dato no encontrado")
    topic_id = fact.topic_id
    db.delete(fact)
    db.commit()
    flash(request, "Dato eliminado.")
    return redirect(volver if volver.startswith("/") else f"/temas/{topic_id}")


# --------------------------------------------------------------------------
# Videos
# --------------------------------------------------------------------------
@panel.get("/videos", response_class=HTMLResponse)
def videos(request: Request, estado: str = "", q: str = "", db: Session = Depends(get_db)):
    query = db.query(Video)
    if estado in VIDEO_STATUS:
        query = query.filter(Video.status == estado)
    else:
        estado = ""
    term = q.strip()
    if term:
        query = query.filter(func.lower(Video.title).like(f"%{term.lower()}%"))
    items = query.order_by(Video.created_at.desc(), Video.id.desc()).all()
    return render(request, db, "videos.html", videos=items, estado=estado, q=term)


@panel.get("/videos/{video_id}", response_class=HTMLResponse)
def video_detail(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    tz = get_tz(get_settings(db))
    local = to_local(video.scheduled_at, tz)
    return render(
        request,
        db,
        "video_detalle.html",
        video=video,
        script=video.current_script,
        scheduled_value=f"{local:%Y-%m-%dT%H:%M}" if local else "",
    )


@panel.post("/videos/{video_id}")
def update_video(
    video_id: int,
    request: Request,
    titulo: str = Form(""),
    formato: str = Form("short"),
    programado: str = Form(""),
    duracion: str = Form(""),
    gancho: str = Form(""),
    prueba: str = Form(""),
    giro: str = Form(""),
    opinion: str = Form(""),
    db: Session = Depends(get_db),
):
    video = get_video(db, video_id)
    tz = get_tz(get_settings(db))
    if titulo.strip():
        video.title = titulo.strip()[:300]
    video.format = "long" if formato == "long" else "short"
    video.duration_s = int(duracion) if duracion.strip().isdigit() else None

    if programado.strip():
        try:
            video.scheduled_at = to_utc(datetime.strptime(programado.strip(), "%Y-%m-%dT%H:%M"), tz)
        except ValueError:
            flash(request, "La fecha no es válida; no se cambió.")
    else:
        video.scheduled_at = None
    if video.status in ("approved", "scheduled"):
        video.status = "scheduled" if video.scheduled_at else "approved"

    script = video.current_script
    if script is None:
        script = Script(version=1)
        video.scripts.append(script)
    script.hook, script.proof, script.twist, script.opinion = (
        gancho.strip(),
        prueba.strip(),
        giro.strip(),
        opinion.strip(),
    )
    db.commit()
    if not request.session.get("flash"):
        flash(request, "Cambios guardados.")
    return redirect(f"/videos/{video.id}")


@panel.post("/videos/{video_id}/revision")
def send_to_review(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    script = video.current_script
    if script is None or not all([script.hook, script.proof, script.twist, script.opinion]):
        flash(request, "Completa las cuatro partes del guion antes de enviarlo a revisión.")
        return redirect(f"/videos/{video.id}")
    settings = get_settings(db)
    if settings.get("publish_mode") == "automatic":
        approve(video)
        flash(request, "Modo automático: el video quedó aprobado sin revisión.")
    else:
        video.status = "pending_review"
        flash(request, "Video enviado a la cola de aprobación.")
    db.commit()
    return redirect(f"/videos/{video.id}")


@panel.post("/videos/{video_id}/guion")
def write_script(video_id: int, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    if not video.topic or not any(f.verified for f in video.topic.facts):
        flash(request, "El guionista solo usa datos verificados. Agrega al menos un dato con dos fuentes.")
        return redirect(f"/videos/{video.id}")
    launch_agent(
        background, request, "writer",
        "El guionista está escribiendo el guion. Recarga esta página en un minuto.",
        video_id=video.id,
    )
    return redirect(f"/videos/{video.id}")


@panel.post("/videos/{video_id}/reabrir")
def reopen_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    video.status = "in_production"
    db.commit()
    flash(request, "El video volvió a producción.")
    return redirect(f"/videos/{video.id}")


@panel.post("/videos/{video_id}/eliminar")
def delete_video(video_id: int, request: Request, db: Session = Depends(get_db)):
    video = get_video(db, video_id)
    title = video.title
    db.delete(video)
    db.commit()
    flash(request, f"Video eliminado: {title}")
    return redirect("/videos")


# --------------------------------------------------------------------------
# Agentes
# --------------------------------------------------------------------------
@panel.get("/agentes", response_class=HTMLResponse)
def agents(request: Request, db: Session = Depends(get_db)):
    items = db.query(Agent).options(selectinload(Agent.runs)).order_by(Agent.run_order).all()
    tz = get_tz(get_settings(db))
    cards = []
    for agent in items:
        last = agent.runs[0] if agent.runs else None
        if last is None:
            summary = "Aún sin ejecuciones"
        else:
            summary = f"Última ejecución: {fmt_datetime(last.started_at, tz)}, {RUN_STATUS.get(last.status, last.status)}"
        cards.append(
            {"agent": agent, "summary": summary, "last": last, "ready": agent.code in runner.IMPLEMENTED}
        )
    return render(request, db, "agentes.html", cards=cards, llm_ready=llm.is_configured())


@panel.post("/agentes/pausar-todos")
def pause_all_agents(request: Request, db: Session = Depends(get_db)):
    db.query(Agent).update({Agent.status: "paused"})
    db.commit()
    flash(request, "Todos los agentes quedaron en pausa.")
    return redirect("/agentes")


@panel.post("/agentes/activar-todos")
def activate_all_agents(request: Request, db: Session = Depends(get_db)):
    db.query(Agent).update({Agent.status: "active"})
    db.commit()
    flash(request, "Todos los agentes quedaron activos.")
    return redirect("/agentes")


@panel.post("/agentes/{agent_id}/alternar")
def toggle_agent(agent_id: int, request: Request, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    agent.status = "paused" if agent.status == "active" else "active"
    db.commit()
    flash(request, f"{agent.name}: {'activo' if agent.status == 'active' else 'en pausa'}.")
    return redirect("/agentes")


def launch_agent(background: BackgroundTasks, request: Request, code: str, message: str, **params) -> bool:
    """Arranca un agente en segundo plano. Devuelve False si falta la clave del modelo."""
    if not llm.is_configured():
        flash(request, "Falta la clave del modelo de IA: agrega la variable de entorno ANTHROPIC_API_KEY.")
        return False
    run_id = runner.start_run(code)
    background.add_task(runner.execute, run_id, code, **params)
    flash(request, message)
    return True


@panel.post("/agentes/{agent_id}/ejecutar")
def run_agent(
    agent_id: int, request: Request, background: BackgroundTasks, db: Session = Depends(get_db)
):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    if agent.code == "researcher":
        launch_agent(
            background, request, "researcher",
            "El investigador está buscando 5 temas. Tarda uno o dos minutos; revisa Temas o su registro.",
            count=5,
        )
        return redirect("/agentes")
    if agent.code == "writer":
        launch_agent(
            background, request, "writer",
            "El guionista está escribiendo los guiones vacíos. Revisa la cola de aprobación en un minuto.",
        )
        return redirect("/agentes")
    # Los demás agentes todavía no están programados. Se deja constancia del intento.
    now = utcnow()
    db.add(
        AgentRun(
            agent_id=agent.id,
            trigger="manual",
            status="cancelled",
            started_at=now,
            finished_at=now,
            log="Este agente todavía no está implementado. No se hizo ningún trabajo.",
        )
    )
    db.commit()
    flash(request, f"{agent.name} todavía no está implementado; no se ejecutó nada.")
    return redirect("/agentes")


@panel.get("/agentes/{agent_id}/registro", response_class=HTMLResponse)
def agent_log(agent_id: int, request: Request, db: Session = Depends(get_db)):
    agent = db.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agente no encontrado")
    runs = (
        db.query(AgentRun)
        .filter(AgentRun.agent_id == agent.id)
        .order_by(AgentRun.started_at.desc(), AgentRun.id.desc())
        .limit(100)
        .all()
    )
    return render(request, db, "agente_registro.html", agent=agent, runs=runs, run_status=RUN_STATUS)


# --------------------------------------------------------------------------
# Ajustes
# --------------------------------------------------------------------------
@panel.get("/ajustes", response_class=HTMLResponse)
def settings_page(request: Request, db: Session = Depends(get_db)):
    accounts = (
        db.query(PlatformAccount)
        .options(selectinload(PlatformAccount.platform))
        .order_by(PlatformAccount.platform_id)
        .all()
    )
    services = db.query(ServiceConnection).order_by(ServiceConnection.id).all()
    opinions = db.query(OpinionBank).order_by(OpinionBank.id.desc()).all()
    return render(
        request,
        db,
        "ajustes.html",
        accounts=accounts,
        services=services,
        opinions=opinions,
        llm_ready=llm.is_configured(),
        llm_model=llm.model_name(),
    )


@panel.post("/opiniones")
def add_opinion(request: Request, texto: str = Form(""), db: Session = Depends(get_db)):
    text = texto.strip()
    if text:
        db.add(OpinionBank(text=text[:1000]))
        db.commit()
        flash(request, "Frase agregada.")
    return redirect("/ajustes#opiniones")


@panel.post("/opiniones/{opinion_id}/eliminar")
def delete_opinion(opinion_id: int, request: Request, db: Session = Depends(get_db)):
    opinion = db.get(OpinionBank, opinion_id)
    if opinion is not None:
        db.delete(opinion)
        db.commit()
        flash(request, "Frase eliminada.")
    return redirect("/ajustes#opiniones")


@panel.post("/ajustes")
def save_settings(
    request: Request,
    channel_name: str = Form(""),
    publish_mode: str = Form("approval"),
    shorts_per_week: str = Form("5"),
    longs_per_week: str = Form("1"),
    publish_time_local: str = Form("18:00"),
    tz_name: str = Form("America/Ciudad_Juarez"),
    db: Session = Depends(get_db),
):
    def clamp(value: str, low: int, high: int, default: int) -> str:
        number = int(value) if value.strip().isdigit() else default
        return str(max(low, min(high, number)))

    try:
        datetime.strptime(publish_time_local.strip(), "%H:%M")
        publish_time = publish_time_local.strip()
    except ValueError:
        publish_time = "18:00"
    try:
        ZoneInfo(tz_name.strip())
        tz_value = tz_name.strip()
    except (ZoneInfoNotFoundError, ValueError):
        tz_value = "America/Ciudad_Juarez"

    new_values = {
        "channel_name": channel_name.strip()[:80],
        "publish_mode": "automatic" if publish_mode == "automatic" else "approval",
        "shorts_per_week": clamp(shorts_per_week, 0, 14, 5),
        "longs_per_week": clamp(longs_per_week, 0, 7, 1),
        "publish_time_local": publish_time,
        "timezone": tz_value,
    }
    current = {s.key: s for s in db.query(Setting).all()}
    for key, value in new_values.items():
        if key in current:
            current[key].value = value
        else:
            db.add(Setting(key=key, value=value))
    db.commit()
    flash(request, "Ajustes guardados.")
    return redirect("/ajustes")


app.include_router(panel)
