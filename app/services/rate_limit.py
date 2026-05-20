"""Rate limiter in-memory para endpoints sensibles (creación de órdenes,
magic links). Ventana deslizante por IP.

Limitaciones conocidas:
- Solo válido en single-process / single-instance (suficiente en Azure App
  Service B1 con 1 worker). Si se escala horizontal o se agrega gunicorn -w N,
  hay que mover a Redis o similar.
- En memoria → se resetea al restart del container. Aceptable para anti-DoS
  básico; no es un contador exacto.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from fastapi import HTTPException, Request


class RateLimiter:
    def __init__(self, *, max_calls: int, window_seconds: int) -> None:
        self.max_calls = max_calls
        self.window = window_seconds
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Lanza HTTPException 429 si la key superó el límite en la ventana."""
        now = time.time()
        cutoff = now - self.window
        with self._lock:
            q = self._calls[key]
            # Drop calls fuera de la ventana
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.max_calls:
                retry_after = int(q[0] + self.window - now) + 1
                raise HTTPException(
                    status_code=429,
                    detail=f"Demasiados intentos. Esperá {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
            q.append(now)
            # Garbage collect: si el dict tiene >5000 IPs únicas, dropeamos las
            # entries con queue vacía. Evita leak sin tracking explícito.
            if len(self._calls) > 5000:
                stale = [k for k, dq in self._calls.items() if not dq]
                for k in stale[:1000]:
                    del self._calls[k]


def client_ip(request: Request) -> str:
    """IP del cliente honrando X-Forwarded-For (Azure mete uno) pero capando
    al primer hop para no inflar 429 contra IPs forjadas en proxies legítimos."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# Limiters instanciados arriba para que sean singletons del proceso.
orders_create_limiter = RateLimiter(max_calls=10, window_seconds=60)
auth_request_link_limiter = RateLimiter(max_calls=5, window_seconds=300)
