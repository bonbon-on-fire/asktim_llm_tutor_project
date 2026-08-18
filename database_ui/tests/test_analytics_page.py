from database_ui.run_app import create_app


def _client():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = None       # gate off for the render check
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {}
    return app.test_client()


def test_analytics_page_route_is_gone():
    # The standalone /analytics page was removed; the report lives only in-place
    # on the dashboard. The GET route should no longer exist.
    assert _client().get("/analytics").status_code == 404


def test_index_has_weekly_report_button():
    html = _client().get("/").get_data(as_text=True)
    assert 'id="weekly-report-open"' in html and "Weekly report" in html
