def test_no_overall_score_in_contract(app) -> None:
    schema = app.openapi()
    opportunity_card = schema["components"]["schemas"]["OpportunityCard"]
    assert "overall_score" not in opportunity_card.get("properties", {})
    assert set(opportunity_card["properties"]["axes"]) >= {"title", "type", "additionalProperties"}


def test_openapi_is_frontend_agnostic(app) -> None:
    schema = app.openapi()
    assert schema["openapi"].startswith("3.1")
    assert "/api/v1/applications" in schema["paths"]
    assert "/api/v1/opportunities/{opportunity_id}" in schema["paths"]
    assert "/api/v1/search/opportunities" in schema["paths"]
