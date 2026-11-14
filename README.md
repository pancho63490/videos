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
- **Configuración inicial y Guía de inicio:** el programa pide crear la cuenta la primera vez y guía paso a paso lo que falta por configurar.

## Qué falta

- Los agentes de voz, visuales, editor, publicador y analista todavía no están programados: "Ejecutar" solo deja constancia en su registro.
- Los agentes se ejecutan a mano desde el panel; todavía no hay ejecución programada.
- La conexión con YouTube, TikTok, Facebook e Instagram llegará con el agente publicador.
- No hay métricas todavía; las tablas ya existen.

## Ejecutarlo en tu computadora

```bash
python3 -m venv .venv
source .venv/bin/activate          # En Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Abre http://127.0.0.1:8000. No hace falta configurar nada antes: el programa
te guía.

1. **Crea tu cuenta.** La primera vez, la Terminal muestra un recuadro
   "CONFIGURACIÓN INICIAL" con un código. El navegador te lo pide junto con tu
   correo y una contraseña.
2. **Sigue la Guía de inicio.** Al entrar verás seis pasos; cada uno dice qué
   falta, cómo conseguirlo y te deja capturarlo ahí mismo: nombre del canal,
   clave del modelo de IA, frases de opinión, primer tema y primer video.

La base de datos se crea sola en el archivo `canal.db`. No se necesita Docker.

## Desplegarlo en Render

1. Sube este repositorio a GitHub.
2. En Render elige **New > Blueprint** y selecciona el repositorio. El archivo
   `render.yaml` crea el servicio web y la base de datos PostgreSQL.
3. Cuando termine el despliegue, abre la pestaña **Logs** del servicio, copia
   el código del recuadro "CONFIGURACIÓN INICIAL" y abre la dirección del panel.
4. Crea tu cuenta con ese código y sigue la Guía de inicio.

### Avisos sobre el plan gratuito de Render

- El servicio web se duerme cuando no hay visitas; la primera carga tarda.
- El disco no es permanente, por eso los datos van en PostgreSQL y no en SQLite.
- La base de datos gratuita tiene fecha de vencimiento. Revisa las condiciones
  actuales en Render antes de guardar ahí datos importantes.
- Generar video con FFmpeg necesita más memoria que la del plan gratuito. Los
  agentes de voz y edición probablemente correrán en tu computadora o en un
  plan de pago.

## Variables de entorno (opcionales)

Todo se puede configurar desde el panel. Estas variables solo hacen falta si
prefieres no guardar esos datos en la base; cuando existen, tienen prioridad.

| Variable | Para qué |
| --- | --- |
| `ADMIN_EMAIL` y `ADMIN_PASSWORD` | Cuenta para entrar, en lugar de crearla en el panel |
| `ANTHROPIC_API_KEY` | Clave del modelo de IA, en lugar de capturarla en la Guía de inicio |
| `ANTHROPIC_MODEL` | Modelo a usar; por defecto `claude-sonnet-5-5` |
| `SECRET_KEY` | Firma de la sesión; si falta, el panel genera una y la guarda |
| `DATABASE_URL` | Conexión a PostgreSQL; sin ella se usa SQLite |

La clave del modelo capturada en el panel se guarda en la base de datos sin
cifrar. Si eso no te conviene, usa la variable de entorno.

Cada ejecución de un agente consume créditos de la API del modelo, y la
búsqueda web del investigador se cobra aparte por búsqueda. Revisa los precios
vigentes antes de ejecutarlos seguido.

## Estructura

```
app/
  main.py        Rutas del panel
  models.py      Tablas de la base de datos
  db.py          Conexión a la base de datos
  config.py      Cuenta, clave del modelo y secreto capturados desde el panel
  seed.py        Datos iniciales (ajustes, plataformas, agentes, primeros temas)
  agents/        Agentes: cliente del modelo de IA, investigador, guionista y ejecutor
  templates/     Pantallas
  static/        Estilos
render.yaml      Configuración de Render
requirements.txt Dependencias
```
