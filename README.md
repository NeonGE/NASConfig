# NASConfig

Respaldo de la configuración de mi NAS con OpenMediaVault.

## `compose/`

Copia diaria de los archivos del plugin Compose de OMV
(`/srv/mergerfs/mergpool/appdata/compose`), generada por
`scripts/backup_compose.py` y subida por una tarea programada del NAS.

**Los secretos no están aquí.** Toda variable cuyo nombre parece un secreto
(`*_PASSWORD`, `*_TOKEN`, `*_KEY`, `*_SECRET`, `PLEX_CLAIM`, …) aparece como
`CHANGEME`, y los `.env` se guardan como `.env.example`. Para restaurar una app
hay que poner los valores reales, que viven fuera de este repo (gestor de
contraseñas).

No edites `compose/` a mano en GitHub: el NAS la reescribe en cada respaldo.

## Restaurar una app

1. En OMV: Services → Compose → Files → crear la app con el mismo nombre.
2. Pegar el contenido de `compose/<App>/<App>.yml`.
3. Pegar `compose/<App>/<App>.env.example` en el archivo de entorno y
   reemplazar cada `CHANGEME` por el valor real.
4. Levantar el servicio.

## Script de respaldo

- Solo copia `*.yml`, `*.yaml` y `*.env` (no copia datos de las apps).
- Si detecta algo con pinta de clave o token que no pudo limpiar, **no sube
  nada** y termina con error. La salida dice en qué archivo y línea.
- Solo hace commit cuando algo cambió.

Prueba sin subir nada:

```bash
python3 /root/NASConfig/scripts/backup_compose.py --no-push
```

## Otros archivos

- `pihole/blocking_list.txt`: lista de bloqueo de Pi-hole.
