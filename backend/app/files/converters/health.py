"""Converter health probe: engine availability, queue depth, worker count.

The capability table answers "what can this server convert?". This answers the
operational question "is the converter healthy right now?" — a distinction that
matters when an engine binary is uninstalled, or the worker pool died while the
route table still advertises 373 conversions.

Deliberately cheap: no subprocess is spawned and no job is executed. Busy
servers poll this, so it only reads state that is already in memory.
"""
import logging

from aiohttp import web

from . import jobs, queue as queue_mod, registry, routes_table, settings

logger = logging.getLogger(__name__)

# Below this share of available routes the server is degraded rather than down:
# a partial install is still usable, so it must not fail a liveness probe.
DEGRADED_ROUTE_RATIO = 0.9


def _engine_report() -> dict:
    report = {}
    for name, spec in registry.ENGINES.items():
        report[name] = {
            "available": spec.available,
            "binary": spec.binary,
            "needs": list(spec.binaries) or list(spec.modules) or ["python stdlib"],
        }
    return report


def _route_counts() -> dict:
    routes = routes_table.all_routes()
    total = len(routes)
    available = sum(1 for route in routes if route.available)
    return {"total": total, "available": available, "unavailable": total - available}


async def _queue_depth(q):
    """Queue depth, or -1 when the backend cannot be read at all."""
    try:
        return await q.depth()
    except Exception as err:  # a dead queue must not break the health probe
        logger.warning("Health probe could not read queue depth: %s", err)
        return -1


async def health_handler(request: web.Request) -> web.Response:
    """GET /api/files/convert/health — 200 when healthy, 503 when degraded."""
    q = queue_mod.get_queue()
    depth = await _queue_depth(q)
    engines = _engine_report()
    counts = _route_counts()
    workers = jobs.worker_count()
    missing = [name for name, info in engines.items() if not info["available"]]

    if not settings.CONVERTER_V2_ENABLED:
        status, http_status = "disabled", 200
    elif counts["total"] and counts["available"] / counts["total"] < DEGRADED_ROUTE_RATIO:
        status, http_status = "degraded", 503
    elif depth < 0:
        # An unreadable queue is the one failure that stalls every job silently.
        status, http_status = "degraded", 503
    else:
        status, http_status = "ok", 200

    payload = {
        "status": status,
        "version": settings.CAPABILITIES_VERSION,
        "enabled": settings.CONVERTER_V2_ENABLED,
        "routes": counts,
        "engines": engines,
        "missing_engines": missing,
        "queue": {"backend": getattr(q, "name", "unknown"), "depth": depth},
        "workers": {
            "inline": workers,
            "max_concurrent": settings.CONVERTER_MAX_CONCURRENT,
        },
        "limits": {
            "max_bytes": settings.CONVERTER_LIMITS_MAX_BYTES,
            "user_hourly_cap": settings.CONVERTER_USER_HOURLY_CAP,
            "user_max_running": settings.CONVERTER_USER_MAX_RUNNING,
        },
    }
    # Never cached: the whole point is to observe the current state.
    return web.json_response(payload, status=http_status,
                             headers={"Cache-Control": "no-store"})
