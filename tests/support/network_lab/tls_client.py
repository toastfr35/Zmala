"""Observe native media security without overriding application policy."""
import ctypes as C


def status(engine):
    params = engine.call_get_current_params(engine.call) if engine.call else None
    if not params:
        return {}
    f = engine.dll.linphone_call_params_get_media_encryption
    f.restype, f.argtypes = C.c_int, [C.c_void_p]
    result = {'media_encryption': f(params)}
    ice = engine.dll.linphone_call_stats_get_ice_state
    ice.restype, ice.argtypes = C.c_int, [C.c_void_p]
    for kind in ('audio', 'video'):
        stats = getattr(engine, 'call_get_'+kind+'_stats')(engine.call)
        if stats:
            try:
                result[kind+'_ice_state'] = ice(stats)
            finally:
                engine.call_stats_unref(stats)
    return result
