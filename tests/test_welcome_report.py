"""G5: welcome screen + report center (headless)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_welcome_dialog_emits_choices(qapp):
    from nbeast.gui.welcome import WelcomeDialog

    dialog = WelcomeDialog(["/tmp/proj-a", "/tmp/proj-b"], show_startup=True)
    chosen = []
    dialog.templateChosen.connect(lambda t: chosen.append(("template", t)))
    dialog.exampleChosen.connect(lambda k: chosen.append(("example", k)))
    dialog._choose_template("Godiva")
    assert chosen == [("template", "Godiva")]
    assert dialog.show_on_startup is True
    dialog.close()


def test_report_html_is_pure_and_escapes():
    from nbeast.gui.report_center import build_report_html

    html_out = build_report_html("Test <k>", [
        ("Model", ["Template: Pin cell", "pitch = 1.26 cm"]),
        ("Studies", ["k-effective run: k = 1.413"]),
    ])
    assert "<h1>Test &lt;k&gt;</h1>" in html_out            # title escaped
    assert "<h2>Model</h2>" in html_out and "<h2>Studies</h2>" in html_out
    assert "pitch = 1.26 cm" in html_out
    assert html_out.strip().endswith("</html>")


def test_report_center_writes_html(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from nbeast.gui.main_window import MainWindow
    from nbeast.gui.report_center import ReportCenterDialog

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    win.set_template("Pin cell")
    dialog = ReportCenterDialog(win)
    dialog.deck_check.setChecked(False)                     # no run yet — HTML only
    out = tmp_path / "report_out"
    out.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(out))
    dialog._generate()
    report = out / "report.html"
    assert report.exists()
    text = report.read_text()
    assert "Template: Pin cell" in text and "Studies" in text and "Validation" in text
    dialog.close()
    win.close()


def test_recent_projects_are_remembered(qapp, tmp_path):
    from nbeast.core.project import Project
    from nbeast.gui.main_window import MainWindow

    win = MainWindow(run_root=tmp_path, project_dir=tmp_path / "p")
    proj = Project.create(tmp_path / "another")
    win._switch_project(proj)
    assert str(proj.path) in win._recent_projects()
    win.close()
