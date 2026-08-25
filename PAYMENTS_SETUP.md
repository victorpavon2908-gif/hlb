# HBL · Depósitos NOWPayments

HBL acepta únicamente USDT por estas dos redes:

- TRON / TRC20 (`usdttrc20` en NOWPayments).
- BNB Smart Chain / BEP20 (`usdtbsc` en NOWPayments).

Los depósitos se validan automáticamente con la API y los avisos IPN de NOWPayments. Los retiros no usan Mass Payouts: permanecen pendientes para revisión y pago manual por administración.

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
```

No guardes estos secretos en Git ni en los campos del panel HBL.

## Prueba temporal con monto pequeño

Para permitir temporalmente órdenes desde 1 USDT agrega en Render:

```env
NOWPAYMENTS_TEST_MODE=True
NOWPAYMENTS_TEST_MIN_USDT=1
```

NOWPayments conserva su propio mínimo dinámico según la red y las comisiones. Al finalizar la prueba cambia `NOWPAYMENTS_TEST_MODE=False` y vuelve a desplegar; HBL restaurará el mínimo normal configurado.

## Flujo de depósito

1. El usuario elige TRC20 o BEP20 e ingresa el monto.
2. HBL crea una orden mediante `POST /v1/payment`.
3. NOWPayments devuelve la dirección y el monto exactos.
4. HBL recibe los cambios por IPN y vuelve a consultar `GET /v1/payment/{payment_id}` como comprobación independiente.
5. El saldo se acredita únicamente cuando el proveedor responde `finished` y coinciden el ID de orden, la red, la moneda y el monto solicitado.

`waiting`, `confirming`, `confirmed` y `sending` permanecen procesando. `partially_paid` o cualquier inconsistencia pasan a revisión manual. `failed`, `refunded` y `expired` no acreditan saldo.

La firma IPN se valida con `x-nowpayments-sig`, HMAC-SHA512 y el secreto IPN. La acreditación es atómica e idempotente para impedir dobles créditos.

## Reconciliación

Además del IPN y de la consulta periódica en la billetera, administración puede ejecutar:

```bash
python manage.py sync_crypto_deposits --limit 100
```

Para volver a consultar también los pagos parciales enviados a revisión:

```bash
python manage.py sync_crypto_deposits --include-pending --limit 100
```

## Revisión manual y retiros

Los depósitos pendientes pueden aprobarse o rechazarse desde `/control/recargas/`. Esa opción es un respaldo operativo y debe usarse solo tras comprobar el pago en NOWPayments.

Los retiros aceptan únicamente direcciones USDT TRC20 (`T...`) o BEP20 (`0x...`). HBL detecta la red por la dirección, reserva el saldo y deja la solicitud pendiente; administración realiza el pago y registra la referencia manualmente.
