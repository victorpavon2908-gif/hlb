# HBL · Pagos manuales

HBL queda configurado para trabajar únicamente con **recargas manuales**. No se usan PayPal ni Tilopay y no existe acreditación automática desde la billetera.

## Flujo

1. El usuario selecciona un método manual habilitado.
2. Realiza la transferencia al destino mostrado por HBL.
3. Escribe referencia/TXID cuando el método lo requiera.
4. Sube un comprobante JPG/PNG/WebP.
5. La recarga se guarda con estado `PENDING`.
6. Administración revisa el comprobante desde **HBL Control → Recargas**.
7. Solo una aprobación administrativa llama a `approve_deposit()` y acredita el saldo.

## Métodos

Los métodos se administran desde **HBL Control → Métodos de pago**. Puedes mantener, por ejemplo:

- Transferencia bancaria.
- Binance ID / referencia manual.
- USDT TRC20 manual.
- USDT BEP20 manual.
- Otra criptomoneda/red manual.
- Giro o remesa.
- Billetera móvil manual.

PayPal, Tilopay y Binance Pay automático quedan desactivados y no aparecen en la billetera.

## Comprobante obligatorio

Toda recarga visible en la billetera exige comprobante. Para métodos de criptomonedas o Binance ID también puede exigirse TXID/referencia.

El comprobante se almacena con el depósito y debe revisarse antes de aprobarlo.

## Deploy

`build.sh` sigue ejecutando:

```text
migrate
collectstatic
seed_hbl
seed_payment_gateways
```

Ahora `seed_payment_gateways` no activa gateways: desactiva métodos automáticos y fuerza `require_proof=True` en los métodos manuales existentes.

## Configuración

Los datos reales del comercio no se guardan en variables de pasarela. Se configuran desde HBL Control:

- Nombre del método.
- Moneda.
- Red si aplica.
- Destino (cuenta, wallet, ID, etc.).
- Instrucciones.
- Monto mínimo/máximo.
- Requerir TXID/referencia.
- Estado activo.

## Seguridad

- No subir `.env` al repositorio.
- No almacenar private keys ni seed phrases.
- Verificar manualmente que monto, destino y referencia coincidan con el comprobante.
- No aprobar depósitos dudosos o incompletos.
- Mantener HTTPS, `DEBUG=False` y PostgreSQL en producción.
