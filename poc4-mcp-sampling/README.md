# PoC 4 — MCP Sampling-driven Agent

Cuarta PoC de la serie "Aprender MCP en profundidad". Las PoC 1-3 cubrieron
los tres primitivos del **server** (Tools, Resources, Prompts). Esta cubre
el primitivo central del **client**: **Sampling**.

## La inversión del flujo

- Tools/Resources/Prompts: el host inicia, el server responde.
- Sampling: el **server inicia** una solicitud de generación
  (`sampling/createMessage`) y el host —con aprobación humana— genera y
  devuelve el texto.

Esto permite servers "inteligentes" que no cargan ni pagan su propio
modelo: usan el del host. En esta PoC, `server.py` **no llama a ninguna API
de LLM externa y no usa ninguna API key de modelo**. Toda la generación
pasa por el host vía Sampling.

## Check de compatibilidad (obligatorio antes de codear)

Sampling tiene soporte desigual entre clientes MCP. Antes de escribir una
línea de código se verificó:

| Cliente | Soporte de `sampling/createMessage` |
|---|---|
| **Claude CLI (Claude Code)** | ❌ No soportado. Feature request abierto sin resolver: [anthropics/claude-code#1785](https://github.com/anthropics/claude-code/issues/1785). No hay flag ni config que lo habilite. |
| Claude Desktop | Igual de desigual/no confiable — no se probó porque el cliente elegido para este check es Claude CLI, no Desktop. |
| MCP Inspector oficial (`npx @modelcontextprotocol/inspector`) | ✅ Soporta visualizar y aprobar `sampling/createMessage` interactivamente. Válido como alternativa exploratoria. |
| SDK Python `mcp` (cliente propio) | ✅ `ClientSession` acepta un `sampling_callback` — es la vía usada en esta PoC. |

**Conclusión**: como ningún cliente gráfico disponible soporta Sampling
hoy, la forma de probar `server.py` es con **`test_client.py`**, un
cliente stdio mínimo escrito con el SDK Python de `mcp` que implementa el
lado del client: recibe la solicitud de sampling, la muestra, la aprueba
(o rechaza) y devuelve una respuesta.

Este es exactamente el obstáculo que la consigna original anticipaba:
*"Sampling es el primitivo con más fricción de tooling de toda la
serie"*. Se confirma en la práctica — no es un problema del código de esta
PoC, es el estado del ecosistema de clientes MCP a mediados de 2026.

## Estructura

```
poc4-mcp-sampling/
├── README.md
├── pyproject.toml
├── server.py        # el MCP server con la tool summarize_and_rate
├── test_client.py    # cliente stdio mínimo que aprueba/rechaza sampling
└── .gitignore
```

## La tool: `summarize_and_rate`

Recibe `text: str` y hace dos solicitudes de Sampling encadenadas:

1. **Resumen**: pide al host resumir el texto en 3 bullets.
   `temperature=0.2` (bajo, para un resumen fiel y reproducible, no
   creativo), `maxTokens=300`, `modelPreferences` con
   `intelligencePriority=0.8` (resumir bien requiere entender el texto).
2. **Rating**: con el resumen ya generado, pide una calificación 1-10 de
   qué tan relevante es el texto para un perfil senior/liderazgo IT.
   `temperature=0.1` (más bajo aún — queremos un número consistente),
   `maxTokens=100`, `modelPreferences` más balanceado
   (`intelligencePriority=0.6`, `speedPriority=0.4`).

El server no tiene modelo propio: ambos pasos delegan el "pensar" al LLM
del host. Un rechazo de sampling en cualquiera de los dos pasos se captura
(`McpError`) y se devuelve como un resultado legible con `error: true`, sin
romper el proceso.

## `test_client.py`: qué hace y por qué

Como ningún cliente gráfico disponible soporta Sampling, `test_client.py`
juega el rol del **host**:

1. Lanza `server.py` como subproceso vía stdio.
2. Registra un `sampling_callback` — el punto donde, en un host real
   (Claude Desktop, etc.), se dispararía la UI de aprobación y el LLM
   propio del host generaría la respuesta.
3. Imprime la solicitud completa (`messages`, `systemPrompt`, `maxTokens`,
   `temperature`, `modelPreferences`) — esto es lo que un host real le
   mostraría al usuario antes de pedir aprobación.
4. Como este cliente de prueba **no tiene una API key de LLM real** (a
   propósito — ver más abajo por qué), la "generación" aprobada la resuelve
   un generador de texto local y determinístico
   (`_fake_llm_summarize` / `_fake_llm_rate`) que cumple el rol que
   cumpliría el modelo del host. Esto prueba el **protocolo** de Sampling
   (solicitud → aprobación → respuesta → server la consume), no la calidad
   de un LLM real — eso es responsabilidad del host, no de esta PoC.

### Por qué el cliente de prueba tampoco usa una API key

El requisito de "cero API keys" del enunciado apunta al **server**: la
tool no debe traer su propio modelo. Se extendió el mismo criterio al
cliente de prueba a propósito, para no ensuciar la PoC con secretos ni
depender de una cuenta de API externa solo para poder ejecutar el test. El
costo es que el "resumen" y el "rating" que genera el stub son
simplones (extracción de oraciones, conteo de keywords) — pero el punto de
la PoC es demostrar el protocolo de Sampling, no la calidad de generación.
Si se quisiera ver generación real, `test_client.py` es el único lugar que
habría que tocar: cambiar `sampling_callback` para llamar a un LLM de
verdad (con su propia key) no requiere tocar `server.py` en absoluto — la
separación de responsabilidades del protocolo se sostiene.

### Modos de aprobación (`SAMPLING_MODE`)

```bash
# Interactivo (default): pregunta y/n por consola en cada solicitud.
# Este es el punto donde se observa el human-in-the-loop real.
uv run test_client.py

# Aprueba todo automáticamente (para pruebas rápidas / no interactivas)
SAMPLING_MODE=auto-approve uv run test_client.py

# Rechaza todo automáticamente (para probar el manejo de error sin crash)
SAMPLING_MODE=auto-reject uv run test_client.py

# Con un texto propio en vez del ejemplo hardcodeado
uv run test_client.py "texto de la descripción de trabajo que quiero evaluar"
```

En Windows/PowerShell, seteá la variable en un paso separado:

```powershell
$env:SAMPLING_MODE = "auto-approve"; uv run test_client.py
```

## Cómo probar

```bash
cd poc4-mcp-sampling
uv sync
uv run test_client.py
```

Vas a ver, en orden:

1. El client conecta al server vía stdio y hace `initialize`.
2. El client invoca la tool `summarize_and_rate`.
3. El server loggea a stderr (`Paso 1/2: solicitando resumen...`) y emite
   la primera solicitud `sampling/createMessage`.
4. **Acá está el punto human-in-the-loop**: el client imprime la solicitud
   completa y (en modo interactivo) espera tu aprobación por consola antes
   de devolver nada al server.
5. Se repite para el paso 2 (rating), usando el resumen del paso 1 como
   input.
6. El resultado combinado (resumen + rating) se imprime como JSON.

Si aprobás y después rechazás la segunda solicitud (o usás
`SAMPLING_MODE=auto-reject` desde el principio), vas a ver el error
legible que devuelve la tool en vez de un crash.

## Con MCP Inspector (alternativa exploratoria)

```bash
npx @modelcontextprotocol/inspector uv run server.py
```

El Inspector abre una UI web donde se puede invocar `summarize_and_rate`
manualmente y ver/aprobar cada solicitud de sampling desde el navegador.
Útil para inspeccionar el JSON de la solicitud con más detalle que en la
consola, pero para el flujo automatizado de esta PoC se usó
`test_client.py`.

## Qué aprendí

- **Sampling invierte quién es "el que llama"**: en Tools/Resources/Prompts
  el server solo responde; acá el server *inicia* una solicitud hacia el
  client y espera. Es la primera vez en la serie que el server tiene que
  modelar "puedo ser rechazado" como un flujo normal, no una excepción.
- **El primitivo existe para que el server no cargue modelo propio.** Eso
  habilita servers agénticos ("piensan" pero no pagan ni operan
  infraestructura de LLM) que se apoyan completamente en lo que el host ya
  tiene disponible — importante para servers distribuidos a terceros, que
  no quieren (ni deberían) pedir una API key de LLM a cada usuario.
- **El human-in-the-loop es un control de seguridad, no un detalle de UX.**
  Cada `sampling/createMessage` es una oportunidad para que el usuario vea
  exactamente qué texto se le va a mandar "a pensar" al modelo del host
  antes de que ocurra — relevante si el texto tiene datos sensibles o si el
  server es de un tercero no confiable.
- **La madurez del tooling es real, no anecdótica.** Ni Claude CLI ni
  Claude Desktop soportan Sampling hoy. Probar este primitivo requirió
  escribir el lado del client a mano con el SDK — algo que no hizo falta en
  ninguna de las PoC 1-3. Es información útil per se: cualquier server que
  dependa de Sampling hoy asume un cliente no trivial del lado de quien lo
  consuma.

## Siguiente en la serie

**PoC 5** — HTTP/SSE Server con Auth deployado: migrar de stdio a
transporte remoto con autenticación, cerrando la serie.
