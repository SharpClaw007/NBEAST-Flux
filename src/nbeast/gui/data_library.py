"""Data Library — one window for all nuclear data.

Two tabs:
  • Materials — categories (fuels/moderators/…) + Poisons + Depletion, collapsed on open,
    each material showing installed vs. needs-data with sizes and downloads.
  • Elements — a classic periodic table of the full ENDF/B-VIII.0 library (green = all
    isotopes installed, amber = some, grey = available). Clicking an element opens a
    grouped list of its individual isotopes + the materials that use it, with a Back button.

Downloads accumulate into one library (a superset of the bundled starter) and become
active. All network work runs off the UI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
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


def _pt_position(z: int):
    """(grid row, group column 1-18) for atomic number z in a classic periodic table;
    lanthanides land on grid row 8 and actinides on row 9 (row 7 is a spacer)."""
    if z == 1:
        return (0, 1)
    if z == 2:
        return (0, 18)
    if z == 3:
        return (1, 1)
    if z == 4:
        return (1, 2)
    if 5 <= z <= 10:
        return (1, z + 8)
    if z == 11:
        return (2, 1)
    if z == 12:
        return (2, 2)
    if 13 <= z <= 18:
        return (2, z)
    if 19 <= z <= 36:
        return (3, z - 18)
    if 37 <= z <= 54:
        return (4, z - 36)
    if z in (55, 56):
        return (5, z - 54)
    if 57 <= z <= 71:
        return (8, z - 54)     # lanthanides
    if 72 <= z <= 86:
        return (5, z - 68)
    if z in (87, 88):
        return (6, z - 86)
    if 89 <= z <= 103:
        return (9, z - 86)     # actinides
    if 104 <= z <= 118:
        return (6, z - 100)
    return None


class _ElementCell(QFrame):
    """One periodic-table box: atomic number, symbol, and an isotopes·materials count,
    tinted by install status. Clickable when the element has data."""

    # Light cell backgrounds with explicitly dark text — self-contained, so the table
    # reads the same in light or dark app themes (never inherits a light theme text colour).
    # Data cells: opaque light backgrounds + dark text (readable in any theme). No-data
    # cells: transparent, so they recede into whatever background (light or dark) is active.
    _BG = {"full": "#bfe3c2", "some": "#ffdf80", "none": "#d7dee3", "disabled": "transparent"}
    _BORDER = {"full": "#4caf50", "some": "#f5a623", "none": "#9fb0bc", "disabled": "#777777"}

    def __init__(self, z, symbol, count, status, enabled, on_click):
        super().__init__()
        self._on_click = on_click if enabled else None
        self.setFixedSize(42, 46)
        self.setStyleSheet(
            f"_ElementCell{{background:{self._BG[status]};"
            f"border:1px solid {self._BORDER[status]};border-radius:3px;}}"
        )
        sym_color = "#141414" if enabled else "#8a8a8a"
        sub_color = "#3a3a3a" if enabled else "#7a7a7a"
        v = QVBoxLayout(self)
        v.setContentsMargins(2, 1, 2, 1)
        v.setSpacing(0)
        num = QLabel(str(z))
        num.setAlignment(Qt.AlignRight | Qt.AlignTop)
        num.setStyleSheet(f"font-size:7px;color:{sub_color};border:0;background:transparent;")
        sym = QLabel(symbol)
        sym.setAlignment(Qt.AlignCenter)
        sym.setStyleSheet(f"font-size:13px;font-weight:bold;color:{sym_color};"
                          "border:0;background:transparent;")
        cnt = QLabel(count)
        cnt.setAlignment(Qt.AlignCenter)
        cnt.setStyleSheet(f"font-size:8px;color:{sub_color};border:0;background:transparent;")
        v.addWidget(num)
        v.addWidget(sym)
        v.addWidget(cnt)
        if enabled:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(f"{symbol} — click for isotopes + materials")

    def mousePressEvent(self, event):   # noqa: N802
        if self._on_click:
            self._on_click()


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
        self.resize(900, 680)
        self._active_xml = active_xml
        self._starter_xml = starter_xml
        self._user_dir = data.default_data_dir()
        self._thread = None
        self._worker = None
        self._focus_category = focus_category
        self._available_names: set[str] = set()
        self._downloaded_els: set[str] = set()
        self._detail_element = None

        # element -> catalog materials that contain it (computed once; catalog is static)
        self._mats_by_el: dict[str, list] = {}
        for mspec in materials.LIBRARY.values():
            for element in {data.element_of(n) for n in mspec.required_names()}:
                if element:
                    self._mats_by_el.setdefault(element, []).append(mspec)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "All nuclear data in one place. Browse <b>Materials</b> by category, or open the "
            "<b>Elements</b> tab for the full periodic table. Downloads add to your library and "
            "become active; the bundled starter set always remains as a fallback."
        ))

        from PySide6.QtWidgets import QLineEdit, QProgressBar

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search materials + elements (e.g. “steel”, “Gd”, “c_Graphite”)…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_search)
        layout.addWidget(self.search)

        self.tabs = QTabWidget()
        # --- Materials tab ---
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Data", "Status", "Size", ""])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            self.tree.header().setSectionResizeMode(col, QHeaderView.ResizeToContents)
        self.tabs.addTab(self.tree, "Materials")
        # --- Elements tab (periodic table <-> element detail) ---
        self.el_stack = QStackedWidget()
        self._pt_scroll = QScrollArea()
        self._pt_scroll.setWidgetResizable(True)
        self.el_stack.addWidget(self._pt_scroll)      # index 0: periodic table
        self.el_stack.addWidget(QWidget())            # index 1: detail (rebuilt on demand)
        self.tabs.addTab(self.el_stack, "Elements")
        layout.addWidget(self.tabs, 1)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)         # indeterminate: downloads have no batch count
        self.progress.setMaximumWidth(220)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setWordWrap(True)
        status_row = QHBoxLayout()
        status_row.addWidget(self.progress)
        status_row.addWidget(self.status, 1)
        layout.addLayout(status_row)

        self.disk_label = QLabel("")
        self.disk_label.setStyleSheet("color:#888;")
        layout.addWidget(self.disk_label)

        bottom = QHBoxLayout()
        self.standard_btn = QPushButton(
            f"Download standard set ({data.format_size(data.standard_size())})")
        self.standard_btn.setToolTip(
            "The common materials most of the catalog needs (steels, absorbers, graphite, "
            "sodium, lead, aluminum…) — makes ~90% of the material list runnable.")
        self.standard_btn.clicked.connect(self._download_standard)
        self.everything_btn = QPushButton(
            f"Download everything ({data.format_size(data.everything_size())})")
        self.everything_btn.clicked.connect(self._download_everything)
        self.import_btn = QPushButton("Import from disk…")
        self.import_btn.clicked.connect(self._import)
        self.reset_btn = QPushButton("Reset to starter")
        self.reset_btn.setToolTip("Remove all downloaded/imported data, freeing space "
                                  "and reverting to the bundled starter library.")
        self.reset_btn.clicked.connect(self._reset)
        bottom.addWidget(self.standard_btn)
        bottom.addWidget(self.everything_btn)
        bottom.addWidget(self.import_btn)
        bottom.addWidget(self.reset_btn)
        bottom.addStretch(1)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.rejected.connect(self.reject)
        bottom.addWidget(close)
        layout.addLayout(bottom)

        self._populate()

    # ---- top-level rebuild ------------------------------------------------
    def _populate(self) -> None:
        available = materials.available_names(self._active_xml)
        self._available_names = set(available)
        self._downloaded_els = set(data.downloaded_elements(self._active_xml, self._starter_xml))
        self._build_materials_tree(available)
        self._build_periodic_page(available)
        if self._detail_element:
            self._show_element_detail(self._detail_element)   # refresh an open detail view
        self.status.setText(f"Active library: {self._active_xml or '(bundled starter)'}")
        self._update_disk_usage()
        if getattr(self, "search", None) is not None and self.search.text():
            self._apply_search(self.search.text())

    def _update_disk_usage(self) -> None:
        installed = data.installed_h5()
        if not installed:
            self.disk_label.setText("Disk: bundled starter only (no downloads).")
            return
        import os

        total = 0
        for name in installed:
            try:
                total += os.path.getsize(self._user_dir / name)
            except OSError:
                pass
        self.disk_label.setText(
            f"Disk: {len(installed)} downloaded data files · {data.format_size(total)} "
            f"in {self._user_dir}")

    def _apply_search(self, text: str) -> None:
        """Filter the Materials tree to rows matching the query; empty shows everything.
        Matches material label, category, and the needed-element/status text."""
        query = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            cat = self.tree.topLevelItem(i)
            any_visible = False
            for j in range(cat.childCount()):
                row = cat.child(j)
                haystack = " ".join(row.text(c).lower() for c in range(3)) + " " + cat.text(0).lower()
                match = (query in haystack) if query else True
                row.setHidden(not match)
                any_visible = any_visible or match
            cat.setHidden(bool(query) and not any_visible)
            if any_visible and query:
                cat.setExpanded(True)

    # ---- Materials tab ----------------------------------------------------
    def _build_materials_tree(self, available) -> None:
        self.tree.clear()
        shown: set[str] = set()
        focus_item = None
        for label, keys in _MATERIAL_CATEGORIES:
            mspecs = []
            for key in keys:
                for mspec in materials.by_category(key):
                    if mspec.key not in shown:
                        mspecs.append(mspec)
                        shown.add(mspec.key)
            if mspecs:
                item = self._add_material_category(label, mspecs, available)
                if label == "Moderators & reflectors":
                    self._add_downloaded_sab_rows(item)
                if label == self._focus_category:
                    focus_item = item
        poison_item = self._add_poison_category(available)
        if self._focus_category == "Poisons":
            focus_item = poison_item
        dep_item = self._add_depletion_category()
        if self._focus_category == "Depletion":
            focus_item = dep_item
        # Collapsed on open. Only a category we were asked to focus is expanded + revealed.
        if focus_item is not None:
            self.tabs.setCurrentIndex(0)
            focus_item.setExpanded(True)
            self.tree.scrollToItem(focus_item)
            focus_item.setSelected(True)

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
                self._row_button(self.tree, row, "Download",
                                 lambda e=list(els), s=list(sab): self._download(elements=e, sab=s))
        cat.setText(1, f"{installed}/{len(mspecs)} installed")
        if miss_el or miss_sab:
            cat.setText(2, data.format_size(data.size_for(elements=miss_el, sab=miss_sab)))
            self._row_button(self.tree, cat, "Download all",
                             lambda e=list(miss_el), s=list(miss_sab): self._download(elements=e, sab=s))
        return cat

    def _add_downloaded_sab_rows(self, moderator_cat: QTreeWidgetItem) -> None:
        for name in data.downloaded_sab(self._active_xml, self._starter_xml):
            row = QTreeWidgetItem([f"{name} (thermal scattering)", "✅ downloaded",
                                   data.format_size(data.sab_size(name))])
            moderator_cat.addChild(row)
            self._row_button(self.tree, row, "Delete", lambda s=name: self._delete(sab=[s]))

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
            self._row_button(self.tree, row, "Download", lambda n=nuclides: self._download(nuclides=n))
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
            self._row_button(self.tree, row, "Set up…", self._setup_depletion)
        return cat

    # ---- Elements tab: periodic table ------------------------------------
    def _build_periodic_page(self, available) -> None:
        host = QWidget()
        outer = QVBoxLayout(host)
        grid_widget = QWidget()
        grid = QGridLayout(grid_widget)
        grid.setSpacing(2)
        grid.setContentsMargins(6, 6, 6, 6)
        grid.setRowMinimumHeight(7, 12)   # gap above the lanthanide/actinide rows

        import openmc.data

        symbols = openmc.data.ATOMIC_SYMBOL
        have = set(data.all_elements())
        for z in range(1, 119):
            symbol = symbols.get(z)
            pos = _pt_position(z)
            if not symbol or pos is None:
                continue
            row, col = pos
            if symbol in have:
                isotopes = data.nuclides_of(symbol)
                installed = sum(1 for n in isotopes if n in available)
                status = ("full" if isotopes and installed == len(isotopes)
                          else "some" if installed else "none")
                n_mat = len(self._mats_by_el.get(symbol, []))
                count = f"{len(isotopes)}·{n_mat}" if n_mat else f"{len(isotopes)}"
                cell = _ElementCell(z, symbol, count, status, True,
                                    lambda s=symbol: self._show_element_detail(s))
            else:
                cell = _ElementCell(z, symbol, "", "disabled", False, None)
            grid.addWidget(cell, row, col - 1)

        outer.addWidget(grid_widget)
        legend = QLabel(
            "<span style='background:#bfe3c2;color:#141414'>&nbsp;green&nbsp;</span> all isotopes "
            "installed &nbsp; <span style='background:#ffdf80;color:#141414'>&nbsp;amber&nbsp;</span> "
            "some installed &nbsp; <span style='background:#d7dee3;color:#141414'>&nbsp;grey&nbsp;</span> "
            "available to download &nbsp;·&nbsp; each box: symbol + <b>isotopes·materials</b>. "
            "Click an element for details."
        )
        legend.setWordWrap(True)
        outer.addWidget(legend)
        outer.addStretch(1)
        self._pt_scroll.setWidget(host)

    def _show_periodic_table(self) -> None:
        self._detail_element = None
        self.el_stack.setCurrentIndex(0)

    # ---- Elements tab: one element's detail ------------------------------
    def _show_element_detail(self, symbol: str) -> None:
        self._detail_element = symbol
        available = self._available_names
        isotopes = data.nuclides_of(symbol)
        installed = sum(1 for n in isotopes if n in available)
        mspecs = self._mats_by_el.get(symbol, [])

        page = QWidget()
        v = QVBoxLayout(page)
        top = QHBoxLayout()
        back = QPushButton("← Back to table")
        back.clicked.connect(self._show_periodic_table)
        top.addWidget(back)
        top.addWidget(QLabel(
            f"<b>{symbol}</b> — {len(isotopes)} isotopes · {len(mspecs)} material(s) · "
            f"{installed}/{len(isotopes)} installed"))
        top.addStretch(1)
        if symbol in self._downloaded_els:
            btn = QPushButton(f"Delete {symbol}")
            btn.clicked.connect(lambda: self._delete(elements=[symbol]))
            top.addWidget(btn)
        elif installed < len(isotopes):
            btn = QPushButton(f"Download all {symbol} ({data.format_size(data.element_size(symbol))})")
            btn.clicked.connect(lambda: self._download(elements=[symbol]))
            top.addWidget(btn)
        v.addLayout(top)

        detail = QTreeWidget()
        detail.setHeaderLabels(["Data", "Status", "Size", ""])
        detail.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for col in (1, 2, 3):
            detail.header().setSectionResizeMode(col, QHeaderView.ResizeToContents)

        iso_head = QTreeWidgetItem(["Isotopes (individual)", "", ""])
        detail.addTopLevelItem(iso_head)
        for nuclide in isotopes:
            ok = nuclide in available
            item = QTreeWidgetItem([nuclide, "✅ installed" if ok else "",
                                    "" if ok else data.format_size(data.nuclide_size(nuclide))])
            iso_head.addChild(item)
            if not ok:
                self._row_button(detail, item, "Download", lambda n=nuclide: self._download(nuclides=[n]))

        if mspecs:
            mat_head = QTreeWidgetItem([f"Used in {len(mspecs)} material(s)", "", ""])
            detail.addTopLevelItem(mat_head)
            for mspec in mspecs:
                ok = mspec.is_available(available)
                item = QTreeWidgetItem([mspec.label, "✅ installed" if ok else "", ""])
                mat_head.addChild(item)
                if not ok:
                    els, sab = mspec.missing_data(available)
                    item.setText(1, "⬇ needs " + ", ".join([*els, *sab]))
                    item.setText(2, data.format_size(data.size_for(elements=els, sab=sab)))
                    self._row_button(detail, item, "Download",
                                     lambda e=list(els), s=list(sab): self._download(elements=e, sab=s))
        detail.expandAll()
        v.addWidget(detail, 1)

        old = self.el_stack.widget(1)
        self.el_stack.insertWidget(1, page)
        if old is not None:
            self.el_stack.removeWidget(old)
            old.deleteLater()
        self.el_stack.setCurrentIndex(1)
        self.tabs.setCurrentIndex(1)

    def _row_button(self, tree, item, label, callback) -> None:
        button = QPushButton(label)
        button.clicked.connect(lambda _checked=False: callback())
        tree.setItemWidget(item, 3, button)

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

    def _download_standard(self) -> None:
        size = data.format_size(data.standard_size())
        if QMessageBox.question(
            self, "Download standard set",
            f"Download the common materials most of the catalog needs ({size})? This makes "
            "~90% of the material list runnable (steels, absorbers, graphite, sodium, "
            "lead, aluminum…) without the full library.",
        ) != QMessageBox.Yes:
            return
        self._download(elements=list(data.STANDARD_ELEMENTS), sab=list(data.STANDARD_SAB))

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
        self._detail_element = None
        if self._starter_xml:
            self.activated.emit(self._starter_xml)
        self._populate()
        self.status.setText("Reset to the bundled starter library.")

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
        # Only the download-triggering buttons are disabled during a download; browsing
        # the tree / periodic table / search stays live, and a progress bar shows work.
        for button in (self.standard_btn, self.everything_btn, self.import_btn, self.reset_btn):
            button.setEnabled(not busy)
        self.progress.setVisible(busy)
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
