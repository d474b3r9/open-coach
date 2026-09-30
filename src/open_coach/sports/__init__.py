"""Sport plugins: everything the coach knows about one sport.

The core (models, storage, training load, recovery, plan lifecycle, watch
calendar) is sport-agnostic and only handles the neutral types of
``sports/base.py``. Each sport lives in ``sports/<key>/`` and is looked up
through ``sports/registry.py``.
"""
