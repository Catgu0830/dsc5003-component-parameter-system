"""Category / parameter dictionary loaded from the 11-table schema."""
from flask import Blueprint

from .auth import login_required
from .common import ok
from .db import get_db

bp = Blueprint("catalog", __name__, url_prefix="/api")


class Catalog:
    def __init__(self, parameters, aliases, categories):
        self.parameters = parameters
        self.by_alias = {}
        self.categories = categories
        self.category_by_name = {}
        self.aliases_by_param = {}
        for item in parameters:
            for key in (item["canonical_name"], item["display_name"]):
                self.by_alias.setdefault(key.casefold(), item)
        for alias, parameter_id in aliases:
            self.aliases_by_param.setdefault(parameter_id, []).append(alias)
            item = next((p for p in parameters if p["parameter_id"] == parameter_id), None)
            if item is not None:
                self.by_alias.setdefault(alias.casefold(), item)
        for item in categories:
            self.category_by_name.setdefault(item["name"].casefold(), item)

    def parameter(self, name):
        if name is None:
            return None
        return self.by_alias.get(str(name).strip().casefold())

    def category(self, name):
        if name is None:
            return None
        return self.category_by_name.get(str(name).strip().casefold())

    def parameter_aliases(self, parameter_id):
        return sorted(self.aliases_by_param.get(parameter_id, []))


def load_catalog(db=None):
    db = db or get_db()
    parameters = [
        dict(row)
        for row in db.execute(
            "SELECT parameter_id,canonical_name,display_name,unit,data_type,category_id,description "
            "FROM parameter_def ORDER BY parameter_id"
        )
    ]
    aliases = [
        (row["alias"], row["parameter_id"])
        for row in db.execute("SELECT alias,parameter_id FROM parameter_alias ORDER BY alias_id")
    ]
    categories = [
        dict(row)
        for row in db.execute(
            "SELECT category_id,name,description FROM category ORDER BY category_id"
        )
    ]
    return Catalog(parameters, aliases, categories)


@bp.get("/categories")
@login_required()
def categories():
    catalog = load_catalog()
    return ok({"items": catalog.categories})


@bp.get("/parameters")
@login_required()
def parameters():
    catalog = load_catalog()
    items = []
    for item in catalog.parameters:
        item = dict(item)
        item["aliases"] = catalog.parameter_aliases(item["parameter_id"])
        items.append(item)
    return ok({"items": items})
