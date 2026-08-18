# HBL ULTRA 5.1 FINAL — Informe de validación

Validación ejecutada antes del empaquetado final:

- Todos los módulos Python compilan con `compileall`.
- Todos los JavaScript pasan `node --check`.
- `manifest.webmanifest` es JSON válido.
- Catálogo internacional: 249 países/territorios.
- Mapeo país → moneda: 249/249.
- Catálogo fiat: 181 monedas; catálogo de pago: 185 códigos.
- El retiro local usa la moneda asociada al país de la cuenta; la moneda de visualización del perfil no cambia la moneda de retiro.
- Los métodos de retiro de moneda fija conservan su propia moneda (por ejemplo USDT).
- El mínimo global de retiro se expresa en moneda base y se convierte al país/método antes de mostrarlo.
- La comisión de referido se paga una sola vez y únicamente sobre la primera recarga aprobada.
- La playlist diaria usa fecha local protegida; una tarea del día anterior no puede validarse en el día nuevo.
- Verificación musical global inicial: 10 segundos efectivos; una pista puede exigir más, nunca menos que el global.
- La recompensa diaria se acredita solo tras completar todas las tareas del día y usa una referencia idempotente.
- La ruleta se decide en servidor y puede requerir referidos calificados.
- El upgrade por referidos consume bloques sucesivos; los mismos referidos no habilitan upgrades infinitos.
- Formularios cliente/admin incorporan placeholders, ayudas, obligatorio/opcional, límites y validación del lado servidor.
- Se revisó que el paquete no incluya `.env`, base SQLite, `__pycache__`, `*.pyc`, entorno virtual ni credenciales privadas.

## Pruebas Django

El entorno de construcción no tiene acceso de red para instalar Django. Se intentó instalar Django para ejecutar `manage.py test`, pero la resolución de paquetes externos está bloqueada. Por eso la batería de pruebas Django queda incluida y debe ejecutarse en el equipo de despliegue después de:

```bash
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py test
python manage.py check --deploy
```

Las pruebas incluidas cubren, entre otras reglas: compra de plan, 3 tareas diarias, recompensa única, 10 segundos, retiro mínimo, retiro país/método, depósito mínimo US$100 equivalente, comisión solo primera recarga, ruleta, códigos regalo, 5 referidos para upgrade y registro por teléfono/correo.
