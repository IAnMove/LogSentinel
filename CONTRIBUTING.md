# Contribuir

## Entorno

```bash
python -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/python -m pytest -q      # unas 800 pruebas, menos de 30 s
.venv/bin/ruff check .
.venv/bin/mypy
```

Los recorridos de navegador (`scripts/*_smoke.py`) necesitan Playwright; véase
el README. Antes de abrir una petición, ejecuta las pruebas, el linter y los
tipos: son los mismos pasos que la CI.

## Reglas del repositorio

- **Nada de datos reales.** Los ejemplos, las pruebas y los casos de
  evaluación usan datos sintéticos: `example.invalid`, direcciones de
  documentación (`192.0.2.0/24`, `198.51.100.0/24`, `203.0.113.0/24`), usuarios
  como `alice`. No pegues líneas de tus propios equipos, nombres de máquinas,
  rutas de tu directorio personal, claves ni URLs de webhooks.
  `scripts/check_publishable.py` lo comprueba y una prueba lo ejecuta.
- **Cada corrección lleva su prueba**, y la prueba debe fallar sin ella.
- **Sin esperas fijas.** Espera a la condición (`helpers.until`), no a un
  `sleep`. Ninguna prueba puede depender de la hora del día, del disco del
  equipo o de la red.
- **Mensajes de commit.** Una línea imperativa que diga qué cambia, y un cuerpo
  que explique por qué: el problema observado, no solo el arreglo.
- **Interfaz bilingüe.** Toda cadena visible pasa por `t()` o `bilingual()`;
  `node scripts/check_i18n.js` detecta claves repetidas o ausentes.
- **Documentación.** Si cambia un comportamiento que promete el README, cámbialo
  en el mismo commit.

## Estructura

- `logsentinel/portal/`: el portal. `routes/` tiene las rutas por área;
  `review_queue.py` la cola de revisión; `store.py` la base de datos y sus
  migraciones (número en `SCHEMA_VERSION`).
- `logsentinel/{core,llm,memory,notifiers,collectors}/`: la CLI anterior
  (`logsentinel run`), que se mantiene por compatibilidad.
- `logsentinel/client_setup.py` y `portal/forward.py`: el emisor.
- `tests/` y `scripts/`: pruebas unitarias y recorridos de navegador.
