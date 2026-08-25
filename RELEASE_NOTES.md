# HBL ULTRA 5.1 FINAL

## Diseño
- Rediseño compacto oscuro premium para escritorio, tablet y móvil.
- Corrección de solapamiento de nombre/contacto en sidebar y perfil.
- Quick cards con grid estable y texto con wrap/ellipsis seguro.
- Perfil reconstruido con avatar, identidad, país, moneda y código de invitación.
- Formularios con label, obligatorio/opcional, placeholder, ayuda y error por campo.
- Retiro con resumen de conversión en vivo.
- Galería musical local con lazy-loading.
- HBL Control responsive con navegación compacta.

## Depósitos y retiros cripto
- Solicitud escrita en moneda local asociada al país del usuario.
- Contabilidad congelada en moneda base.
- Pago congelado en la moneda real del método.
- Mínimo global inicial: 500 base, convertido al usuario.
- Mínimo/máximo/comisión por método.
- Únicamente USDT por TRC20 y BEP20.
- Depósitos automáticos mediante órdenes e IPN firmado de NOWPayments.
- Depósitos no concluyentes y todos los retiros conservan revisión manual administrativa.
- Admin muestra importe solicitado, base, comisión y pago final.

## Música diaria
- 10 segundos globales por defecto.
- Heartbeats solo durante reproducción visible/activa.
- Servidor exige tiempo transcurrido y segundos verificados.
- La pista puede exigir un mínimo superior al global.
- Playlist por fecha local; tareas del día anterior vencen.
- Recarga automática de interfaz tras medianoche local.
- Protección contra alternar zonas horarias para fabricar múltiples días.

## Referidos y promociones
- 10% únicamente sobre la primera recarga aprobada de cada referido.
- Referido calificado requiere recarga aprobada.
- Upgrade gratis por bloques de 5 calificados.
- Ruleta promocional gratuita condicionable a referidos calificados.
- Premios, stock, peso y límites controlados en servidor.
- Códigos regalo con vigencia y límites total/usuario.

## Internacional
- 249 países/territorios.
- Mapeo 249/249 país → moneda local.
- 181 monedas fiat de visualización + activos de pago soportados.
- Una moneda base para contabilidad y tasas centralizadas.
- Cambio de base bloqueado después de actividad financiera.

## Seguridad
- Validación de inputs cliente/admin reforzada.
- Protección de redirect de login.
- throttle básico de intentos de login.
- producción exige SECRET_KEY fuerte y ALLOWED_HOSTS.
- saldo/recargas/retiros mediante transacciones atómicas y ledger.
- Depósitos USDT se acreditan solo con estado `finished` reconfirmado por la API de NOWPayments; pagos parciales o inconsistentes quedan para revisión manual.
- comprobantes y audios con límites de tamaño/formato.
