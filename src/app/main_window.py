"""Open Image Blender main window (PySide6/Qt, KDE-native look)."""
import os
import subprocess

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QMainWindow, QPushButton, QRadioButton,
    QSpinBox, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from . import setup_checks
from .worker import RunWorker, SheetWorker

VIEWS = ("front", "side", "back", "top")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Open Image Blender")
        self.resize(1100, 700)
        self.setAcceptDrops(True)
        self.settings = QSettings("openimageblender", "OpenImageBlender")
        self.source_path = None
        self.output_path = None
        self.worker = None
        self.current_run_dir = None

        self.source_label = QLabel("Drop an image here, or choose a file.")
        self.source_label.setAlignment(Qt.AlignCenter)
        self.source_label.setMinimumHeight(180)
        self.source_preview = QLabel()
        self.source_preview.setAlignment(Qt.AlignCenter)
        choose = QPushButton("Choose image…")
        choose.clicked.connect(self.choose_image)

        self.sheet_preview = QLabel("No 3D reference sheet yet.")
        self.sheet_preview.setAlignment(Qt.AlignCenter)
        self.sheet_preview.setMinimumHeight(160)
        self.gen_sheet_btn = QPushButton("1 · Generate 3D reference sheet")
        self.gen_sheet_btn.clicked.connect(lambda: self.make_sheet(None))
        self.use_sheet_btn = QPushButton("Use sheet file…")
        self.use_sheet_btn.clicked.connect(self.choose_sheet)
        self.confirm_sheet_btn = QPushButton("2 · Confirm sheet && start Blender")
        self.confirm_sheet_btn.setEnabled(False)
        self.confirm_sheet_btn.clicked.connect(self.confirm_and_run)
        self.approved_refs = None
        self.sheet_worker = None
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(self.gen_sheet_btn)
        sheet_row.addWidget(self.use_sheet_btn)

        left_top = QVBoxLayout()
        left_top.addWidget(self.source_label)
        left_top.addWidget(self.source_preview)
        left_top.addWidget(choose)
        left_top.addWidget(QLabel("3D angles (confirm before Blender):"))
        left_top.addWidget(self.sheet_preview)
        left_top.addLayout(sheet_row)
        left_top.addWidget(self.confirm_sheet_btn)

        self.key_edit = QLineEdit(self.settings.value("api_key", ""))
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setPlaceholderText("Meta API key (optional, stored locally)")
        self.target_spin = QSpinBox(minimum=10, maximum=100, value=85)
        self.rating_check = QCheckBox("AI rating finish line")
        self.rating_check.setChecked(True)
        self.rating_spin = QDoubleSpinBox(minimum=1.0, maximum=10.0, value=8.0)
        self.rating_spin.setSingleStep(0.5)
        self.rating_spin.setDecimals(1)
        self.rating_check.toggled.connect(self.rating_spin.setEnabled)
        self.driver_code_check = QCheckBox("Let AI write Blender code (experimental)")
        self.blend_new_radio = QRadioButton("New Blender file")
        self.blend_new_radio.setChecked(True)
        self.blend_existing_radio = QRadioButton("Existing Blender file")
        self.blend_file_edit = QLineEdit()
        self.blend_file_edit.setPlaceholderText("Choose a .blend to work from")
        self.blend_file_edit.setEnabled(False)
        self.blend_browse_btn = QPushButton("…")
        self.blend_browse_btn.setEnabled(False)
        self.blend_browse_btn.clicked.connect(self.choose_blend_file)
        self.blend_existing_radio.toggled.connect(self.blend_file_edit.setEnabled)
        self.blend_existing_radio.toggled.connect(self.blend_browse_btn.setEnabled)
        self.rounds_spin = QSpinBox(minimum=1, maximum=100, value=25)
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Output .blend path")
        out_choose = QPushButton("…")
        out_choose.clicked.connect(self.choose_output)

        form = QGridLayout()
        form.addWidget(QLabel("API key"), 0, 0)
        form.addWidget(self.key_edit, 0, 1)
        form.addWidget(QLabel("Target score"), 1, 0)
        form.addWidget(self.target_spin, 1, 1)
        form.addWidget(self.rating_check, 2, 0)
        form.addWidget(self.rating_spin, 2, 1)
        form.addWidget(self.driver_code_check, 3, 0, 1, 2)
        form.addWidget(self.blend_new_radio, 4, 0)
        form.addWidget(self.blend_existing_radio, 4, 1)
        form.addWidget(self.blend_file_edit, 5, 0, 1, 2)
        form.addWidget(self.blend_browse_btn, 5, 2)
        form.addWidget(QLabel("Max rounds"), 6, 0)
        form.addWidget(self.rounds_spin, 6, 1)
        form.addWidget(QLabel("Output"), 7, 0)
        form.addWidget(self.output_edit, 7, 1)
        form.addWidget(out_choose, 7, 2)
        settings_box = QGroupBox("Run settings")
        settings_box.setLayout(form)

        self.setup_labels = [QLabel() for _ in range(4)]
        setup_layout = QVBoxLayout()
        for lab in self.setup_labels:
            setup_layout.addWidget(lab)
        btn_row = QHBoxLayout()
        self.install_btn = QPushButton("Install MCP addon")
        self.install_btn.clicked.connect(self.install_addon)
        self.launch_btn = QPushButton("Launch Blender")
        self.launch_btn.clicked.connect(self.launch_blender)
        self.refresh_btn = QPushButton("Refresh checks")
        self.refresh_btn.clicked.connect(self.refresh_checks)
        btn_row.addWidget(self.install_btn)
        btn_row.addWidget(self.launch_btn)
        btn_row.addWidget(self.refresh_btn)
        setup_layout.addLayout(btn_row)
        setup_box = QGroupBox("Setup")
        setup_box.setLayout(setup_layout)

        left = QVBoxLayout()
        left.addLayout(left_top)
        left.addWidget(settings_box)
        left.addWidget(setup_box)
        left_widget = QWidget()
        left_widget.setLayout(left)

        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.start_run)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel_run)
        self.open_folder_btn = QPushButton("Open output folder")
        self.open_folder_btn.clicked.connect(self.open_folder)
        self.open_blender_btn = QPushButton("Open result in Blender")
        self.open_blender_btn.clicked.connect(self.open_in_blender)
        actions = QHBoxLayout()
        actions.addWidget(self.run_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.open_folder_btn)
        actions.addWidget(self.open_blender_btn)

        self.rounds_list = QListWidget()
        self.rounds_list.currentRowChanged.connect(self.show_round)
        self.view_labels = {v: QLabel(v) for v in VIEWS}
        for lab in self.view_labels.values():
            lab.setAlignment(Qt.AlignCenter)
            lab.setMinimumSize(200, 200)
        views = QGridLayout()
        views.addWidget(self.view_labels["front"], 0, 0)
        views.addWidget(self.view_labels["side"], 0, 1)
        views.addWidget(self.view_labels["back"], 1, 0)
        views.addWidget(self.view_labels["top"], 1, 1)

        self.log_edit = QTextEdit(readOnly=True)
        right = QVBoxLayout()
        right.addLayout(actions)
        right.addWidget(QLabel("Rounds (click to preview)"))
        right.addWidget(self.rounds_list, 1)
        right.addLayout(views)
        right.addWidget(QLabel("Log"))
        right.addWidget(self.log_edit, 1)
        right_widget = QWidget()
        right_widget.setLayout(right)

        splitter = QSplitter()
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([420, 680])
        self.setCentralWidget(splitter)
        self.refresh_checks()

    # -- file selection -------------------------------------------------
    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a character image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif);;All files (*)")
        if path:
            self.set_source(path)

    def choose_blend_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an existing Blender file", "",
            "Blender files (*.blend);;All files (*)")
        if path:
            self.blend_file_edit.setText(path)

    def choose_output(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Output .blend file", self.output_edit.text(),
            "Blender files (*.blend)")
        if path:
            self.output_edit.setText(path)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.set_source(urls[0].toLocalFile())

    def set_source(self, path):
        self.source_path = path
        self.approved_refs = None
        self.confirm_sheet_btn.setEnabled(False)
        self.sheet_preview.setText("No 3D reference sheet yet.")
        self.source_label.setText(os.path.basename(path))
        pix = QPixmap(path)
        if not pix.isNull():
            self.source_preview.setPixmap(pix.scaled(
                360, 240, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        stem = os.path.splitext(os.path.basename(path))[0]
        self.output_edit.setText(os.path.abspath(
            os.path.join("outputs", stem + ".blend")))
        self.log(f"Source: {path}")

    # -- stage 1: reference sheet (image only, no Blender) ---------------
    def choose_sheet(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a 2x2 turnaround sheet", "",
            "Images (*.png *.jpg *.jpeg);;All files (*)")
        if path:
            self.make_sheet(path)

    def make_sheet(self, sheet_path):
        if not self.source_path:
            self.log("Choose an image first.")
            return
        if sheet_path is None and not self.key_edit.text().strip():
            self.log("Generating a sheet needs a Meta API key. "
                     "Without one, use 'Use sheet file…' or Run front-only.")
            return
        if self.key_edit.text().strip():
            import os as _os
            _os.environ["MODEL_API_KEY"] = self.key_edit.text().strip()
        import time
        workdir = os.path.abspath(os.path.join(
            "runs", "sheet-" + time.strftime("%Y%m%d-%H%M%S")))
        self.log("Creating 3D reference angles as images (Blender not started)…")
        self.gen_sheet_btn.setEnabled(False)
        self.sheet_worker = SheetWorker(self.source_path, workdir, sheet_path)
        self.sheet_worker.logmsg.connect(self.log)
        self.sheet_worker.ready.connect(self.on_sheet_ready)
        self.sheet_worker.failed.connect(self.on_sheet_failed)
        self.sheet_worker.start()

    def _refs_pixmap(self, ref_paths):
        """2x2 labelled montage of the individual reference views."""
        cell_w, cell_h = 190, 150
        canvas = QPixmap(cell_w * 2, cell_h * 2)
        canvas.fill(Qt.white)
        painter = QPainter(canvas)
        for i, view in enumerate(VIEWS):
            x, y = (i % 2) * cell_w, (i // 2) * cell_h
            path = ref_paths.get(view)
            pix = QPixmap(path) if path else QPixmap()
            if not pix.isNull():
                painter.drawPixmap(x, y, pix.scaled(
                    cell_w, cell_h - 18, Qt.KeepAspectRatio,
                    Qt.SmoothTransformation))
            else:
                painter.drawText(x + 8, y + 24, "missing")
            painter.drawText(x + 8, y + cell_h - 4, view)
        painter.end()
        return canvas

    def on_sheet_ready(self, ref_paths, sheet):
        self.gen_sheet_btn.setEnabled(True)
        self.approved_refs = ref_paths
        views = ", ".join(v for v in VIEWS if v in ref_paths)
        if sheet:
            pix = QPixmap(sheet)
            if not pix.isNull():
                self.sheet_preview.setPixmap(pix.scaled(
                    380, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.log(f"Reference sheet ready ({views}). "
                     "Check it above, then confirm to start Blender.")
        elif len(ref_paths) > 1:
            self.sheet_preview.setPixmap(self._refs_pixmap(ref_paths))
            self.log(f"Reference views ready ({views}). "
                     "Check them above, then confirm to start Blender.")
        else:
            self.sheet_preview.setPixmap(self._refs_pixmap(ref_paths))
            self.log("Only the front view is available — no side/back/top "
                     "images were created (see the sheet message above). "
                     "Confirming will run Blender front-only.")
        self.confirm_sheet_btn.setEnabled(True)

    def on_sheet_failed(self, msg):
        self.gen_sheet_btn.setEnabled(True)
        self.log("Reference sheet failed: " + msg)

    def confirm_and_run(self):
        self.confirm_sheet_btn.setEnabled(False)
        self.log("Sheet confirmed. Starting Blender work…")
        self.start_run(prepared_refs=self.approved_refs)

    # -- setup ----------------------------------------------------------
    def refresh_checks(self):
        results = setup_checks.run_checks(self.key_edit.text().strip())
        for lab, (ok, text) in zip(self.setup_labels, results):
            lab.setText(("✓ " if ok else "✗ ") + text)

    def install_addon(self):
        self.log("Installing MCP addon…")
        ok, out = setup_checks.install_addon()
        self.log("Addon install " + ("done." if ok else "failed: " + out))
        self.refresh_checks()

    def launch_blender(self):
        from src import blender_host
        ok = blender_host.ensure_blender(self.log)
        self.log("Blender launch " + ("ok." if ok else "failed."))
        self.refresh_checks()

    # -- run ------------------------------------------------------------
    def log(self, msg):
        self.log_edit.append(msg)

    def start_run(self, prepared_refs=None):
        if not self.source_path:
            self.log("Choose an image first.")
            return
        if prepared_refs is None and self.key_edit.text().strip() \
                and self.approved_refs is None:
            self.log("With a key, generate and confirm the 3D reference "
                     "sheet first (step 1), then start Blender (step 2).")
            self.make_sheet(None)
            return
        output = self.output_edit.text().strip()
        if not output:
            self.log("Set an output .blend path first.")
            return
        blend_file = None
        if self.blend_existing_radio.isChecked():
            blend_file = self.blend_file_edit.text().strip()
            if not blend_file or not os.path.isfile(blend_file):
                self.log("Choose an existing .blend file first, "
                         "or switch to New Blender file.")
                return
            if os.path.abspath(blend_file) == os.path.abspath(output):
                self.log("Output must differ from the existing Blender "
                         "file (the original is never overwritten).")
                return
        self.settings.setValue("api_key", self.key_edit.text().strip())
        self.rounds_list.clear()
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.log("Run started (metrics-only mode, no key)"
                 if not self.key_edit.text().strip() else "Run started")
        self.worker = RunWorker(self.source_path, output,
                                self.target_spin.value(),
                                self.rounds_spin.value(),
                                self.key_edit.text().strip(),
                                prepared_refs=prepared_refs,
                                target_rating=self.rating_spin.value(),
                                rating_enabled=self.rating_check.isChecked(),
                                driver_code=self.driver_code_check.isChecked(),
                                blend_file=blend_file)
        self.worker.progress.connect(self.on_progress)
        self.worker.finished_ok.connect(self.on_done)
        self.worker.failed.connect(self.on_failed)
        self.worker.start()

    def cancel_run(self):
        if self.worker:
            self.worker.cancel()
            self.log("Cancelling after the current round…")

    def on_progress(self, event):
        if event.get("type") == "round":
            rec = event["record"]
            self.current_run_dir = event["run_dir"]
            self.rounds_list.addItem(
                f"Round {rec['round']} · strategy {rec['strategy']} · "
                f"score {rec['total']} · rating {rec.get('rating_10')}/10")
            if rec.get("next_plan"):
                self.log(f"Round {rec['round']} plan: {rec['next_plan'][:200]}")
            self.rounds_list.setCurrentRow(self.rounds_list.count() - 1)

    def show_round(self, row):
        if row < 0 or not self.current_run_dir:
            return
        rdir = os.path.join(self.current_run_dir, f"round{row + 1:02d}")
        for view, lab in self.view_labels.items():
            pix = QPixmap(os.path.join(rdir, view + ".png"))
            lab.setPixmap(pix.scaled(260, 260, Qt.KeepAspectRatio,
                                     Qt.SmoothTransformation)
                          if not pix.isNull() else QPixmap())
            lab.setText("" if not pix.isNull() else view)

    def on_done(self, summary):
        self.log(f"Finished. Best round {summary['best_round']} · "
                 f"score {summary['best_total']} · "
                 f"rating {summary.get('best_rating')}/10 · "
                 f"stopped: {summary.get('stop_reason')} · {summary['output']}")
        self.output_path = summary["output"]
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.refresh_checks()

    def on_failed(self, msg):
        self.log("Run failed: " + msg)
        self.run_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.refresh_checks()

    # -- open results ----------------------------------------------------
    def open_folder(self):
        path = self.output_edit.text().strip()
        folder = os.path.dirname(os.path.abspath(path)) if path else os.getcwd()
        subprocess.Popen(["xdg-open", folder])

    def open_in_blender(self):
        path = self.output_edit.text().strip()
        if path and os.path.exists(path):
            subprocess.Popen(["blender", path])
        else:
            self.log("No output file to open yet.")
