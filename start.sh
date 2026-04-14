#!/bin/bash
python -c "
from app import app, db, seed
with app.app_context():
    db.create_all()
    seed()
"
exec gunicorn app:app --bind 0.0.0.0:${PORT:-10000}
