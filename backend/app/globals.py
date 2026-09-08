# Mutable shared state for the DecentralChat backend.
# Imported as `from app.globals import g`; handlers reference g.X.

class _G:
    """Namespace for shared mutable backend state."""
    redis_client = None
    cipher_suite = None
    active_connections = {}      # user_id -> set of websockets
    active_calls = {}            # call_id -> call info
    active_group_calls = {}      # group_call_id -> group call info
    # Firebase/Firestore state (populated by core.firebase_client.init_firebase)
    db = None
    firebase_app = None


g = _G()
