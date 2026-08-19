# HBL · Configuración de pagos

La integración queda preparada para que los secretos vivan únicamente en **Render → Environment**. No guardes credenciales reales en `.env` dentro del repositorio.

## 1. Binance Pay Merchant

Variables:

```env
BINANCE_PAY_ENABLED=True
BINANCE_PAY_API_KEY=
BINANCE_PAY_SECRET_KEY=
BINANCE_PAY_CURRENCY=USDT
BINANCE_PAY_SUPPORT_CURRENCY=USDT
BINANCE_WEBHOOK_MAX_AGE_SECONDS=300
```

Webhook de HBL:

```text
https://TU-DOMINIO/pagos/binance/webhook/
```

HBL crea la orden, conserva `merchantTradeNo`/`prepayId`, valida la firma del webhook y vuelve a consultar la orden antes de acreditar.

## 2. PayPal

Empieza en sandbox:

```env
PAYPAL_ENABLED=True
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=
PAYPAL_CLIENT_SECRET=
PAYPAL_WEBHOOK_ID=
```

Webhook:

```text
https://TU-DOMINIO/pagos/paypal/webhook/
```

Evento requerido para la acreditación automática:

```text
PAYMENT.CAPTURE.COMPLETED
```

Al pasar a producción cambia `PAYPAL_MODE=live` y sustituye las credenciales/webhook por las del entorno Live.

## 3. Tilopay

```env
TILOPAY_ENABLED=True
TILOPAY_API_URL=https://app.tilopay.com/api/v1
TILOPAY_API_KEY=
TILOPAY_API_USER=
TILOPAY_API_PASSWORD=
TILOPAY_CURRENCY=USD
```

HBL usa checkout alojado por Tilopay. El servidor no recibe PAN/CVV. La URL de retorno se genera automáticamente por cada depósito. Antes de acreditar, HBL consulta nuevamente el detalle del Link de Pago y compara referencia, moneda, monto y estado aprobado.

Los métodos concretos visibles dentro del checkout (tarjetas y otros que tenga habilitados el comercio) dependen de la configuración de la cuenta Tilopay.

## 4. USDT TRC20

```env
USDT_TRC20_ENABLED=True
USDT_TRC20_WALLET=
TRONGRID_API_URL=https://api.trongrid.io
TRONGRID_API_KEY=
USDT_TRC20_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t
USDT_TRC20_DECIMALS=6
```

`USDT_TRC20_WALLET` es una dirección **pública**. Nunca pongas la frase semilla o private key. El cliente pega el TXID y HBL comprueba evento `Transfer`, contrato, receptor, monto y confirmación antes de acreditar.

## 5. USDT BEP20 / BNB Smart Chain

```env
USDT_BEP20_ENABLED=True
USDT_BEP20_WALLET=
BSC_RPC_URL=
USDT_BEP20_CONTRACT=
USDT_BEP20_DECIMALS=18
BSC_REQUIRED_CONFIRMATIONS=12
```

Debes definir explícitamente el contrato exacto del token USDT/Binance-Peg que tu comercio decida aceptar. No uses un contrato copiado de una fuente no verificada. `USDT_BEP20_WALLET` es pública; nunca pongas private key/seed.

## 6. Métodos manuales

Transferencia bancaria, Binance ID, remesas, billeteras locales y otras criptomonedas siguen disponibles como métodos administrables desde **HBL Control → Métodos de pago**. Estos requieren los datos reales del comercio (cuenta bancaria, ID, wallet o instrucciones) y pueden exigir comprobante/TXID.

## 7. Qué hace el deploy

`build.sh` ejecuta:

```text
migrate
collectstatic
seed_hbl
seed_payment_gateways
```

`seed_payment_gateways` crea o normaliza Binance Pay, PayPal, Tilopay, TRC20 y BEP20. Los métodos automáticos se activan según los flags y la configuración presente en Environment; no guarda secretos en la base de datos.

## 8. Reconciliación de respaldo

Disponibles:

```bash
python manage.py sync_binance_pay --limit 100
python manage.py sync_paypal_deposits --limit 100
python manage.py sync_tilopay_deposits --limit 100
python manage.py sync_crypto_deposits --limit 100
```

Los cuatro vuelven a consultar al proveedor/blockchain y terminan en `approve_deposit()`. La acreditación es idempotente: una recarga ya aprobada no vuelve a sumar saldo.

## 9. Seguridad obligatoria

- Nunca subir `.env` al repositorio.
- Rotar cualquier secreto que alguna vez haya sido publicado en GitHub.
- Nunca almacenar PAN/CVV ni private keys de wallets en HBL.
- Probar Sandbox antes de activar credenciales Live.
- Mantener `DEBUG=False`, HTTPS y PostgreSQL en producción.
