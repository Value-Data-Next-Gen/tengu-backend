# Configurar SMTP real (Brevo) para magic link

Por defecto el backend usa `SMTP_HOST=__console__` y **imprime el magic link en la
consola** en vez de enviar email. Para que llegue de verdad al correo, configura
Brevo (300 emails/día gratis, sin tarjeta de crédito).

## Paso 1 — Cuenta Brevo

1. Crear cuenta en https://www.brevo.com (antes Sendinblue)
2. Confirmar el email de signup
3. Ir a **SMTP & API** → pestaña **SMTP**
4. Anotar:
   - **SMTP Server**: `smtp-relay.brevo.com`
   - **Port**: `587`
   - **Login**: tu email de Brevo
   - **SMTP Key**: click "Generate a new SMTP key" → guarda el valor

## Paso 2 — Backend `.env`

Crea o edita `backend/.env`:

```env
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=tu-email@brevo.com
SMTP_PASSWORD=xsmtpsib-xxxxxxxxxxxxxxxxxxxxxxxxxxxx
SMTP_FROM_EMAIL=Tengu Roastery <hola@tenguroastery.cl>
SMTP_USE_TLS=true
```

> Importante: el `SMTP_FROM_EMAIL` debe usar un dominio que tengas verificado en
> Brevo (ir a **Senders & IPs**). Si no, llega como spam o se rechaza. Para
> probar sin dominio verificado puedes usar tu mismo `SMTP_USER` como `from`:
> `SMTP_FROM_EMAIL=tu-email@brevo.com`

## Paso 3 — Reiniciar backend

```powershell
# Stop uvicorn actual (Ctrl+C en su terminal)
# Restart
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload
```

Ahora el magic link llega como email real. La consola del backend ya no lo imprime.

## Paso 4 — Probar

1. Ir a http://localhost:5173/admin/login
2. Entrar email autorizado (`g.rojaschacon@gmail.com`)
3. Revisar bandeja de entrada (puede demorar 5-30s)
4. Click en el botón "Entrar al admin"

## Troubleshooting

| Síntoma | Causa probable | Solución |
|---------|----------------|----------|
| Email no llega en 30s | dominio del `SMTP_FROM_EMAIL` no verificado | Usar `SMTP_USER` como `from`, o verificar dominio en Brevo |
| Llega a spam | Sender no autenticado (SPF/DKIM) | Agregar registros SPF y DKIM al dominio (Brevo te los muestra) |
| Error 550/551 al enviar | Credenciales incorrectas | Regenerar SMTP key en Brevo |
| `403 Forbidden` desde Brevo | Cuenta suspendida o sin verificar | Confirmar email de signup, verificar identidad |

## Alternativas

| Servicio | Free tier | Notas |
|----------|-----------|-------|
| **Brevo** | 300/día | Recomendado. Sin tarjeta. |
| **Resend** | 3.000/mes | API moderna, requiere dominio verificado |
| **SendGrid** | 100/día | Históricamente fuerte, integración fácil |
| **Gmail SMTP** | gratis | Requiere "App password" + 2FA. Solo personal, no para producción |
