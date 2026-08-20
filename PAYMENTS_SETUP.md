# HBL · USDT TRC20 / BEP20

HBL queda restringido a **dos métodos de recarga**:

- USDT por TRON / TRC20.
- USDT por BNB Smart Chain / BEP20.

`build.sh` ejecuta `seed_payment_gateways` en cada despliegue. Ese comando crea/normaliza estos dos métodos y desactiva cualquier otro método de recarga.

## Direcciones receptoras

En Binance abre **Depositar → Cripto → USDT** y copia por separado la dirección para cada red. En Render configura:

```env
USDT_TRC20_ADDRESS=T...
USDT_BEP20_ADDRESS=0x...
```

Estas direcciones son públicas y sirven únicamente para recibir fondos. El dinero enviado por el usuario llega a la cuenta propietaria de esas direcciones.

Opcionalmente HBL también puede obtener esas direcciones mediante la API de Binance:

```env
BINANCE_API_KEY=
BINANCE_API_SECRET=
BINANCE_API_BASE_URL=https://api.binance.com
```

Usa una API key con permisos mínimos y **sin permiso de retiro**. La API Secret nunca se guarda en la base de datos ni se envía al navegador.

## Validación automática en blockchain

Variables disponibles:

```env
TRONGRID_API_URL=https://api.trongrid.io
TRONGRID_API_KEY=
USDT_TRC20_CONTRACT=TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t

BSC_RPC_URL=https://bsc-dataseed.bnbchain.org
USDT_BEP20_CONTRACT=0x55d398326f99059ff775485246999027b3197955
BSC_REQUIRED_CONFIRMATIONS=12
CRYPTO_TX_MAX_AGE_MINUTES=30
```

`TRONGRID_API_KEY` es opcional pero recomendable para evitar límites bajos del endpoint público. `BSC_RPC_URL` puede sustituirse por un RPC privado si el volumen aumenta.

## Flujo de recarga

1. El usuario escoge TRC20 o BEP20.
2. HBL muestra la dirección receptora correspondiente.
3. El usuario envía USDT usando exactamente esa red.
4. El usuario registra el monto exacto y pega el TXID; el comprobante queda como respaldo opcional.
5. HBL consulta la blockchain y valida:
   - formato y existencia del TXID;
   - ejecución exitosa;
   - contrato del token USDT esperado;
   - dirección receptora exacta de HBL;
   - monto exacto enviado;
   - finalización/confirmaciones de la red;
   - antigüedad razonable del TXID;
   - que el TXID no haya sido registrado previamente.
6. Si todo coincide, `approve_deposit()` acredita el saldo de forma idempotente.
7. Si solo faltan confirmaciones o el proveedor blockchain falla temporalmente, queda `PROCESSING` y la billetera reintenta automáticamente mientras el usuario permanece en la pantalla.
8. Si token, destino o monto no coinciden, queda `PENDING` para revisión manual y no se acredita saldo.

Además existe el comando de respaldo:

```bash
python manage.py sync_crypto_deposits --limit 100
```

Para reintentar también depósitos enviados a revisión manual:

```bash
python manage.py sync_crypto_deposits --include-pending --limit 100
```

## Seguridad

- Nunca guardes seed phrases, private keys, contraseñas de Binance ni códigos 2FA en HBL.
- Nunca subas `.env` al repositorio.
- No habilites permisos de retiro en una API key que solo consulta direcciones.
- Un TXID existente no basta: HBL exige token, destino y monto correctos antes de acreditar.
- El TXID es único en base de datos para evitar doble acreditación.
- Las discrepancias quedan para revisión manual en vez de acreditarse automáticamente.
- Mantén `DEBUG=False`, HTTPS y PostgreSQL en producción.
