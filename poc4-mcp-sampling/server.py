"""PoC 4 — MCP server que usa Sampling en vez de traer modelo propio.

La tool `summarize_and_rate` no llama a ninguna API de LLM externa. En cambio,
emite dos solicitudes `sampling/createMessage` encadenadas hacia el host:

    1) Pide un resumen en 3 bullets del texto de entrada.
    2) Con ese resumen, pide una calificación 1-10 de qué tan relevante es
       para un perfil senior/liderazgo IT.

Todo el "pensar" lo hace el modelo del host, no el server. El server solo
orquesta. Ver README.md para el detalle de por qué esto requiere un cliente
que soporte Sampling (Claude CLI y Claude Desktop, al momento de escribir
esto, no lo soportan) y cómo probarlo con test_client.py.
"""

import logging
import re
import sys

from mcp.server.fastmcp import Context, FastMCP
from mcp.shared.exceptions import McpError
from mcp.types import ModelPreferences, SamplingMessage, TextContent

# En Windows, stderr puede quedar en el codepage legacy (cp1252) y corromper
# tildes/ñ. stdout NO se toca: el transporte stdio lo necesita intacto para
# los mensajes JSON-RPC.
sys.stderr.reconfigure(encoding="utf-8")

# Logging a stderr: stdout está reservado para los mensajes JSON-RPC del
# transporte stdio. Escribir logs ahí rompería el protocolo.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("poc4-sampling-server")

mcp = FastMCP("poc4-sampling")


def _user_message(text: str) -> list[SamplingMessage]:
    return [
        SamplingMessage(
            role="user",
            content=TextContent(type="text", text=text),
        )
    ]


def _extract_text(result) -> str:
    content = result.content
    if isinstance(content, list):
        content = content[0]
    if getattr(content, "type", None) == "text":
        return content.text
    return str(content)


def _parse_rating(raw: str) -> int | None:
    match = re.search(r"\b(10|[1-9])\b", raw)
    return int(match.group(1)) if match else None


@mcp.tool()
async def summarize_and_rate(text: str, ctx: Context) -> dict:
    """Resume un texto en 3 bullets y lo califica 1-10 para un perfil senior/liderazgo IT.

    Ambos pasos se resuelven vía Sampling: el server no trae modelo propio,
    delega toda la generación al LLM del host (con aprobación human-in-the-loop
    en cada solicitud).
    """
    logger.info("summarize_and_rate: recibido texto de %d caracteres", len(text))

    # --- Paso 1: resumen en 3 bullets ---------------------------------
    # temperature baja (0.2): queremos un resumen fiel y reproducible, no
    # creativo. maxTokens acotado (300) porque son solo 3 bullets.
    # modelPreferences: priorizamos intelligence sobre speed, ya que resumir
    # bien requiere entender el texto, no solo ser rápido.
    logger.info("Paso 1/2: solicitando resumen vía sampling/createMessage")
    try:
        summary_result = await ctx.session.create_message(
            messages=_user_message(
                "Resumí el siguiente texto en exactamente 3 bullets, "
                "concisos y en español. No agregues nada más que los bullets.\n\n"
                f"TEXTO:\n{text}"
            ),
            system_prompt=(
                "Sos un asistente que resume texto profesional en bullets "
                "claros y objetivos. Respondé solo con los 3 bullets."
            ),
            max_tokens=300,
            temperature=0.2,
            model_preferences=ModelPreferences(
                intelligencePriority=0.8,
                speedPriority=0.2,
            ),
        )
    except McpError as e:
        logger.warning("Sampling rechazado/fallido en paso 1 (resumen): %s", e.error.message)
        return {
            "error": True,
            "stage": "summary",
            "message": f"El host rechazó o no pudo completar la solicitud de resumen: {e.error.message}",
        }

    summary = _extract_text(summary_result).strip()
    logger.info("Paso 1/2 completo. Modelo usado por el host: %s", summary_result.model)

    # --- Paso 2: calificación 1-10 ------------------------------------
    # temperature aún más baja (0.1): queremos un número consistente, no
    # variabilidad creativa. maxTokens muy chico (50) porque solo pedimos
    # un número y una justificación breve.
    logger.info("Paso 2/2: solicitando calificación vía sampling/createMessage")
    try:
        rating_result = await ctx.session.create_message(
            messages=_user_message(
                "Con base en este resumen, calificá de 1 a 10 qué tan "
                "relevante es el texto original para un perfil senior o de "
                "liderazgo en IT. Respondé en el formato:\n"
                "Rating: <número>\nJustificación: <una oración>\n\n"
                f"RESUMEN:\n{summary}"
            ),
            system_prompt=(
                "Sos un evaluador de contenido profesional para perfiles "
                "senior/liderazgo en tecnología. Respondé siempre con el "
                "formato pedido."
            ),
            max_tokens=100,
            temperature=0.1,
            model_preferences=ModelPreferences(
                intelligencePriority=0.6,
                speedPriority=0.4,
            ),
        )
    except McpError as e:
        logger.warning("Sampling rechazado/fallido en paso 2 (rating): %s", e.error.message)
        return {
            "error": True,
            "stage": "rating",
            "summary": summary,
            "message": f"El host rechazó o no pudo completar la solicitud de calificación: {e.error.message}",
        }

    rating_text = _extract_text(rating_result).strip()
    rating = _parse_rating(rating_text)
    logger.info("Paso 2/2 completo. Rating extraído: %s", rating)

    return {
        "error": False,
        "summary": summary,
        "rating": rating,
        "rating_raw": rating_text,
    }


if __name__ == "__main__":
    mcp.run(transport="stdio")
