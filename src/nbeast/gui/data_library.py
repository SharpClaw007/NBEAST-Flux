"""Data Library — one window for all nuclear data.

Consolidates what used to be scattered across the app (the cross-section downloader,
the per-material 'needs data' offers, the Xe/Sm poison download, and depletion setup)
into a single browser: categories of materials + special data, what's installed vs.
available, per-item / per-category / everything downloads with size estimates, and
import-from-disk. Downloads accumulate in one library (a superset of the bundle) and
become active. Runs off the UI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from nbeast.core import data, materials

# Display category -> material-catalog category keys. First category to claim a
# material wins (so water shows once, under Moderators).
_MATERIAL_CATEGORIES = (
    ("Fuels", ("fuel",)),
    ("Moderators & reflectors", ("moderator", "reflector")),
    ("Coolants", ("coolant",)),
    ("Cladding & structural", ("cladding", "structural")),
    ("Absorbers", ("absorber",)),
)


class _LibraryWorker(QObject):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    @Slot()
    def run(self):
        try:
            self.done.emit(str(self._fn() or ""))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class DataLibraryDialog(QDialog):
    activated = Signal(str)   # emitted with the active cross_sections.xml when it changes

    def __init__(self, active_xml=None, starter_xml=None, parent=None, focus_category=None):
        super().__init__(parent)
        self.setWindowTitle("Data Library")
        self.resize(760, 620)
        self._active_xml = active_xml
        self._starter_xml = starter_xml       # bundled library, for 'reset'
        self._user_dir = data.default_data_dir()
        self._thread = None
        self._worker = None
        self._focus_category = focus_category  # scroll to this category on open

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "All nuclear data in one place. ✅ installed, ⬇ available to download. "
            "Downloads add to your library and become active; the bundled starter set "
            "always remains as a fallback."
        ))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Data", "Status", "Size", ""])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.tree.header().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        layout.addWidget(self.tree, 1)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #555;")
        layout.addWidget(self.status)

        bottom = QHBoxLayout()
        self.everything_btn = QPushButton(
            f"Download everything ({data.format_size(data.everything_size())})")
        self.everything_btn.clicked.connect(self._download_everything)
        self.import_btn = QPushButton("Import from disk…")
        self.import_btn.clicked.connect(self._import)
        self.reset_btn = QPushButton("Reset to starter")
        self.reset_btn.setToolTip("Remove all downloaded/imported data, freeing space "
                                  "and reverting to the bundled starter library.")
        self.reset_btn.clicked.connect(self._reset)
        bottom.addWidget(self.everything_btn)
        bottom.addWidget(self.import_btn)
        bottom.addWidget(self.reset_btn)
        bottom.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        self._all_buttons = [self.everything_btn, self.import_btn, self.reset_btn]
        self._populate()

    # ---- build the tree ---------------------------------------------------
    def _populate(self) -> None:
        self.tree.clear()
        available = materials.available_names(self._active_xml)
        shown: set[str] = set()
        focus_item = None
        self._add_downloaded_category()   # per-element uninstall, if anything's downloaded
        for label, keys in _MATERIAL_CATEGORIES:
            mspecs = []
            for key in keys:
                for mspec in materials.by_category(key):
                    if mspec.key not in shown:
                        mspecs.append(mspec)
                        shown.add(mspec.key)
            if mspecs:
                item = self._add_material_category(label, mspecs, available)
                if label == self._focus_category:
                    focus_item = item
        poison_item = self._add_poison_category(available)
        if self._focus_category == "Poisons":
            focus_item = poison_item
        dep_item = self._add_depletion_category()
        if self._focus_category == "Depletion":
            focus_item = dep_item
        self.tree.expandAll()
        if focus_item is not None:
            self.tree.scrollToItem(focus_item)
            focus_item.setSelected(True)
        self.status.setText(f"Active library: {self._active_xml or '(bundled starter)'}")

    def _cat_item(self, label: str) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label, "", "", ""])
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        self.tree.addTopLevelItem(item)
        return item

    def _add_material_category(self, label, mspecs, available) -> QTreeWidgetItem:
        cat = self._cat_item(label)
        miss_el: set[str] = set()
        miss_sab: set[str] = set()
        installed = 0
        for mspec in mspecs:
            ok = mspec.is_available(available)
            installed += ok
            row = QTreeWidgetItem([mspec.label, "✅ installed" if ok else "", ""])
            cat.addChild(row)
            if not ok:
                els, sab = mspec.missing_data(available)
                miss_el.update(els)
                miss_sab.update(sab)
                need = ", ".join([*els, *sab]) or "data"
                row.setText(1, f"⬇ needs {need}")
                row.setText(2, data.format_size(data.size_for(elements=els, sab=sab)))
                self._row_button(row, "Download",
                                 lambda e=list(els), s=list(sab): self._download(elements=e, sab=s))
        cat.setText(1, f"{installed}/{len(mspecs)} installed")
        if miss_el or miss_sab:
            cat.setText(2, data.format_size(data.size_for(elements=miss_el, sab=miss_sab)))
            self._row_button(cat, "Download all",
                             lambda e=list(miss_el), s=list(miss_sab): self._download(elements=e, sab=s))
        return cat

    def _add_downloaded_category(self) -> QTreeWidgetItem | None:
        elements = data.downloaded_elements(self._active_xml, self._starter_xml)
        sabs = data.downloaded_sab(self._active_xml, self._starter_xml)
        if not elements and not sabs:
            return None
        cat = self._cat_item("Installed downloads — delete to free space")
        total = 0
        for element in elements:
            size = data.element_size(element)
            total += size
            row = QTreeWidgetItem([f"{element} (element)", "✅ downloaded", data.format_size(size)])
            cat.addChild(row)
            self._row_button(row, "Delete", lambda e=element: self._delete(elements=[e]))
        for name in sabs:
            size = data.sab_size(name)
            total += size
            row = QTreeWidgetItem([name, "✅ downloaded", data.format_size(size)])
            cat.addChild(row)
            self._row_button(row, "Delete", lambda s=name: self._delete(sab=[s]))
        cat.setText(1, f"{len(elements) + len(sabs)} downloaded")
        cat.setText(2, data.format_size(total))
        return cat

    def _add_poison_category(self, available) -> QTreeWidgetItem:
        from nbeast.core import poisons

        cat = self._cat_item("Poisons (fission products)")
        ok = set(poisons.REQUIRED_NUCLIDES) <= available
        row = QTreeWidgetItem(["Xe-135 & Sm-149 (equilibrium poisoning)",
                               "✅ installed" if ok else "⬇ needs Xe-135, Sm-149", ""])
        cat.addChild(row)
        cat.setText(1, "installed" if ok else "needs data")
        if not ok:
            nuclides = list(poisons.REQUIRED_NUCLIDES)
            size = data.format_size(data.size_for(nuclides=nuclides))
            row.setText(2, size)
            cat.setText(2, size)
            self._row_button(row, "Download", lambda n=nuclides: self._download(nuclides=n))
        return cat

    def _add_depletion_category(self) -> QTreeWidgetItem:
        from nbeast.core import depletion

        cat = self._cat_item("Depletion chains")
        ok = depletion.is_available()
        row = QTreeWidgetItem(["ENDF/B-VIII.0 depletion chain + data",
                               "✅ installed" if ok else "⬇ not set up", ""])
        cat.addChild(row)
        cat.setText(1, "installed" if ok else "needs setup")
        if not ok:
            self._row_button(row, "Set up…", self._setup_depletion)
        return cat

    def _row_button(self, item, label, callback) -> None:
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False: callback())
        self.tree.setItemWidget(item, 3, button)
        self._all_buttons.append(button)

    # ---- actions ----------------------------------------------------------
    def _download(self, elements=(), nuclides=(), sab=()) -> None:
        active = self._active_xml
        dest = str(self._user_dir)
        els, nucs, sabs = list(elements), list(nuclides), list(sab)

        def fn():
            if active:
                data.seed_from(active, dest)
            return data.download(dest, elements=els, nuclides=nucs, sab=sabs)

        size = data.format_size(data.size_for(els, nucs, sabs))
        self._run(fn, f"Downloading {size}… (this can take a while)")

    def _delete(self, elements=(), sab=()) -> None:
        names = ", ".join([*elements, *sab])
        if QMessageBox.question(
            self, "Delete data",
            f"Remove {names} from your library to free space? Materials that need it "
            "will show 'needs data' again (you can re-download any time).",
        ) != QMessageBox.Yes:
            return
        active = self._active_xml
        dest = str(self._user_dir)
        els, sabs = list(elements), list(sab)

        def fn():
            xml = data.remove_items(elements=els, sab=sabs, active_xml=active, dest=dest)
            return str(xml) if xml else (active or "")

        self._run(fn, f"Removing {names}…")

    def _download_everything(self) -> None:
        size = data.format_size(data.everything_size())
        if QMessageBox.question(
            self, "Download everything",
            f"This downloads the full ENDF/B-VIII.0 library ({size}). Continue?",
        ) != QMessageBox.Yes:
            return
        self._download(elements=["all"])

    def _import(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Import data — OpenMC .h5 files or a cross_sections.xml", "",
            "OpenMC data (*.h5 *.xml)")
        if not paths:
            return
        active = self._active_xml

        def fn():
            h5s = [p for p in paths if p.endswith(".h5")]
            xmls = [p for p in paths if p.endswith(".xml")]
            result = active
            if h5s:
                result = str(data.import_files(h5s, seed_xml=result))
            for xml in xmls:
                result = str(data.import_library(xml, seed_xml=result))
            return result or ""

        self._run(fn, f"Importing {len(paths)} file(s)…")

    def _reset(self) -> None:
        if QMessageBox.question(
            self, "Reset to starter",
            "Remove all downloaded and imported data, reverting to the bundled starter "
            "library? This frees disk space and cannot be undone.",
        ) != QMessageBox.Yes:
            return
        data.reset_to_starter()
        self._active_xml = self._starter_xml
        if self._starter_xml:
            self.activated.emit(self._starter_xml)
        self.status.setText("Reset to the bundled starter library.")
        self._populate()

    def _setup_depletion(self) -> None:
        from .depletion_setup import DepletionSetupDialog

        dialog = DepletionSetupDialog(parent=self)
        dialog.configured.connect(self._populate)
        dialog.exec()

    # ---- async plumbing ---------------------------------------------------
    def _run(self, fn, message: str) -> None:
        if self._thread is not None:
            return
        self._set_busy(True, message)
        self._thread = QThread()
        self._worker = _LibraryWorker(fn)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.done.connect(self._on_done)      # bound method → queued to GUI thread
        self._worker.failed.connect(self._on_failed)
        self._thread.start()

    def _set_busy(self, busy: bool, message: str) -> None:
        for button in self._all_buttons:
            button.setEnabled(not busy)
        self.tree.setEnabled(not busy)
        self.status.setText(message)

    def _teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = self._worker = None

    @Slot(str)
    def _on_done(self, xml: str) -> None:
        self._teardown()
        if xml:
            self._active_xml = xml
            self.activated.emit(xml)
        self._set_busy(False, "Done.")
        self._populate()

    @Slot(str)
    def _on_failed(self, message: str) -> None:
        self._teardown()
        line = next((ln for ln in reversed(message.strip().splitlines()) if ln.strip()), message)
        self._set_busy(False, f"Failed: {line[:300]}")

    def closeEvent(self, event) -> None:
        self._teardown()
        super().closeEvent(event)
