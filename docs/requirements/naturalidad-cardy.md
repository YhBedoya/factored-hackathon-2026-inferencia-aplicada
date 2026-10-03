# Requerimiento: naturalidad y memoria de conversación de Cardy

Estado: **borrador para revisión** · Fecha: 2026-10-02 · Card propia (no es fila de `07`), planeada para **D7** · Pista: conversación (backend) con un cambio pequeño en el chat web.

Este documento es la entrada para `/wave-run naturalidad-cardy`. El `spec-writer` lo convierte en `docs/specs/naturalidad-cardy.md`; las preguntas abiertas del final se responden en esa etapa.

## Objetivo

Cardy debe sonar más cercana y natural, y responder con lógica respecto a **lo que ya se habló**: si el cliente acaba de consultar una tarjeta, "quiero bloquearla" se refiere a esa; si la tarjeta ya está bloqueada, Cardy lo dice y ofrece el siguiente paso útil en lugar de repetir preguntas o mostrar opciones que no aplican.

## Contexto actual

- **El NLU solo ve el mensaje actual** y la pregunta pendiente ([understand.py](../../backend/app/domains/conversation/nodes/understand.py), `_build_user_message`). No recibe historial, así que no puede resolver "bloquearla" o "esa tarjeta".
- **El selector de tarjeta repite la lista en el texto y en los botones** (`ask_which_card_text` + `card_picker_event`).
- **Bloqueo pregunta temporal/permanente antes de revisar el estado** ([card_block.py](../../backend/app/domains/conversation/flows/card_block.py), `_select_card` → `_ask_block_kind`); el "ya está bloqueada" (`already_in_state`) solo llega después.
- **Reposición acepta tarjetas activas** ([replacement.py](../../backend/app/domains/conversation/flows/replacement.py)) y el selector muestra todas las tarjetas.
- **"Quiero una tarjeta nueva" cae en `replacement_request`** y termina preguntando qué tarjeta reponer.
- **Casi todo el texto son plantillas fijas** en [templates.py](../../backend/app/domains/conversation/templates.py) (una sola versión por mensaje). Los rechazos de alcance usan `abstain_fallback` ("Por aquí no puedo gestionar {topic_label}…"), que suena seco.
- Tras una acción verificada (`action_done`) Cardy no pregunta si hay algo más. Ya existen `anything_else`, `farewell` y el evento `conversation_closed`.

## R1 · Memoria de conversación (historial + resumen)

1. Cada turno arma un **contexto de conversación** con:
   - los **últimos 6 mensajes** de la conversación, contando cliente y Cardy juntos (≈ 3 intercambios);
   - cuando la conversación tiene más de 6 mensajes, un **resumen** de todos los anteriores.
2. El resumen lo genera una **llamada LLM** a partir del texto **enmascarado** (`content_masked`, R5). Se actualiza solo cuando hay mensajes nuevos que salen de la ventana de 6, no en cada turno.
3. El contexto se usa en dos lugares:
   - **NLU (`understand`)**: para resolver referencias ("bloquearla", "esa", "la otra", "sí, esa") a la tarjeta o al movimiento del que se viene hablando.
   - **Redacción (`compose`)**: para que la respuesta sea coherente con lo dicho antes (no repetir datos ya dados, no volver a saludar, retomar el tema).
4. Las acciones con efecto siguen usando plantillas, tokens de confirmación y lectura posterior. El historial **no** cambia quién decide qué herramienta se llama.
5. El historial y el resumen se leen solo de la conversación de la sesión (R1, R13). Al LLM y a Langfuse solo llega texto tokenizado (R5). Los nodos que leen historial con salida de herramientas no tienen herramientas de escritura (R6).

**Hecho cuando**
- En una conversación de más de 6 mensajes, el NLU y `compose` reciben los últimos 6 y un resumen de los anteriores; con 6 o menos, solo los mensajes.
- Ningún prompt (NLU, resumen, `compose`) contiene PII sin tokenizar (test R5).

## R2 · Referencia a la tarjeta en foco (ejemplo 2)

1. Si en el contexto hay **una sola tarjeta en foco** (la última consultada o elegida) y el cliente se refiere a ella sin nombrarla, Cardy la usa directamente. El paso de confirmación de la acción ya muestra la `•••• 1234`.
2. Si se habló de **varias tarjetas** y la referencia es ambigua, Cardy pregunta con botones.

**Ejemplo:** consulta el estado de Crédito •••• 5284 (Bloqueada) → "Quiero bloquearla" → Cardy **no** pregunta cuál tarjeta: responde que esa tarjeta ya está bloqueada y ofrece reposición (ver R4).

**Hecho cuando**
- El caso del ejemplo 2 responde "ya está bloqueada" + oferta de reposición, sin selector de tarjeta, en ES y en PT.

## R3 · Selector sin lista duplicada (ejemplo 1)

1. Cuando Cardy pide elegir (tarjeta o movimiento), el texto es **solo la pregunta**: "¿Sobre cuál tarjeta quieres saber?". Las opciones van **solo en los botones**.
2. Aplica a todos los selectores: tarjetas y movimientos.

**Hecho cuando**
- Ningún mensaje de selección repite en el texto las opciones que muestran los botones.

## R4 · Responder según el estado de la tarjeta (ejemplos 2, 3 y 4)

1. **Bloqueo:** el estado de la tarjeta se revisa **antes** de preguntar temporal/permanente. Si ya está bloqueada, Cardy lo dice de una vez y no muestra las opciones de bloqueo (ejemplo 3).
2. **Después de informar el estado** de una tarjeta no activa (consulta de estado o intento de bloqueo), Cardy ofrece el siguiente paso según el estado:

| Estado | Qué ofrece Cardy |
|---|---|
| Bloqueada (permanente) | Reposición |
| Bloqueo temporal | Desbloquearla |
| Suspendida / Cerrada | Hablar con una persona |

   Siempre cierra con "¿o te ayudo con algo más?". Ejemplo (estado 4): "…tienes COP $23.494.545 disponible de un límite de COP $26.917.985. Como está bloqueada, ¿quieres que pidamos una reposición o te ayudo con algo más?"

**Hecho cuando**
- Ejemplos 2, 3 y 4 producen la oferta de la tabla, en ES y en PT, sin preguntar temporal/permanente cuando la tarjeta ya está bloqueada.

## R5 · Reposición solo para tarjetas bloqueadas (ejemplos 5 y 7)

1. El selector de reposición **solo muestra tarjetas bloqueadas**.
2. **Una sola bloqueada** → Cardy va directo a confirmar la reposición de esa tarjeta (dirección y confirmación como hoy), sin selector.
3. **Varias bloqueadas** → botones solo con las bloqueadas.
4. **Ninguna bloqueada**, o el cliente nombra una tarjeta activa → Cardy explica que para reponerla primero hay que bloquearla o reportarla como perdida o robada, y **ofrece bloquearla**.
5. La regla vive en `policies/` (p. ej. estados elegibles para reposición), no en el prompt.

**Hecho cuando**
- Ejemplo 5 (una bloqueada) llega a la confirmación sin selector.
- Ejemplo 7 (elige una activa) no pide dirección: explica y ofrece bloqueo.

## R6 · "Quiero una tarjeta nueva" no es reposición (ejemplo 8)

1. Pedir un **producto nuevo** (tarjeta adicional, "solicitar una nueva tarjeta") se distingue de reponer una existente.
2. Cardy responde con amabilidad que **por este chat no se pueden solicitar tarjetas nuevas** y pregunta en qué más puede ayudar. **Sin** botón de "Hablar con una persona".

**Hecho cuando**
- "Quiero solicitar una nueva tarjeta" (ES) y su equivalente PT no entran al flujo de reposición.

## R7 · Cierre proactivo tras una acción (ejemplo 6)

1. Después de una acción verificada (`action_done` / `action_done_noref`), Cardy pregunta: "¿Te ayudo con algo más o damos por terminada la conversación?".
2. Se muestran dos botones: **"Algo más"** y **"Terminar"**. "Algo más" responde con `ask_what_else`; "Terminar" responde con la despedida y cierra la conversación (`conversation_closed`), como hace hoy `anything_else`.
3. El texto del mensaje "listo" sigue en pasado solo después de la lectura posterior (regla de `brand.md`).

**Hecho cuando**
- Tras bloquear, desbloquear o reponer, aparece la pregunta con los dos botones, y "Terminar" cierra la conversación.

## R8 · Fuera de alcance, cálido y cercano (ejemplos 9 y 10)

1. Cardy habla en **primera persona** ("no lo puedo gestionar"), pide disculpas, explica que en Swip solo se gestionan tarjetas, agradece la comprensión y pregunta en qué puede ayudar con sus tarjetas.
2. Se **mantienen** los botones actuales (acción cercana y "Hablar con una persona").
3. Aplica a productos bancarios (cuentas, préstamos, transferencias…) y a temas ajenos (p. ej. "¿quién es el presidente de Colombia?"). Cardy no responde la pregunta ajena.

**Ejemplo ES:** "Disculpa, eso no lo puedo gestionar por aquí: en Swip solo manejamos tarjetas. Gracias por entenderlo. ¿Te ayudo con algo de tus tarjetas?"

**Hecho cuando**
- Ejemplos 9 y 10 responden con este tono y conservan los botones, en ES y en PT.

## R9 · Tono más cercano en las plantillas

1. Se **reescriben** las plantillas de cara al cliente (aclaraciones, confirmaciones, "listo", fuera de alcance, errores) para que suenen más cálidas, siguiendo `docs/brand.md` (tú neutro, `você`, sin emojis, máximo ~3 oraciones, una pregunta a la vez).
2. Cada plantilla tiene **varias variantes** y se elige una al azar, como la bienvenida. Montos, fechas y máscaras siguen formateados en código; las variantes no llevan dígitos propios.
3. Las plantillas de seguridad (inyección, no autorizado, herramienta caída) pueden ganar calidez pero conservan su precisión.
4. El texto PT queda pendiente de revisión por un hablante nativo, como el resto.

**Hecho cuando**
- Las plantillas reescritas tienen al menos N variantes por idioma (N se fija en el spec) y pasan los tests existentes de formato (sin dígitos, placeholders completos).

## Reglas que no cambian

- `customer_id` solo sale de la sesión (R1). El historial no puede introducir otro cliente ni otra tarjeta ajena.
- Toda escritura sigue con token de confirmación y lectura posterior (R2/R3 de `06`).
- Montos, fechas y máscaras los formatea el código (R4); el resumen y el historial no son fuente de cifras para la respuesta.
- Al LLM y a Langfuse solo va texto tokenizado (R5). La política vive en `policies/*.yaml` (R8).
- La llamada de resumen fija modelo, versión de prompt y temperatura, y queda trazada (R7). Sus reintentos están acotados (R11).
- `eval/scenarios/heldout/` no se toca. Si escenarios `dev` dependen de textos viejos, se actualizan en esta card.
- Tests mínimos: los de las reglas de seguridad tocadas (R1, R5, R6), los "Hecho cuando" de arriba y un happy path ES + PT por flujo, siempre con LLM falso.

## Preguntas abiertas (para el spec)

1. ¿Dónde se guarda el resumen (estado del grafo en el checkpointer, columna en `conversations`, o tabla aparte) y con qué modelo se genera (¿Haiku 4.5?)?
2. ¿Qué es exactamente la "tarjeta en foco": se guarda como dato estructurado del estado (`selected_card_id` persistente entre turnos) además del historial en texto?
3. ¿El NLU necesita un intent nuevo para "tarjeta nueva" (p. ej. `new_card_request` en `scope.yaml`) o se trata como tema fuera de alcance?
4. ¿Cuántas variantes por plantilla (N) y qué plantillas entran en R9 (todas o una lista)?
5. ¿La versión `baseline` del grafo (sin LLM) también recibe los cambios de R3–R8, para que la comparación de eval siga siendo justa?
6. Impacto en latencia y costo de la llamada de resumen: ¿hay un límite por turno?
7. Si la llamada de resumen falla, ¿el turno sigue solo con los últimos 6 mensajes (sin resumen) o pasa a handoff como otras fallas LLM?
