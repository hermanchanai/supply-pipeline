"""A slim LLM wrapper: one request shape across vendors, a spend cap, and a local call log.

Production logs every call to a database and enforces per-system daily budgets there.
This version keeps the parts that matter for reading the code: a neutral Request/Completion
shape, verified per-model prices (an unknown model is an error, never a guessed $0), a
per-run and per-call spend cap checked before each call, and one JSON line per call.
"""
