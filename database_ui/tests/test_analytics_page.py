from database_ui.run_app import create_app


def _client():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = None       # gate off for the render check
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {}
    return app.test_client()


def test_analytics_page_renders_shell():
    html = _client().get("/analytics").get_data(as_text=True)
    assert 'id="analytics-root"' in html
    assert "analytics.js" in html


def test_index_has_weekly_report_link():
    html = _client().get("/").get_data(as_text=True)
    assert "/analytics" in html and "Weekly report" in html
