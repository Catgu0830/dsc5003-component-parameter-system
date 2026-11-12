from flask import Blueprint

from .auth import login_required
from .common import APIError, body, ok
from .components import query_components
from .tasks import create_task, serialize_task

bp = Blueprint("search", __name__, url_prefix="/api")


@bp.post("/search")
@login_required()
def search():
    data = body()
    query = data.get("query", {})
    if not isinstance(query, dict):
        raise APIError("query must be an object")
    result = query_components(query=query)
    if result["total"] or not data.get("source"):
        return ok({"mode": "database", "needs_extraction": result["total"] == 0, **result})
    source = data["source"]
    if not isinstance(source, dict):
        raise APIError("source must be a task input object")
    task = create_task(source)
    return ok(
        {
            "mode": "extraction",
            "needs_extraction": True,
            "task": serialize_task(task),
            "items": [],
            "publication": "pending_review",
        },
        202,
    )
