# HBL · Depósitos y retiros USDT

HBL acepta únicamente USDT por estas dos redes:

- TRON / TRC20 (`usdttrc20` en NOWPayments).
- BNB Smart Chain / BEP20 (`usdtbsc` en NOWPayments).

Los depósitos se validan automáticamente con la API y los avisos IPN de NOWPayments. Los retiros permanecen pendientes para pago administrativo por la red detectada.

## Regla fija de 1 USDT

HBL aplica una regla sencilla y visible en ambas direcciones:

- **Depósito:** el usuario escribe cuánto desea acreditar. HBL genera la orden por ese monto **+ 1 USDT**. Si desea acreditar 10 USDT, paga 11 USDT y recibe 10 USDT de saldo equivalente.
- **Retiro:** el usuario escribe cuánto desea recibir. HBL suma el equivalente de **1 USDT** al total reservado/descontado. Si desea recibir 10 USDT y su saldo está expresado en USDT, se descuentan 11 USDT y se pagan 10 USDT.

La tarifa propia de la billetera o exchange desde donde se envía una transacción es externa a HBL. El usuario debe asegurarse de que la dirección de pago reciba el monto exacto indicado por HBL.

## Configuración en NOWPayments

1. Crea una API key en el panel de NOWPayments.
2. En Store Settings genera un secreto IPN.
3. Configura como callback:

```text
https://hbl-e8cw.onrender.com/api/pagos/nowpayments/ipn/
```

4. En Render agrega:

```env
NOWPAYMENTS_API_KEY=tu_api_key
NOWPAYMENTS_IPN_SECRET=tu_secreto_ipn
NOWPAYMENTS_API_BASE_URL=https://api.nowpayments.io/v1
NOWPAYMENTS_IPN_CALLBACK_URL=https://hbl-e8cw.onrender.com/api/pagos/nowpayments/ipn/
NOWPAYMENTS_TIMEOUT_SECONDS=15
NOWPAYMENTS_FEE_PAID_BY_USER=False
```

No guardes estos secretos en Git ni en los campos del panel HBL.

`NOWPAYMENTS_FEE_PAID_BY_USER=False` evita que HBL solicite a NOWPayments agregar otra comisión de servicio sobre el precio de la orden. El cargo comercial de HBL ya está incorporado explícitamente en el precio como +1 USDT.

## Prueba temporal con monto pequeño

Para permitir temporalmente acreditaciones desde 1 USDT agrega en Render:

```env
NOWPAYMENTS_TEST_MODE=True
NOWPAYMENTS_TEST_MIN_USDT=1
```

Con esa configuración, una prueba que acredita 1 USDT genera una orden por 2 USDT. Al finalizar la prueba cambia `NOWPAYMENTS_TEST_MODE=False` y vuelve a desplegar; HBL restaurará el mínimo normal configurado.

## Flujo de depósito

1. El usuario elige TRC20 o BEP20 e ingresa el monto que desea acreditar.
2. HBL suma 1 USDT y crea la orden mediante `POST /v1/payment`.
3. NOWPayments devuelve la dirección y el monto exactos.
4. HBL recibe los cambios por IPN y vuelve a consultar `GET /v1/payment/{payment_id}` como comprobación independiente.
5. El saldo se acredita únicamente cuando el proveedor responde `finished` y coinciden el ID de orden, la red, la moneda y el precio esperado.

`waiting`, `confirming`, `confirmed` y `sending` permanecen procesando. Un `partially_paid` permanece activo: HBL muestra cuánto se recibió y cuánto falta, y seguirá verificando hasta que el proveedor confirme el pago completo. `failed`, `refunded` y `expired` no acreditan saldo.

Las inconsistencias reales de ID, orden, red, moneda o monto quedan disponibles para revisión administrativa, pero los textos técnicos no se exponen al usuario final.

La firma IPN se valida con `x-nowpayments-sig`, HMAC-SHA512 y el secreto IPN. La acreditación es atómica e idempotente para impedir dobles créditos.

## Reconciliación

Además del IPN y de la consulta periódica en la billetera, administración puede ejecutar:

```bash
python manage.py sync_crypto_deposits --limit 100
```

Para volver a consultar también registros pendientes por una inconsistencia real:

```bash
python manage.py sync_crypto_deposits --include-pending --limit 100
```

Las órdenes antiguas creadas antes de activar la regla +1 USDT conservan su precio original y pueden terminar normalmente; la compatibilidad se mantiene para no bloquear depósitos que ya estaban abiertos.

## Retiros

Los retiros aceptan únicamente direcciones USDT TRC20 (`T...`) o BEP20 (`0x...`). HBL detecta la red por la dirección y muestra al usuario el monto neto a recibir, el cargo fijo de 1 USDT y el total a descontar antes de confirmar.

En cada despliegue, `seed_hbl` mantiene las dos redes de retiro activas con comisión porcentual 0 y comisión fija equivalente a 1 USDT en la moneda base vigente. Administración realiza el pago del monto neto y registra la referencia correspondiente.
