# Requerimiento: landing Swip, home bancario y bienvenida de Cardy

Estado: **borrador para revisión** · Fecha: 2026-09-30 · Pista: Dev B (G5 Web app), con un endpoint nuevo de lectura del lado de Dev A.

Este documento es la entrada para `/wave-run`. El `spec-writer` lo convierte en `docs/specs/<slug>.md`; las preguntas abiertas del final se responden en esa etapa.

## Contexto actual

- `/` ([frontend/src/routes/index.tsx](../../frontend/src/routes/index.tsx)) es una landing de relleno: título, subtítulo y botón a `/login`.
- Después del login, [login.tsx](../../frontend/src/routes/login.tsx) navega directo a `/chat`. No existe una pantalla bancaria intermedia.
- El backend **no expone endpoints REST de lectura** para tarjetas, saldo o movimientos. Esos datos solo llegan por las herramientas del chat (`cards.service.list_cards`, `get_card_details`, `transactions.service.search`).
- El chat abre vacío: Cardy solo saluda cuando el cliente escribe un saludo (plantillas fijas `greeting` / `greeting_named` en `backend/app/domains/conversation/templates.py`).

## R1 · Landing principal desde Claude Design

**Fuente:** proyecto de Claude Design, archivo `SwipLanding v2.dc.html`
(`https://claude.ai/design/p/1a8e704d-3387-4cbb-bd2a-f8926a9b67f0?file=SwipLanding+v2.dc.html`).
El agente implementador no puede abrir este link: hay que exportar el HTML y guardarlo en `docs/design/landing/SwipLanding-v2.html` (con sus assets) antes de empezar.

**Qué se construye**
1. La landing reemplaza el contenido de `frontend/src/routes/index.tsx`. Es React + Tailwind, sin iframe y sin HTML estático aparte.
2. Se divide en secciones en `frontend/src/components/landing/` (por ejemplo `Hero`, `Features`, `HowItWorks`, `CardyShowcase`, `Footer`); la ruta solo las compone.
3. Colores y tipografías usan los tokens de marca de `frontend/src/index.css` (`bg-bg`, `text-cyan`, `text-gold`, `text-alert`, `font-heading`, `font-sans`) y las reglas de [`docs/brand.md`](../brand.md). Si el diseño trae un color o fuente fuera de la marca, se mapea al token más cercano y se anota en el PR.
4. Todo texto visible va al diccionario i18n (`landing.*` en `es.json` y `pt.json`). El toggle ES | PT funciona en la landing.
5. Se reutilizan los componentes de `components/ui/` (shadcn) y, si encaja, `StarryBackground`.
6. El botón **"Iniciar sesión"** (y cualquier CTA equivalente) es un `<Link to="/login">`.
7. Responsive: sin scroll horizontal a 360 px de ancho; accesible (contraste AA, `alt` en imágenes, foco visible).

**Hecho cuando**
- `/` se ve como el diseño en escritorio y móvil, en ES y en PT.
- "Iniciar sesión" lleva a `/login`.
- `npm run lint` y `npm run typecheck` pasan.

## R2 · Home bancario (después del login)

Nueva ruta protegida **`/home`**. El flujo queda: `/` → "Iniciar sesión" → `/login` → **`/home`** → "Hablar con Cardy".

### Contenido

| Sección | Qué muestra | Origen del dato |
|---|---|---|
| Encabezado | Saludo con el nombre del cliente, toggle ES/PT, cerrar sesión | `GET /api/v1/auth/me` |
| **Mis tarjetas** | Una tarjeta visual por producto: tipo (crédito/débito), `•••• 1234`, estado (Activa, Bloqueada, Suspendida, Cerrada, Bloqueo temporal) | `cards.list_cards` |
| **Mi saldo** | Crédito: cupo total, saldo usado y **cupo disponible**, con una barra de uso. Débito: saldo disponible si el dato existe. Fecha de vencimiento de la tarjeta | `cards.get_card_details` |
| **Historial de transacciones** | Últimos movimientos (fecha, comercio, monto, estado: aprobada, rechazada, pendiente, reversada), filtro por tarjeta y por rango de fechas, paginación o "ver más" | `transactions.service.search` |
| **Hablar con Cardy** | Botón flotante fijo que abre el chat como panel lateral (en móvil, pantalla completa) | Componentes existentes de `/chat` |

### Adicionales sugeridos (típicos de un home bancario)

- **Alertas destacadas:** tarjeta bloqueada o con días de mora, movimiento rechazado reciente. Cada alerta tiene un botón "Preguntarle a Cardy" que abre el chat con el tema ya elegido.
- **Acciones rápidas** (bloquear/desbloquear tarjeta, reponer tarjeta, reclamar un cargo, "¿por qué me rechazaron?"): **abren Cardy con esa intención**. No ejecutan la acción directamente: toda escritura sigue pasando por el token de confirmación y la verificación posterior del flujo existente.
- Detalle del movimiento al tocarlo, con el botón "Reclamar este cargo" (abre Cardy).
- Estados vacíos, de carga (skeletons) y de error, todos traducidos.
- Mostrar/ocultar montos (ícono de ojo), recordado solo en el navegador.

### Backend nuevo (solo lectura)

Endpoints bajo el router de cliente (rol `customer` + CSRF), cada uno con su test R1:
- `GET /api/v1/me/cards` → lista de `CardSummary`.
- `GET /api/v1/me/cards/{card_id}` → `CardDetails`; `404` si la tarjeta no es del cliente de la sesión.
- `GET /api/v1/me/transactions?card_id=&date_from=&date_to=&cursor=` → página de `TxView`.

Después: `make client` para regenerar `frontend/src/client/`.

### Reglas que aplican

- **R1:** `customer_id` sale solo de la sesión; ningún endpoint lo recibe por parámetro.
- **R4:** montos, fechas y máscaras se formatean en código, con la moneda y la zona horaria del país del cliente. Nunca se muestra el número completo de la tarjeta.
- Estas lecturas no pasan por el LLM ni por Langfuse.

### Hecho cuando

- Tras el login, el cliente llega a `/home` y ve sus tarjetas, su saldo y sus movimientos reales del dataset, en ES y en PT.
- Otro cliente no puede leer esas tarjetas ni esos movimientos (test R1 en los tres endpoints).
- "Hablar con Cardy" abre el chat sin salir de `/home`, y una conversación allí funciona igual que en `/chat`.
- `/chat` sigue funcionando como página completa (la usan los e2e y el simulador).
- Entrar a `/home` sin sesión redirige a `/login`.

## R3 · Mensaje de bienvenida cálido y variado

**Qué se construye**
1. Al **crear una conversación**, Cardy publica primero un mensaje de bienvenida, sin que el cliente escriba nada.
2. El mensaje sale de un **banco de plantillas en código** (≥ 8 por idioma, ES y PT), con el nombre del cliente cuando existe y, opcionalmente, un matiz según la hora local (buenos días/tardes/noches).
3. **"Siempre diferente"** significa: nunca es igual a la bienvenida de la conversación anterior del mismo cliente. Se guarda el índice de la última usada por cliente (Redis o `app.conversations`) y se elige al azar entre las demás.
4. El tono sigue la voz de Cardy en [`docs/brand.md`](../brand.md): cálido, breve (1–2 frases) y termina invitando a contar qué necesita.
5. La bienvenida se guarda como el primer mensaje del bot, para que el panel de staff y la trazabilidad la muestren.
6. Aplica tanto en `/chat` como en el panel de Cardy de `/home`.

**Por qué plantillas y no LLM:** no tiene costo ni latencia, se puede probar sin modelo y no manda datos al proveedor (el nombre del cliente sería PII).

**Hecho cuando**
- Cada chat nuevo empieza con una bienvenida en el idioma de la UI.
- Dos chats seguidos del mismo cliente nunca muestran la misma bienvenida (test).
- Un test ES y uno PT con LLM falso confirman que la bienvenida no rompe el primer turno del cliente.

## Fuera de alcance

- Registro de clientes nuevos o recuperación de contraseña.
- Ejecutar escrituras (bloqueos, reposiciones, reclamos) desde botones del home sin pasar por Cardy.
- Cambios en `eval/scenarios/heldout/`.

## Preguntas abiertas (para el spec)

1. **Ruta del home:** ¿`/home` o `/inicio`? ¿Después del login se va siempre a `/home`, o se conserva la opción de ir directo a `/chat`?
2. **Chat en `/home`:** ¿panel lateral (recomendado) o modal centrado?
3. **Saldo de débito:** el dataset no trae un saldo de cuenta de débito claro. ¿Se muestra solo el estado de la tarjeta de débito, o se busca otra fuente?
4. **Bienvenida:** ¿confirmamos plantillas en código? La alternativa es generarla con el LLM, con más variedad pero más costo, más latencia y un riesgo de PII.
5. **Diseño de Claude Design:** ¿quién exporta `SwipLanding v2` al repo, y hay diseño para el home bancario o se construye con la marca actual?
