"""Service-layer helpers for main_ui.

Each module owns one cross-cutting concern (tutor calls, conversation
persistence, image storage, etc.). Route handlers compose these; they never
talk to the underlying libraries directly.
"""
