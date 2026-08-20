# HBL · USDT TRC20 / BEP20

HBL queda restringido a **dos métodos de recarga**:

- USDT por TRON / TRC20.
- USDT por BNB Smart Chain / BEP20.

`build.sh` ejecuta `seed_payment_gateways` en cada despliegue. Ese comando crea/normaliza estos dos métodos y desactiva cualquier otro método de recarga.

## Opción 1 — Direcciones públicas de Binance

En Binance abre **Depositar → Cripto → USDT** y copia por separado la dirección para cada red. En Render configura:

```env
USDT_TRC20_ADDRESS=T...
USDT_BEP20_ADDRESS=0x...
```

Estas direcciones son públicas y sirven únicamente para recibir fondos. El dinero enviado por el usuario llegará a la cuenta de Binance propietaria de esas direcciones.

## Opción 2 — Obtener las direcciones por API

También puedes configurar:

```env
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_API_BASE_URL=https://api.binance.com
```

Durante el deploy HBL consulta `GET /sapi/v1/capital/deposit/address` para `USDT` con red `TRX` y `BSC`, valida el formato y guarda únicamente la dirección pública resultante en el método de pago.

La API Secret nunca se guarda en la base de datos ni se envía al navegador. Usa una API key con los permisos mínimos necesarios y **sin permisos de retiro**.

Si la API falla pero existe una dirección pública válida configurada por variable de entorno o ya guardada en la base de datos, HBL usa esa dirección como respaldo.

## Flujo de recarga

1. El usuario escoge TRC20 o BEP20.
2. HBL muestra la dirección correspondiente y permite copiarla.
3. El usuario envía USDT usando exactamente esa red.
4. El usuario registra el monto y el TXID; el comprobante es opcional.
5. La recarga queda pendiente hasta revisión y aprobación administrativa.

La transferencia blockchain sí llega directamente a la billetera receptora; la acreditación del **saldo interno HBL** continúa bajo revisión administrativa para evitar acreditar TXID falsos o montos incorrectos.

## Seguridad

- Nunca guardes seed phrases, private keys ni códigos 2FA en HBL.
- Nunca subas `.env` al repositorio.
- No habilites permisos de retiro en una API key que solo se usa para consultar direcciones.
- Verifica que TRC20 se envíe por TRON y BEP20 por BNB Smart Chain.
- Mantén `DEBUG=False`, HTTPS y PostgreSQL en producción.
