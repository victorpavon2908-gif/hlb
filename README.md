# HBL ULTRA 5.1 FINAL

Plataforma Django/PWA de membresías y recompensas por tareas de escucha, con **HBL Control** como panel operativo propio.

## Reglas incluidas por defecto

- Moneda contable base: **NIO (C$)**.
- Tasa inicial de referencia: **US$1 = C$36.62**; las tasas operativas se administran en `/control/monedas/`.
- Recarga mínima global: **US$100** o su equivalente en la moneda del método.
- Retiro mínimo global: **500 unidades de la moneda base**; el cliente lo ve convertido a su moneda local.
- Plan inicial HBL 100: US$100, 30 días, 3 canciones diarias, recompensa diaria C$122.
- Escucha: mínimo global **10 segundos efectivos por canción**. Una canción puede exigir un mínimo mayor; nunca menor al global.
- Recompensa diaria: se acredita **una sola vez y únicamente después de completar toda la playlist del día**.
- Referidos: **10% solo sobre la primera recarga aprobada** del referido.
- Referido calificado: referido con al menos una recarga aprobada.
- Upgrade gratis: cada bloque de 5 referidos calificados habilita una subida al siguiente plan; los mismos 5 no se reutilizan infinitamente.
- Ruleta: promoción gratuita; puede exigir membresía y referidos calificados. El resultado se decide en servidor.

## Registro internacional

El catálogo contiene **249 países/territorios**. Se puede registrar una cuenta con:

- correo solamente;
- teléfono solamente;
- correo y teléfono.

Al menos uno es obligatorio. El país asigna la moneda local preferida. El teléfono se normaliza a formato internacional cuando existe prefijo disponible. El inicio de sesión acepta usuario interno, correo o teléfono.

La zona horaria de recompensa se detecta en el dispositivo durante el alta/primer uso y luego queda protegida contra cambios automáticos repetidos para impedir abusos del corte diario.

## Retiro multimoneda

HBL separa tres conceptos:

1. **Moneda base:** contabilidad interna.
2. **Moneda local del país del usuario:** donde escribe el retiro cuando el método es local.
3. **Moneda de pago del método:** moneda real que recibe (p. ej. MXN, NIO, USD, USDT).

El usuario escribe el monto en la moneda asociada a su país; la moneda de visualización del perfil no altera esta regla. El servidor lo convierte a la moneda base para validar saldo, mínimo, máximo y comisión; después congela el monto neto en la moneda del método. El historial conserva tasas y monedas usadas en el momento de la solicitud.

Cada método de retiro define desde `/control/metodos-retiro/`:

- país o disponibilidad global;
- moneda local del usuario o moneda fija;
- red/proveedor;
- tipo de identificador y validación (banco/IBAN, Binance ID, TRC20, BEP20/EVM, correo, teléfono o personalizado);
- placeholder e instrucciones visibles;
- titular obligatorio sí/no;
- mínimo y máximo en moneda base;
- comisión porcentual y fija;
- estado y orden.

El mínimo efectivo es el mayor entre el mínimo global y el mínimo propio del método.

## Renovación diaria de música

Las tareas se agrupan por la **fecha local protegida de la cuenta**. Al comenzar un nuevo día:

- las tareas del día anterior dejan de ser válidas;
- una sesión de escucha del día anterior no puede completar una tarea nueva;
- al abrir el dashboard se genera la playlist del nuevo día bajo demanda;
- si el panel queda abierto, JavaScript programa una recarga justo después de medianoche local;
- la recompensa del día usa una referencia única por membresía+fecha, evitando doble acreditación.

No se necesita un cron para crear playlists diarias; se crean de forma idempotente al entrar.

## HBL Control

Panel: `/control/`

- `/control/usuarios/` — cuentas, bloqueo/desbloqueo, saldo auditado, membresías.
- `/control/planes/` — planes/niveles.
- `/control/canciones/` — catálogo, archivos y asignación por plan.
- `/control/monedas/` — tasas contra la moneda base.
- `/control/configuracion/` — mínimos globales, referidos, escucha, ruleta, mantenimiento.
- `/control/metodos-pago/` — depósitos/recargas.
- `/control/recargas/` — aprobación/rechazo.
- `/control/metodos-retiro/` — métodos, validaciones, mínimos, máximos y comisiones.
- `/control/retiros/` — pago/rechazo con referencia/motivo obligatorio.
- `/control/referidos/` — niveles y nómina semanal.
- `/control/ruleta/` — reglas y premios.
- `/control/regalos/` — códigos, valor, fechas y límites.
- `/control/auditoria/` — trazabilidad administrativa.

Los formularios operativos incluyen etiquetas de obligatorio/opcional, placeholders, ayudas, validación servidor y mensajes de error por campo.

## Moneda base

La moneda base puede elegirse durante la configuración inicial. **Después de existir actividad financiera, HBL bloquea su cambio**, porque reinterpretar saldos e historiales sería contablemente inseguro. Para operar otros países después de iniciar, mantén la base y actualiza `/control/monedas/`.

Antes de la primera operación, si se cambia la base, HBL rebasa tasas y convierte los importes configurables del catálogo.

## Binance Pay

La integración queda preparada para:

- Create Order v3;
- retorno de checkout;
- webhook firmado;
- consulta de orden antes de acreditar;
- validación de `merchantTradeNo`, `prepayId`, moneda, monto y estado;
- rechazo de webhooks con timestamp fuera de la ventana configurada.

Variables:

```env
BINANCE_PAY_ENABLED=True
BINANCE_PAY_API_KEY=...
BINANCE_PAY_SECRET_KEY=...
BINANCE_PAY_CURRENCY=USDT
BINANCE_PAY_SUPPORT_CURRENCY=USDT
BINANCE_WEBHOOK_MAX_AGE_SECONDS=300
```

Webhook de producción:

```text
https://TU-DOMINIO/pagos/binance/webhook/
```

Nunca escribas claves API, frases semilla o claves privadas en campos visibles del panel.

## Instalación Windows

```powershell
cd "C:\ruta\HBL_ULTRA_5_FINAL"
python -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python manage.py migrate
python manage.py seed_hbl
python manage.py createsuperuser
python manage.py check
python manage.py test
python manage.py runserver
```

Abrir:

```text
http://127.0.0.1:8000/
http://127.0.0.1:8000/control/
http://127.0.0.1:8000/admin/
```

## Producción

No publiques el `.env`. Usa PostgreSQL, HTTPS, storage persistente para media y secretos reales en variables de entorno. Con `DEBUG=False`, HBL rechaza el arranque si `SECRET_KEY` es insegura o `ALLOWED_HOSTS` está vacío.

Ejecuta antes del despliegue:

```bash
python manage.py migrate --noinput
python manage.py collectstatic --noinput
python manage.py check --deploy
python manage.py test
```

Para sincronización adicional de órdenes Binance pendientes:

```bash
python manage.py sync_binance_pay --limit 100
```

Para nómina de referidos, únicamente cuando la regla esté habilitada/validada por administración:

```bash
python manage.py run_referral_payroll --pay
```

## Nota de operación

Los audios demo son únicamente para prueba. Antes de abrir la plataforma al público sustituye el contenido por música propia o debidamente licenciada y revisa requisitos legales, de consumo, privacidad, pagos, promociones e impuestos de los países donde operarás.
