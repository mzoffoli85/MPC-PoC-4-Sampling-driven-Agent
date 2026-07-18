"""Cliente mínimo de prueba para server.py.

Existe porque, al momento de escribir esto, ni Claude CLI ni Claude Desktop
implementan `sampling/createMessage` como cliente MCP (ver README.md). Sin
un cliente que apruebe y resuelva Sampling, la tool `summarize_and_rate` no
tiene forma de probarse end-to-end.

Este cliente:
  1. Lanza server.py como subproceso via stdio.
  2. Registra un `sampling_callback`: cada vez que el server pide
     sampling/createMessage, el callback se ejecuta ACÁ, del lado del
     cliente — esa inversión de flujo (server → client) es el punto
     central de la PoC.
  3. Simula el punto de aprobación human-in-the-loop: imprime la solicitud
     completa (mensajes, systemPrompt, maxTokens, temperature,
     modelPreferences) y, según el modo, pide confirmación por consola o
     aprueba automáticamente.
  4. Como no hay una API key de LLM real disponible en este cliente de
     prueba (deliberado — ver context.md), la "generación" aprobada se
     resuelve con un generador de texto determinístico y local (ver
     `_fake_llm_summarize` / `_fake_llm_rate`) que cumple el rol que en un
     host real cumpliría Claude/GPT/etc. Esto prueba el PROTOCOLO de
     Sampling (la solicitud, la aprobación, la respuesta), no la calidad
     de un LLM real.

Modos de aprobación (variable de entorno SAMPLING_MODE):
  - "interactive" (default): pregunta y/n en consola por cada solicitud.
  - "auto-approve": aprueba todo automáticamente (útil para CI / pruebas rápidas).
  - "auto-reject": rechaza todo automáticamente (para probar el manejo de error).
"""

import asyncio
import os
import re
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

sys.stderr.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")

SERVER_SCRIPT = Path(__file__).parent / "server.py"
SAMPLING_MODE = os.environ.get("SAMPLING_MODE", "interactive")


def _extract_prompt_text(params: types.CreateMessageRequestParams) -> str:
    parts = []
    for msg in params.messages:
        content = msg.content
        if isinstance(content, list):
            content = content[0]
        text = getattr(content, "text", str(content))
        parts.append(f"  [{msg.role}] {text}")
    return "\n".join(parts)


def _print_request(params: types.CreateMessageRequestParams) -> None:
    print("\n" + "=" * 70, file=sys.stderr)
    print("SAMPLING REQUEST recibido del server (sampling/createMessage)", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    if params.systemPrompt:
        print(f"systemPrompt: {params.systemPrompt}", file=sys.stderr)
    print(f"maxTokens: {params.maxTokens}   temperature: {params.temperature}", file=sys.stderr)
    if params.modelPreferences:
        mp = params.modelPreferences
        print(
            f"modelPreferences: intelligence={mp.intelligencePriority} "
            f"speed={mp.speedPriority} cost={mp.costPriority}",
            file=sys.stderr,
        )
    print("messages:", file=sys.stderr)
    print(_extract_prompt_text(params), file=sys.stderr)
    print("=" * 70, file=sys.stderr)


def _approve(params: types.CreateMessageRequestParams) -> bool:
    if SAMPLING_MODE == "auto-approve":
        print(">>> [auto-approve] solicitud aprobada automáticamente", file=sys.stderr)
        return True
    if SAMPLING_MODE == "auto-reject":
        print(">>> [auto-reject] solicitud rechazada automáticamente", file=sys.stderr)
        return False
    # interactive: éste es el punto human-in-the-loop real.
    answer = input(">>> ¿Aprobar esta solicitud de sampling? [y/N]: ").strip().lower()
    return answer == "y"


def _fake_llm_summarize(prompt_text: str) -> str:
    """Sustituto local y determinístico del LLM del host, solo para poder
    probar el flujo sin API keys. Un host real (Claude Desktop, etc.) usaría
    su propio modelo acá."""
    match = re.search(r"TEXTO:\n(.*)", prompt_text, re.DOTALL)
    source = match.group(1).strip() if match else prompt_text
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", source) if s.strip()]
    bullets = sentences[:3] if sentences else [source[:80]]
    while len(bullets) < 3:
        bullets.append("(sin más contenido para resumir)")
    return "\n".join(f"- {b}" for b in bullets)


def _fake_llm_rate(prompt_text: str) -> str:
    keywords = ["senior", "líder", "lead", "arquitect", "estrategia", "equipo", "gerenc", "director"]
    lower = prompt_text.lower()
    score = 3 + sum(1 for k in keywords if k in lower)
    score = max(1, min(score, 10))
    return f"Rating: {score}\nJustificación: calculado localmente por test_client (stub, no LLM real)."


async def sampling_callback(
    context,
    params: types.CreateMessageRequestParams,
) -> types.CreateMessageResult | types.ErrorData:
    _print_request(params)

    if not _approve(params):
        print(">>> Solicitud RECHAZADA por el usuario.\n", file=sys.stderr)
        return types.ErrorData(
            code=types.INVALID_REQUEST,
            message="User rejected the sampling request",
        )

    prompt_text = _extract_prompt_text(params)
    is_rating_step = "calificá" in prompt_text.lower() or "rating:" in prompt_text.lower()
    response_text = _fake_llm_rate(prompt_text) if is_rating_step else _fake_llm_summarize(prompt_text)

    print(f">>> Solicitud APROBADA. Respuesta generada:\n{response_text}\n", file=sys.stderr)

    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(type="text", text=response_text),
        model="test-client-fake-llm/v1",
        stopReason="endTurn",
    )


async def main() -> None:
    sample_text = (
        "Buscamos un/a Head of Engineering para liderar un equipo de 25 personas "
        "distribuidas en 3 países. La persona seleccionada definirá la estrategia "
        "técnica de la plataforma, participará del comité de dirección, y será "
        "responsable de la arquitectura de los sistemas core. Se requiere "
        "experiencia previa como líder de equipos senior y manejo de presupuesto "
        "de ingeniería."
    )
    if len(sys.argv) > 1:
        sample_text = " ".join(sys.argv[1:])

    server_params = StdioServerParameters(
        command=sys.executable,
        args=[str(SERVER_SCRIPT)],
    )

    print(f"Conectando a {SERVER_SCRIPT} vía stdio (SAMPLING_MODE={SAMPLING_MODE})...", file=sys.stderr)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read,
            write,
            sampling_callback=sampling_callback,
        ) as session:
            await session.initialize()
            print("Sesión inicializada. Invocando tool summarize_and_rate...\n", file=sys.stderr)

            result = await session.call_tool(
                "summarize_and_rate",
                arguments={"text": sample_text},
            )

            print("\n" + "#" * 70, file=sys.stderr)
            print("RESULTADO FINAL DE LA TOOL", file=sys.stderr)
            print("#" * 70, file=sys.stderr)
            for block in result.content:
                if isinstance(block, types.TextContent):
                    print(block.text, file=sys.stderr)
            if result.isError:
                print("(la tool reportó un error)", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
