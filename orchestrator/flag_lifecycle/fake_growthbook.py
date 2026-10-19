# An in-memory GrowthBook for tests: `gb(method, path, body)` returns (status, document) like the real API client does.


class FakeGrowthBook:
    def __init__(self, features=None):
        self.features, self.calls = dict(features or {}), []

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.startswith("/projects"):
            return 200, {"projects": [{"id": "p1"}]}
        if method == "POST" and path == "/features":
            if body.get("tags") and getattr(self, "refuse_extras", False):
                return 400, {"message": "tags not allowed"}
            self.features[body["id"]] = {"id": body["id"], "environments": body["environments"], "description": body.get("description"), "tags": body.get("tags")}
            return 200, {"feature": self.features[body["id"]]}
        key = path.split("/features/")[-1]
        if method == "GET":
            return (200, {"feature": self.features[key]}) if key in self.features else (404, {})
        if method == "POST":
            feature = self.features[key]
            if "archived" in body:
                feature["archived"] = body["archived"]
            if "environments" in body:
                feature["environments"] = body["environments"]
            return 200, {"feature": feature}
        return 500, {}

    def production_enabled(self, key):
        return self.features[key]["environments"]["production"]["enabled"]
