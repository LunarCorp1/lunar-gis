def test_project_bootstrap_metadata():
    assert "Lunar GIS" in open("metadata.txt", encoding="utf-8").read()
