# Requerimiento: personalidad de Cardy (propositiva, cercana y amable)

Estado: **borrador para revisión** · Fecha: 2026-10-02 · Card propia (no es fila de `07`), día por definir · Pista: conversación (backend) con un cambio pequeño en el chat web y en `docs/brand.md`.

Este documento es la entrada para `/wave-run personalidad-cardy`. El `spec-writer` lo convierte en `docs/specs/personalidad-cardy.md`; las preguntas abiertas del final se responden en esa etapa. Parte de lo que dejó [`naturalidad-cardy`](naturalidad-cardy.md) y corrige lo que, en uso real, todavía suena tosco o ilógico.

## Objetivo

Cardy debe sentirse como una persona de soporte **propositiva, cercana y amable**, no como un formulario:

- **Propositiva:** cuando termina algo, sugiere el siguiente paso que tiene sentido según lo que acaba de pasar, sin esperar a que el cliente adivine qué más puede hacer.
- **Cercana:** recuerda de qué se viene hablando, no se vuelve a presentar y entiende referencias como "la otra".
- **Amable:** pregunta con calidez ("¿Te puedo ayudar con algo adicional?"), nunca con fórmulas de trámite ("¿…o damos por terminada la conversación?").

Los límites de `docs/brand.md` siguen igual: sin emojis, tú neutro / `você`, unas tres oraciones por turno, una pregunta a la vez, no vende productos ni da asesoría financiera.

## Conversación que motiva el requerimiento

```
Cardy:   Hola, Luz. Qué gusto tenerte de vuelta en el universo Swip. Soy Cardy, dime qué necesitas con tu tarjeta y empezamos.
Cliente: Hola Cardy
Cardy:   Hola, Luz. Soy Cardy, de Swip. ¿Qué necesitas hoy con tu tarjeta?          ← (A) se presenta otra vez
Cliente: Quisiera conocer el estado de mi tarjeta
Cardy:   ¿De cuál de tus tarjetas quieres información?
Cliente: 9653
Cardy:   Tu tarjeta Crédito •••• 9653 está Activa, vence el 31/12/2024 y tienes COP $134.106.226
         disponible de un límite de COP $138.059.134. ¿Necesitas algo más o damos por terminada
         la conversación?                                                              ← (B) cierre tosco + botones "Algo más"/"Terminar"
Cliente: Y la otra que estado tiene?
Cardy:   ¿Sobre cuál tarjeta quieres saber?                                            ← (C) la clienta solo tiene dos tarjetas
```

## Contexto actual

- **Cierre:** tras cada flujo terminado, `_closing_allowed` / `_closing_update` en [next_intent.py](../../backend/app/domains/conversation/nodes/next_intent.py) agregan `closing_question` ("¿Te ayudo con algo más o damos por terminada la conversación?" y variantes) más los botones `ui.quick_replies{slot: closing}` "Algo más"/"Terminar" (spec `naturalidad-cardy`, D24 y D29).
- **"La otra":** `NLUSlots.card_hint` solo admite `credit`, `debit`, `focus` y `last4:NNNN` ([schemas.py](../../backend/app/domains/conversation/schemas.py)). "La otra" no tiene valor, así que termina en el selector aunque solo haya dos tarjetas.
- **Saludo:** la plantilla `greeting` ("Hola. Soy Cardy, de Swip…") se usa igual aunque la bienvenida ya presentó a Cardy en la misma conversación. Los mensajes de bienvenida no entran al historial (D8 de `naturalidad-cardy`).
- **Personalidad en `brand.md`:** ya lista "Proactive, within limits" y "Warm", pero sin ejemplos de cierre ni de continuidad, y las plantillas de cierre no lo reflejan.

## R1 · Cierre propositivo según el contexto (ejemplo B)

1. Cuando un flujo termina (respuesta a una consulta, acción verificada, cancelación, oferta rechazada), Cardy **cierra con una sola pregunta amable que propone el siguiente paso útil** según lo que acaba de pasar, y deja abierta la puerta a otra cosa. Ejemplo tras consultar el estado de una tarjeta de crédito activa:
   > "…tienes COP $134.106.226 disponible de un límite de COP $138.059.134. ¿Quieres que revisemos tus últimos movimientos o te puedo ayudar con algo adicional?"
2. La sugerencia **solo ofrece servicios que Cardy ya resuelve** (consulta de estado, saldo a pagar, movimientos, explicación de rechazos, cargo no reconocido, bloqueo, desbloqueo, reposición, hablar con una persona).
3. La tabla "situación → sugerencia" vive en `policies/` (como `next_step_offer` de `card_select.yaml`), no en el prompt. Propuesta inicial, **a confirmar en el spec**:

| Acaba de pasar | Sugerencia |
|---|---|
| Estado de una tarjeta activa | Últimos movimientos; en crédito, también el saldo a pagar |
| Estado de una tarjeta no activa | Se mantiene la oferta por origen del bloqueo (`next_step_offer`) |
| Saldo a pagar | Últimos movimientos |
| Búsqueda o explicación de movimientos | Reportar un cargo que no reconozca |
| Explicación de un rechazo | La que ya ofrece la causa (p. ej. reposición); si no hay, genérica |
| Bloqueo verificado | Se mantiene la oferta de reposición |
| Desbloqueo, reposición, reclamo, cancelación, oferta rechazada | Genérica |

   **Genérica** = "¿Te puedo ayudar con algo adicional?" y variantes.
4. El texto **no** usa "damos por terminada la conversación" ni fórmulas equivalentes.
5. Los casos en que hoy se omite el cierre (D29: hay una pausa abierta, la cola no está vacía, handoff, smalltalk, fuera de alcance, etc.) se mantienen.
6. Si el cliente acepta la sugerencia ("sí", "dale", "los movimientos"), Cardy entra a ese flujo con la tarjeta en foco cuando aplica.

**Hecho cuando**
- El ejemplo B, en ES y en PT, termina con una sugerencia de la tabla y sin la palabra "terminada" / "encerrar a conversa".
- Aceptar la sugerencia tras el estado de una tarjeta abre los movimientos de esa misma tarjeta, sin selector.

## R2 · Sin botones "Algo más" / "Terminar" (ejemplo B)

1. Se eliminan los botones del cierre (`slot: closing`) en ES y PT. El cliente responde escribiendo.
2. Una respuesta de cierre ("no, gracias", "eso es todo", "não, obrigado") responde con la despedida (`farewell`) y cierra la conversación (`conversation_closed`), como hoy.
3. Un "sí" sin más detalle responde con `ask_what_else`. Un pedido nuevo se atiende como cualquier otro turno.
4. Los demás botones no cambian (selector de tarjeta, confirmar/cancelar, ofertas sí/no, "Hablar con una persona").

**Hecho cuando**
- Ningún turno emite `ui.quick_replies` con `slot: closing`, y el frontend ya no depende de ese slot.
- "No, gracias" tras el cierre termina la conversación, en ES y en PT.

## R3 · "La otra" tarjeta (ejemplo C)

1. Cuando hay una tarjeta en foco y el cliente pregunta por "la otra" ("y la otra", "a outra", "la de débito" si la de foco es la de crédito, etc.):
   - **El cliente tiene 2 tarjetas** → Cardy responde directamente sobre la que no está en foco, sin selector.
   - **Tiene 3 o más** → Cardy pregunta cuál, con botones **solo con las tarjetas que no están en foco**.
   - **No hay tarjeta en foco** → selector normal.
2. La resolución se hace en código contra `list_cards()` de la sesión (regla R1 de `06`), igual que `focus`. El NLU solo marca la referencia; nunca da un id de tarjeta.
3. Tras responder, la tarjeta en foco pasa a ser la nueva.

**Hecho cuando**
- El ejemplo C (clienta con dos tarjetas) responde el estado de la otra tarjeta sin selector, en ES y en PT.
- Con 3 tarjetas, el selector no incluye la tarjeta en foco.
- Un `selected_card_id` que no pertenece a la sesión nunca hace que aparezca una tarjeta ajena (test R1).

## R4 · No volver a presentarse (ejemplo A)

1. Si Cardy ya se presentó en la conversación (bienvenida o saludo anterior), un nuevo saludo del cliente se responde **sin repetir "Soy Cardy, de Swip"** y sin repetir la pregunta de la bienvenida con las mismas palabras. Ejemplo: "¡Hola de nuevo, Luz! Cuéntame, ¿en qué te ayudo con tus tarjetas?"
2. La presentación completa se mantiene en el primer mensaje de la conversación y cuando el cliente pregunta quién es.

**Hecho cuando**
- El ejemplo A, en ES y en PT, responde al "Hola Cardy" sin "Soy Cardy".

## R5 · Revisión de todas las plantillas de cara al cliente

1. Se revisan **todas** las plantillas de cara al cliente de [templates.py](../../backend/app/domains/conversation/templates.py) (no solo las de los ejemplos), buscando frases toscas, de trámite o repetitivas, y se reescriben con el tono de R1–R4 y de `docs/brand.md`.
2. Criterios: suena a una persona que ayuda; no usa fórmulas de cierre de trámite; no repite datos ni preguntas que ya se dijeron; mantiene una pregunta por turno y unas tres oraciones; no cambia la precisión de las plantillas de seguridad (inyección, no autorizado, herramienta caída, escalamiento).
3. Se mantiene el mínimo de 3 variantes por idioma en las plantillas que ya las tienen, sin dígitos propios y con los mismos placeholders.
4. El texto PT queda pendiente de revisión por un hablante nativo, como el resto.

**Hecho cuando**
- Ninguna plantilla contiene "damos por terminada" ni "encerrar a conversa" (o equivalente).
- El test de formato de variantes existente sigue pasando.

## R6 · Personalidad documentada en `brand.md`

1. La sección **Personality** de [`docs/brand.md`](../brand.md) agrega o precisa los rasgos **propositiva**, **cercana** y **amable**, cada uno con un ejemplo "así sí / así no" tomado de esta conversación. Por ejemplo:

| Rasgo | Así no | Así sí |
|---|---|---|
| Propositiva | "¿Necesitas algo más o damos por terminada la conversación?" | "¿Quieres que revisemos tus últimos movimientos o te puedo ayudar con algo adicional?" |
| Cercana | "¿Sobre cuál tarjeta quieres saber?" (tras hablar de una de dos) | "Tu tarjeta Débito •••• 1234 está Activa…" |
| Amable | "Hola, Luz. Soy Cardy, de Swip." (por segunda vez) | "¡Hola de nuevo, Luz! Cuéntame, ¿en qué te ayudo?" |

2. La tabla de tono (Voice and tone) agrega la fila **"Cierre de un flujo"**.
3. El bloque de persona del prompt de `compose` se alinea con estos rasgos (nueva versión del prompt). La lógica de qué se sugiere sigue en `policies/`, no en el prompt.

**Hecho cuando**
- `brand.md` tiene los tres rasgos con ejemplos y la fila de cierre, y el prompt de `compose` tiene una versión nueva que los refleja.

## Reglas que no cambian

- `customer_id` solo sale de la sesión (R1 de `06`). "La otra" se resuelve contra las tarjetas de la sesión; el historial no puede introducir una tarjeta ajena.
- Toda escritura sigue con token de confirmación y lectura posterior (R2/R3). Aceptar una sugerencia de bloqueo o reposición pasa por la confirmación de siempre.
- Montos, fechas y máscaras los formatea el código (R4). Las sugerencias no llevan cifras propias.
- Al LLM y a Langfuse solo va texto tokenizado (R5). Los nodos LLM que leen salida de herramientas no tienen herramientas de escritura (R6).
- La política (qué se sugiere, qué tarjeta es "la otra") vive en `policies/*.yaml` y en código, no en el prompt (R8).
- `eval/scenarios/heldout/` no se toca. Si escenarios `dev` dependen de los textos o botones viejos de cierre, se actualizan en esta card.
- Tests mínimos: los de las reglas de seguridad tocadas (R1, R5, R6), los "Hecho cuando" de arriba y un happy path ES + PT por flujo tocado, siempre con LLM falso.

## Preguntas abiertas (para el spec)

1. ¿Se aprueba la tabla de sugerencias de R1.3 tal cual, o cambia alguna fila?
2. ¿Dónde vive la tabla de sugerencias: una sección nueva de `card_select.yaml` o un archivo nuevo en `policies/`?
3. ¿La sugerencia se redacta en código (plantilla con variantes) o la redacta `compose` a partir de la clave que da la política?
4. ¿Cómo se marca "la otra" en el NLU: un valor nuevo de `card_hint` (p. ej. `other`) o un campo aparte?
5. ¿Cómo sabe el grafo que Cardy ya se presentó, si la bienvenida no entra al historial (D8): un flag en el estado del grafo o el número de mensajes de Cardy en la conversación?
6. Cuando el cliente acepta la sugerencia con un "sí", ¿se abre una pausa sí/no como las ofertas de R4 de `naturalidad-cardy`, o el "sí" se interpreta con el historial?
7. ¿El `baseline` (sin LLM) también recibe R1–R4, para que la comparación de eval siga siendo justa?
