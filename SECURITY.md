# Seguridad

## Cómo informar de una vulnerabilidad

Usa **Report a vulnerability** en la pestaña *Security* del repositorio de
GitHub (aviso privado). No abras un *issue* público ni pegues en él logs,
claves o URLs de tu instalación. Incluye la versión (`pip show logsentinel`), los
pasos para reproducirlo y qué esperabas.

## Qué protege y qué no

| Superficie | Cómo está protegida |
| --- | --- |
| Panel (`:8765`) | Solo escucha en loopback; comprueba `Host` y `Origin`; exige cabecera CSRF y sesión; clave de acceso de 256 bits que se puede rotar. Se accede desde otro equipo por túnel SSH. |
| Receptor (`--ingest-listen`) | Aparte del panel. Cada fuente tiene su token (guardado como hash). En red, exige TLS. El alta usa un código de un solo uso que caduca y se cuenta por dirección. |
| Emisor | Cuenta sin login, unidad systemd confinada, certificado del central fijado y comparado con una huella que confirma quien lo instala. |
| Destinos y proveedores | Sin proxies del entorno, sin redirecciones, con bloqueo de direcciones de metadatos cloud comprobado al conectar. Las claves no se devuelven al navegador. |
| Registros y avisos | Se ocultan las credenciales reconocibles antes de salir. Es una lista, no una garantía. |
| Modelo | Sus respuestas se validan; no ejecuta acciones. El texto de los logs se trata como dato; el detector de instrucciones es una lista de frases y se puede sortear. |

**Fuera de alcance**: un usuario local con acceso de lectura a
`~/.local/share/logsentinel` (la base guarda las credenciales de los destinos
sin cifrar, con permisos 0600), y la inmunidad del modelo a la inyección de
instrucciones.

## Datos sensibles

La base de datos, las copias de seguridad y `access-key.txt` contienen logs
originales y secretos. Se crean con permisos de propietario. Tras restaurar una
copia, rota la clave de acceso, los tokens de fuente y las credenciales de los
destinos.

## Versiones con soporte

Se corrige la última versión publicada. El repositorio no tiene ramas de
mantenimiento.
