# HBL ULTRA 5 — Guía operativa rápida

## Lo que ve el cliente

### Dashboard
- saldo base y equivalencia local;
- plan activo;
- progreso de canciones del día;
- segundos exigidos por pista;
- renovación diaria según zona horaria protegida;
- recarga, retiro, referidos, regalos y ruleta;
- banners musicales locales optimizados.

### Retirar
El formulario solicita el monto en la moneda asociada al país del usuario. Antes de confirmar muestra:
- equivalente en moneda base;
- comisión estimada;
- mínimo efectivo;
- moneda real del método;
- monto neto aproximado.

Al confirmar, el servidor vuelve a validar todo y congela tasas/montos en el registro del retiro.

### Destinos de retiro
El formulario cambia label, placeholder y ayuda según el método configurado. Se validan formatos de banco/IBAN, Binance ID, TRC20, BEP20/EVM, correo y teléfono.

### Música diaria
Cada canción requiere el mayor valor entre:
- mínimo global (`Configuración → segundos efectivos`), inicialmente 10;
- mínimo específico de la pista.

La recompensa se acredita solamente cuando todas las tareas del día están completas.

## Lo que ve el administrador

### Métodos de retiro
`/control/metodos-retiro/`

Configura país, moneda de pago, red, tipo de identificador, placeholder, ayuda, titular, mínimo, máximo, porcentaje/fijo y estado.

### Monedas
`/control/monedas/`

Cada tasa significa: `1 unidad de esa moneda = X unidades de moneda base`.

Ejemplo con NIO como base:
- USD: 36.62
- NIO: 1
- USDT: tasa administrada según la política operativa.

No uses tasas inventadas en producción.

### Configuración
`/control/configuracion/`

Valores clave iniciales:
- depósito mínimo: US$100;
- retiro mínimo: 500 base;
- comisión referido: 10% primera recarga aprobada únicamente;
- 5 referidos calificados por upgrade;
- ruleta requiere referido calificado: sí;
- escucha: 10 segundos.

### Recargas y retiros
Una recarga rechazada requiere motivo. Un retiro pagado requiere referencia de pago; un retiro rechazado requiere motivo. Las acciones quedan auditadas.

## Corte diario

Las playlists no se "resetean" borrando historial. Se crea un nuevo conjunto de `DailyAssignment` por fecha local. El conjunto anterior queda histórico y no es utilizable en la fecha nueva.

La zona horaria detectada no puede alternarse libremente para generar días artificiales. Una cuenta ya configurada mantiene su zona de recompensa; el primer cambio automático desde UTC solo se permite antes de completar tareas/recompensas.

## Seguridad práctica

- CSRF activo en formularios y APIs de sesión.
- cookies seguras en producción.
- HSTS opcional/activado cuando corresponde.
- protección contra open redirect en login.
- limitación básica de intentos de login por identidad+IP.
- saldo modificado mediante ledger/servicios atómicos.
- retiro reserva saldo inmediatamente.
- TXID manual único.
- Binance se valida del lado servidor antes de acreditar.
- webhooks Binance: firma + ventana temporal + consulta de orden.
- cambios de moneda base bloqueados después de actividad financiera.
- archivos de comprobante limitados a imagen y 5 MB.
- audios administrativos limitados a formatos permitidos y 25 MB.
