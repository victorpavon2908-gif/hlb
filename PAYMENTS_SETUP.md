# HBL · Métodos de recarga

HBL queda restringido a **tres métodos de recarga**:

- USDT por TRON / TRC20.
- USDT por BNB Smart Chain / BEP20.
- Transferencia bancaria.

`build.sh` ejecuta `seed_payment_gateways` en cada despliegue. Ese comando normaliza estos tres métodos, desactiva cualquier otro y elimina métodos antiguos que no tengan historial asociado.

## TRC20 y BEP20

En Render configura las direcciones públicas receptoras:

```env
USDT_TRC20_ADDRESS=T...
USDT_BEP20_ADDRESS=0x...
```

Opcionalmente HBL puede obtenerlas mediante la API de Binance:

```env
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_API_BASE_URL=https://api.binance.com
```

Usa una API key con permisos mínimos y **sin permiso de retiro**.

La validación automática usa:

```env
TRONGRID_API_URL=https://api.trongrid.io
TRONGRID_API_KEY=
USDT_TRC20_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t

BSC_RPC_URL=https://bsc-dataseed.bnbchain.org
USDT_BEP20_CONTRACT=0x55d398326f99059ff775485246999027b3197955
BSC_REQUIRED_CONFIRMATIONS=12
CRYPTO_TX_MAX_AGE_MINUTES=30
```

Para TRC20/BEP20 el usuario registra monto exacto y TXID. HBL valida existencia, estado, token, red, destino, monto, confirmaciones y unicidad del TXID antes de acreditar saldo.

## Transferencia bancaria

Puede configurarse desde **HBL Control → Métodos de pago** o mediante variables de Render:

```env
BANK_TRANSFER_DESTINATION=
BANK_TRANSFER_NETWORK=
BANK_TRANSFER_INSTRUCTIONS=
```

Si esas variables están vacías, el deploy conserva los datos bancarios ya guardados en la base de datos.

La transferencia bancaria exige comprobante. La recarga queda `PENDING` hasta que administración la revise y apruebe.

## Comportamiento en la app

Los únicos métodos visibles para el usuario son TRC20, BEP20 y transferencia bancaria. Los métodos antiguos con historial se conservan únicamente como registros inactivos para no romper recargas anteriores; los que no tienen historial se eliminan durante el deploy.

## Reconciliación cripto

```bash
python manage.py sync_crypto_deposits --limit 100
```

También puede reintentar pendientes manuales:

```bash
python manage.py sync_crypto_deposits --include-pending --limit 100
```

## Seguridad

- Nunca guardes seed phrases, private keys, contraseñas de Binance ni códigos 2FA en HBL.
- Nunca subas `.env` al repositorio.
- Un TXID existente no basta: HBL exige token, destino y monto correctos.
- El TXID es único en base de datos para evitar doble acreditación.
- La transferencia bancaria nunca se acredita automáticamente solo por subir una imagen.
- Mantén `DEBUG=False`, HTTPS y PostgreSQL en producción.
