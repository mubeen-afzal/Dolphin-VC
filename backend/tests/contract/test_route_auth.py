PUBLIC_OPERATIONS = {
    ("/api/v1/auth/signup", "post"),
    ("/api/v1/auth/login", "post"),
    ("/api/v1/auth/refresh", "post"),
    ("/api/v1/auth/verify-email", "post"),
    ("/api/v1/auth/password/forgot", "post"),
    ("/api/v1/auth/password/reset", "post"),
    ("/api/v1/public/apply", "post"),
    ("/api/v1/public/apply/{tracking_token}", "get"),
    ("/api/v1/public/privacy", "get"),
}


def test_all_non_public_api_routes_declare_auth(app) -> None:
    schema = app.openapi()
    for path, methods in schema["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for method, operation in methods.items():
            if method not in {"get", "post", "patch", "delete", "put"}:
                continue
            if (path, method) in PUBLIC_OPERATIONS:
                continue
            assert operation.get("security"), f"{method.upper()} {path} has no auth dependency"
