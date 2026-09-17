"""Explicit, validated SOC migration; callback pipelines are never translated."""
from illustrator_mcp.protocol import TaskPayload


def payload_to_batch(payload: TaskPayload):
    from illustrator_mcp.tools.task_execution import StructuredPilotBatch, _normalize_operation_payload
    payload = _normalize_operation_payload(payload)
    # Compound children belong to one operation, not the outer batch.
    # Keep the same distinction used by the AR09 normalizer and dispatcher.
    ops = payload.params.get("ops") if payload.task != "compound" else None
    if ops is None:
        op = {"task": payload.task, "params": payload.params}
        if payload.targets is not None:
            op["targets"] = payload.targets.model_dump(mode="json", exclude_none=True)
        ops = [op]
    elif set(payload.params) != {"ops"} or payload.targets is not None:
        raise ValueError("Mixed payload has outer params/targets that batch cannot represent; keep payload and remove unused outer fields only after auditing their semantics.")
    try:
        return StructuredPilotBatch(operations=ops, mode=payload.options.mode,
            stopOnError=payload.options.stopOnError, options=payload.options)
    except ValueError as exc:
        raise ValueError("Payload cannot be translated losslessly to batch; keep the compatibility route: " + str(exc)) from exc


def task_intent(params):
    """Equivalent supported SOC routes share intent; callbacks retain all inputs."""
    value = params.model_dump(mode="json", by_alias=True,
        exclude={"job_id", "return_preview", "preview_mode", "final_step", "clip_box"})
    if params.compute_fn is not None or params.apply_fn is not None:
        return value
    try:
        batch = payload_to_batch(params.payload)
    except ValueError:
        return value  # Non-translatable compatibility payload keeps its identity.
    value.pop("payload", None)
    value.pop("batch", None)
    options = params.payload.options.model_dump(mode="json")
    # Default SOC execution always skips the callback collection stage.
    options.update(kind="creation", skipCollect=True)
    value["soc"] = {"operations": [op.model_dump(mode="json", exclude_none=True) for op in batch.operations],
                    "options": options}
    return value
