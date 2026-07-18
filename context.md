# PoC 4 — MCP Sampling-driven Agent

> Inicializador para Claude Code. Cuarta PoC de la serie "Aprender MCP en profundidad".
> Objetivo: dominar **Sampling** — el primitivo del client que invierte el flujo: el server pide al host que el LLM genere.

---

## Contexto para Claude Code

Soy Marco. Terminé las PoC 1 (Tools), 2 (Resources) y 3 (Prompts) — los tres primitivos del server. Manejo arquitectura MCP, handshake y transporte stdio.

**No expliques teoría de MCP a menos que la pida.** Esta PoC es sobre un primitivo del **client**: Sampling.

---

## ⚠️ CHECK PREVIO OBLIGATORIO (hacer ANTES de codear)

Sampling tiene **soporte desigual entre clientes MCP**. Antes de invertir tiempo:

1. Verificá si el cliente que vas a usar soporta `sampling/createMessage` en su versión actual. La API cambia rápido — no asumas.
2. Si el cliente no lo soporta, la alternativa es usar el **MCP Inspector** oficial o un cliente de prueba que sí implemente Sampling, o escribir un client mínimo con el SDK que apruebe las solicitudes automáticamente.
3. Documentá en el README qué cliente terminaste usando y su versión.

**No sigas sin resolver esto** — es la diferencia entre una PoC que corre y una que se queda a medias.

### Resultado del check (2026-07-18)

- **Cliente elegido: Claude CLI (Claude Code), no Claude Desktop.**
- **Claude Code CLI NO soporta Sampling.** Confirmado: `sampling/createMessage` no está implementado como cliente MCP en Claude Code — feature request abierto sin resolver ([anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785)). No hay flag ni config que lo habilite.
- **Decisión**: se prueba el server con **`test_client.py`** (cliente mínimo con el SDK Python `mcp`, usando un `sampling_callback` que auto-aprueba las solicitudes) y opcionalmente con el **MCP Inspector** oficial (`npx @modelcontextprotocol/inspector <server-command>`), que sí visualiza y permite aprobar `sampling/createMessage` interactivamente.
- Esto vuelve **obligatorio** el paso 4 de "Pasos de trabajo" (`test_client.py`), no opcional.

---

## Objetivo de esta PoC

Construir un MCP server que, en el curso de ejecutar una Tool, **le pida al host que su LLM genere** un texto — en vez de traer su propio modelo. El server delega el razonamiento al modelo del host.

### La inversión del flujo

- **Tools/Resources/Prompts**: el host inicia, el server responde.
- **Sampling**: el **server inicia** una solicitud de generación, el host (con aprobación humana) genera y devuelve.

Esto permite servers "inteligentes" que no cargan ni pagan su propio modelo: usan el del host.

### Puntos de aprendizaje que cubre
- Primitivo **Sampling**: `sampling/createMessage`
- Inversión del flujo de control server → host
- **Human-in-the-loop**: el usuario aprueba qué se manda y qué vuelve
- Parámetros de sampling: `messages`, `systemPrompt`, `maxTokens`, `temperature`, `modelPreferences`
- Diseño de un server que compone: Tool → Sampling → resultado

---

## Stack

- **Python 3.11+**
- SDK oficial `mcp`
- Transporte **stdio**
- `uv`
- Cliente con soporte de Sampling (según el check previo)

---

## Estructura del proyecto

​```
poc4-mcp-sampling/
├── README.md
├── pyproject.toml
├── server.py               # el MCP server con Sampling
├── test_client.py          # cliente mínimo de prueba (si Claude Desktop no sirve)
├── .gitignore
​```

---

## Especificación

Un server con una tool que internamente **usa Sampling** para resolver su tarea. Idea concreta:

### Tool: `summarize_and_rate`
- **Input**: `text: str` (un texto largo — ej. una descripción de trabajo, un artículo)
- **Comportamiento interno**:
  1. La tool recibe el texto.
  2. El server hace un `sampling/createMessage` pidiéndole al LLM del host que **resuma** el texto en 3 bullets.
  3. Con el resumen, hace un **segundo sampling** pidiendo una **calificación** (1-10) de qué tan relevante es para un perfil senior/liderazgo IT.
  4. Devuelve resumen + rating combinados.
- **Patrón**: el server orquesta dos generaciones del host. No tiene modelo propio — todo el "pensar" lo hace el host.

> El dominio (evaluar descripciones de trabajo) es a propósito útil para mi búsqueda laboral. Si preferís algo más neutro para la PoC, un `smart_classifier` que clasifique texto en categorías vía Sampling sirve igual.

---

## Requisitos de implementación

1. La tool debe emitir solicitudes de Sampling al host, no llamar a ninguna API de LLM externa. **Cero API keys de modelos** — ese es el punto.
2. Manejar el caso en que el host **rechace** la solicitud de sampling (el usuario puede negar): devolver un error legible.
3. Parametrizar `maxTokens` y `temperature` en las solicitudes, y comentarlas para entender su efecto.
4. `modelPreferences`: probar a expresar una preferencia (velocidad vs inteligencia) y documentar si el host la respeta.
5. Logging a **stderr**.
6. Si escribís `test_client.py`: un cliente stdio mínimo que conecte al server, apruebe las solicitudes de sampling, e invoque la tool. Útil si el cliente gráfico no soporta Sampling.

---

## Pasos de trabajo (en orden)

1. **CHECK PREVIO** de soporte de Sampling (ver arriba). No saltear.
2. **Scaffolding**: estructura, `pyproject.toml`, `.gitignore`.
3. **server.py**: la tool `summarize_and_rate` con las dos solicitudes de sampling encadenadas.
4. **test_client.py** (obligatorio — Claude CLI no soporta Sampling): cliente que apruebe sampling automáticamente para poder probar.
5. **README.md**: el check de compatibilidad, cómo probar, y qué observar en el human-in-the-loop.
6. Probar el flujo completo y observar dónde aparece la aprobación del usuario.

---

## Criterios de aceptación (definición de "listo")

- [ ] Documentado qué cliente soporta Sampling y cuál se usó.
- [ ] La tool emite `sampling/createMessage` correctamente.
- [ ] El server NO usa ninguna API key de modelo externo — toda generación pasa por el host.
- [ ] Las dos generaciones encadenadas producen resumen + rating coherentes.
- [ ] Un rechazo de sampling por el usuario se maneja sin crash.
- [ ] Se observa el punto de aprobación human-in-the-loop en el flujo.
- [ ] README explica el check de compatibilidad y permite reproducir todo.

---

## Notas

- **Verificá la firma actual del SDK `mcp`** para el lado del server que emite sampling, y del lado del client que lo aprueba. Es la parte del SDK que menos madura está — revisá antes de asumir.
- Sampling es el primitivo con **más fricción de tooling** de toda la serie. Si te trabás, no es tu código necesariamente — es el ecosistema. Anotá los obstáculos en el README; son parte del aprendizaje real y valen para tu perfil.
- Al terminar, apartado "Qué aprendí" (3-4 bullets), con foco en **qué habilita Sampling que Tools no puede**: servers agénticos sin modelo propio, y el rol del human-in-the-loop como control de seguridad.

---

## Siguiente en la serie

**PoC 5** — HTTP/SSE Server con Auth deployado: migrar de stdio a transporte remoto con autenticación, cerrando la serie.