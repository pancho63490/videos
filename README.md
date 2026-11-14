# Panel del canal de curiosidades

Panel web para administrar un canal de videos de curiosidades: temas, datos
verificados, guiones, cola de aprobación, calendario, agentes y ajustes.

Hecho con FastAPI, SQLAlchemy y plantillas Jinja2. Usa PostgreSQL en Render y
SQLite en tu computadora.

## Qué hace hoy

- **Temas:** agregar, descartar, recuperar y convertir en video.
- **Datos y fuentes:** cada afirmación se registra con sus enlaces; con dos fuentes cuenta como verificada.
- **Videos:** editar título, formato, fecha, duración y guion (gancho, prueba, giro, opinión).
- **Cola de aprobación:** aprobar o rechazar cada video, o aprobar de una vez los verificados.
- **Calendario:** vista semanal de lo programado, en tu zona horaria.
- **Agentes:** activar o pausar cada uno o todos, y ver su registro.
- **Agente investigador:** busca en la web, propone temas nuevos y registra cada dato con sus fuentes. Solo acepta enlaces que la búsqueda devolvió de verdad, y un dato cuenta como verificado con dos fuentes de sitios distintos.
- **Agente guionista:** escribe el guion usando únicamente los datos verificados del tema y tus frases de opinión, y manda el video a revisión.
- **Ajustes:** nombre del canal, modo de publicación, ritmo semanal, hora y tus frases de opinión.

## Qué falta

- Los agentes de voz, visuales, editor, publicador y analista todavía no están programados: "Ejecutar" solo deja constancia en su registro.
- Los agentes se ejecutan a mano desde el panel; todavía no hay ejecución programada.
- La conexión con YouTube, TikTok, Facebook e Instagram llegará con el agente publicador.
- No hay métricas todavía; las tablas ya existen.

## Ejecutarlo en tu computadora

```bash
python -m venv .venv
source .venv/bin/activate          # En Windows: .venv\Scripts\activate
pip install -r requirements.txt

export ADMIN_EMAIL="tu@correo.com"       # En Windows (PowerShell): $env:ADMIN_EMAIL="tu@correo.com"
export ADMIN_PASSWORD="una-clave-larga"  # En Windows (PowerShell): $env:ADMIN_PASSWORD="una-clave-larga"

uvicorn app.main:app --reload
```

Abre http://127.0.0.1:8000 e inicia sesión con ese correo y esa clave. La base
de datos se crea sola en el archivo `canal.db`.

## Desplegarlo en Render

1. Sube este repositorio a GitHub.
2. En Render elige **New > Blueprint** y selecciona el repositorio. El archivo
   `render.yaml` crea el servicio web y la base de datos PostgreSQL.
3. Render te pedirá dos valores: `ADMIN_EMAIL` y `ADMIN_PASSWORD`. Usa una clave larga.
4. Espera a que termine el despliegue y abre la dirección que te da Render.

`SECRET_KEY` y `DATABASE_URL` se configuran solos.

### Avisos sobre el plan gratuito de Render

- El servicio web se duerme cuando no hay visitas; la primera carga tarda.
- El disco no es permanente, por eso los datos van en PostgreSQL y no en SQLite.
- La base de datos gratuita tiene fecha de vencimiento. Revisa las condiciones
  actuales en Render antes de guardar ahí datos importantes.
- Generar video con FFmpeg necesita más memoria que la del plan gratuito. Los
  agentes de voz y edición probablemente correrán en tu computadora o en un
  plan de pago.

## Variables de entorno

| Variable | Para qué | Obligatoria |
| --- | --- | --- |
| `ADMIN_EMAIL` | Correo para entrar al panel | Sí |
| `ADMIN_PASSWORD` | Contraseña para entrar al panel | Sí |
| `SECRET_KEY` | Firma de la sesión; Render la genera | En producción |
| `DATABASE_URL` | Conexión a PostgreSQL; sin ella se usa SQLite | En producción |
| `ANTHROPIC_API_KEY` | Clave del modelo de IA para el investigador y el guionista | Para usar los agentes |
| `ANTHROPIC_MODEL` | Modelo a usar; por defecto `claude-sonnet-5-5` | No |

Cada ejecución de un agente consume créditos de la API del modelo, y la
búsqueda web del investigador se cobra aparte por búsqueda. Revisa los precios
vigentes antes de ejecutarlos seguido.

## Estructura

```
app/
  main.py        Rutas del panel
  models.py      Tablas de la base de datos
  db.py          Conexión a la base de datos
  seed.py        Datos iniciales (ajustes, plataformas, agentes, primeros temas)
  agents/        Agentes: cliente del modelo de IA, investigador, guionista y ejecutor
  templates/     Pantallas
  static/        Estilos
render.yaml      Configuración de Render
requirements.txt Dependencias
```
