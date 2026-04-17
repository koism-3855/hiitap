#!/bin/bash
python -c "
from app import app, db, seed, purge_expired_cache
with app.app_context():
    db.create_all()
    seed()
    purge_expired_cache()
"
exec gunicorn app:app --bind 0.0.0.0:${PORT:-10000}
