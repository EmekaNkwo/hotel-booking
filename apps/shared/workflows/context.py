"""Workflow execution context for the Shared Kernel.

This module provides a generic mechanism to mark that a workflow is actively
Executing, allowing domain modules to enforce that state transitions go through
the proper WorkflowRunner path.

The context is designed to be:
- Thread-safe (uses thread-local storage)
- Async-safe (uses context variables)
- Generic (no domain-specific dependencies)
- Extensible (can be used by any workflow)
"""

import contextvars
import threading


# Thread-local storage for the workflow context
_workflow_context = threading.local()

# Context variable for async contexts
_workflow_context_var = contextvars.ContextVar("_workflow_active", default=False)


def mark_workflow_active():
    """Mark that a workflow is actively executing."""
    _workflow_context.active = True
    _workflow_context_var.set(True)


def mark_workflow_inactive():
    """Mark that workflow execution has completed."""
    _workflow_context.active = False
    _workflow_context_var.set(False)


def is_workflow_active() -> bool:
    """Check if we're currently executing within a workflow.

    Returns True if the current thread or async context is executing a workflow.
    """
    # Check thread-local first
    if hasattr(_workflow_context, "active") and _workflow_context.active:
        return True
    # Check context variable for async
    return _workflow_context_var.get()


class WorkflowContext:
    """Context manager for workflow execution.

    Usage:
        with WorkflowContext():
            # Execute workflow transitions
            # State changes are allowed here
            pass

    This context manager marks that workflow execution is active, allowing
domain models to distinguish between proper workflow-driven state changes
and direct bypass attempts.
    """

    def __enter__(self):
        mark_workflow_active()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        mark_workflow_inactive()
        return False