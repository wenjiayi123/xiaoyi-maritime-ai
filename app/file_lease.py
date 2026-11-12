"""Exclusive file leases used by the standalone local research commands."""
import os

if os.name=="nt":
    from app.windows_flock import LOCK_EX, LOCK_NB, LOCK_UN, flock
else:
    from fcntl import LOCK_EX, LOCK_NB, LOCK_UN, flock

__all__=["LOCK_EX","LOCK_NB","LOCK_UN","flock"]
