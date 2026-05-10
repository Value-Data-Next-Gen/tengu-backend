# Configurar Webpay Plus en producción

El backend ya está integrado con Webpay Plus (sandbox). Para procesar pagos reales
hay que (A) afiliarse con Transbank — proceso con tu RUT empresa — y (B) cambiar
3 env vars en producción. Esta guía cubre ambos.

---

## A. Afiliación comercial con Transbank

Transbank es la única empresa en Chile que procesa pagos con tarjeta vía Webpay.
La afiliación toma **1 a 2 semanas** y requiere documentación de tu empresa.

### Requisitos

- **Empresa formalmente constituida** (Sociedad por Acciones, EIRL, Sociedad Limitada, o persona natural con inicio de actividades en SII).
- **RUT empresa** y **giro comercial activo** en SII.
- **Cuenta corriente bancaria** a nombre de la empresa (donde Transbank deposita las ventas).
- **Sitio web público** funcionando (importante: tienen que ver el catálogo en línea para aprobar).

### Documentos típicos que pedirán

- Cédula de identidad del representante legal (PDF ambos lados)
- RUT empresa (e-RUT del SII)
- Escritura de constitución de la sociedad (notariada)
- Inicio de actividades en el SII
- Carpeta tributaria electrónica (últimos 3 meses)
- Cartola bancaria reciente (últimos 30 días)
- Modelo de negocio: descripción del producto/servicio + precios

### Costos (referenciales 2026)

| Item | Costo |
|------|-------|
| Afiliación inicial | $0 (gratis para PyMEs Webpay Plus) |
| Comisión por transacción | ~2.95% + IVA (crédito) / ~1.95% + IVA (débito) |
| Mantención mensual | $0 a $9.000 según volumen |
| Liquidación | 24-72h hábiles según banco |

### Cómo iniciar

**Opción 1 — Sitio oficial Transbank**
1. Entrar a https://www.transbank.cl/comercios
2. Click "Quiero ser comercio Webpay" → completar formulario
3. Te llaman / mandan email con la lista de documentos

**Opción 2 — Vía banco (más rápido si ya eres cliente)**
1. Hablar con tu ejecutivo de cuenta del banco (Banco de Chile, Santander, BCI, Itaú, etc.)
2. Ellos canalizan la afiliación a Transbank
3. Suele ser más rápido porque ya tienen tus datos

### Plataforma Webpay Plus — qué te entregan al final

- **Commerce code (código de comercio)**: número largo, ej `597055555532`
- **API Key**: hash hexadecimal de 64 caracteres
- Acceso a **Portal Transbank** (portales.transbank.cl) para ver transacciones, reportes y conciliaciones

⚠️ **Importante**: estas credenciales son secretas. NUNCA commitearlas al repo.

---

## B. Cambios técnicos para pasar de sandbox a producción

El código ya soporta ambos modos. Para activar producción:

### 1. Variables de entorno

En el backend de producción (`backend/.env` en tu servidor o en el panel de Render/Railway):

```env
WEBPAY_ENVIRONMENT=live
WEBPAY_COMMERCE_CODE=597055555555     # el real que te entreguen
WEBPAY_API_KEY=abcd1234...             # el real

# Asegúrate también de que estas apunten a tu dominio real, no a localhost
FRONTEND_URL=https://tenguroastery.cl
WEBPAY_RETURN_URL=https://api.tenguroastery.cl/api/checkout/webpay/return
CORS_ORIGINS=https://tenguroastery.cl
```

### 2. Quitar el bypass TLS (solo aplicaba al sandbox)

En `app/services/webpay.py` la línea que evita verificar TLS solo se activa
cuando `webpay_environment == 'test'`, así que en `live` se desactiva sola.
**Pero** si tu servidor de producción tiene la cadena de CAs OK, el SDK
funcionará sin problemas. Si tienes problemas TLS en producción, hay un bug
de infraestructura que arreglar primero.

### 3. URL de return debe ser HTTPS

Transbank rechaza return URLs `http://` en producción. Tu hosting de backend
**debe** servir por HTTPS. Render, Railway y la mayoría de PaaS ya lo hacen
automáticamente con Let's Encrypt.

### 4. Reiniciar backend

```bash
# Render: redeploy, las env vars nuevas se cargan
# Railway: igual
# VPS: systemctl restart tengu-api
```

### 5. Hacer una transacción de prueba real

**No te saltes este paso.** Antes de hacer marketing:

1. Compra un producto barato (mínimo: ~$1.000 CLP)
2. Paga con tarjeta tuya real
3. Verifica:
   - El pedido aparece en `/admin/orders` con status `paid`
   - El código de autorización Webpay aparece en la orden
   - Llega a tu cuenta bancaria en 24-48h
   - Aparece en el portal de Transbank
4. **Anula la transacción** desde el portal Transbank si quieres recuperar el monto

### 6. Conciliación

Transbank te manda email diario con:
- Resumen de transacciones del día
- Liquidación que llega a tu cuenta

Tu admin debe verificar contra tus pedidos `paid`. Si hay desfases, llamas a
soporte Transbank con el `webpay_authorization_code` de la orden.

---

## C. Errores comunes

| Síntoma | Causa | Solución |
|---------|-------|----------|
| `Invalid commerce code` al hacer checkout | Code o API key con typo | Copia exactamente del email Transbank, sin espacios |
| `URL not allowed` | El return URL no está registrado en el portal | Configurar la URL en portales.transbank.cl |
| Transacción autorizada pero no llega plata | Cuenta bancaria mal configurada | Llamar a soporte Transbank con tracking ID |
| Pago aprobado pero orden queda `pending` | Webhook return no se ejecutó (timeout en TBK) | Verificar logs del backend, reintentar commit con el token |
| Tarjeta declinada constantemente | Cuenta de prueba en cuenta `live` | Asegurar `WEBPAY_ENVIRONMENT=live` y tarjeta real |

---

## D. Alternativas / complementos

Si la afiliación con Transbank te demora o quieres dar más opciones de pago,
estos también están planeados (modelos en backend listos, falta integración):

| Pasarela | Fortaleza | Comisión |
|----------|-----------|----------|
| **Webpay** (este doc) | Estándar Chile, todas las tarjetas | ~3% |
| **Mercado Pago** | Fácil de integrar (SDK Python oficial), aceptación rápida | ~3.5% |
| **Khipu** | Transferencia bancaria directa, comisión más baja | ~1.5% |
| **Flow** | Multipagos (Webpay + MP + transferencia + Klap), un solo onboarding | ~2.95% + 0.5% |

**Recomendación**: Webpay como principal + Khipu para los que prefieran transferencia
(comisión menor te conviene). MP como tercero opcional.

Cuando estés listo para sumar otra pasarela, abre un issue y los integramos.

---

## TL;DR

1. **Hoy**: estás en sandbox, todo funciona con tarjetas de prueba
2. **Cuando tengas empresa formalizada**: tramita en https://www.transbank.cl/comercios
3. **Cuando lleguen las credenciales**: setea 3 env vars en producción
4. **Antes de marketing**: hacer 1 transacción real y verificar end-to-end
