"""Background worker: runs the single-shot image->.blend build off the GUI thread."""
import os
import threading

from PySide6.QtCore import QThread, Signal


class SheetWorker(QThread):
    """Stage 1 only: create/split the 3D-angle reference sheet. No Blender."""
    ready = Signal(dict, object)  # refs dict, sheet path or None
    failed = Signal(str)
    logmsg = Signal(str)

    def __init__(self, source, workdir, sheet_path=None, sheet_prompt=None):
        super().__init__()
        self.source = source
        self.workdir = workdir
        self.sheet_path = sheet_path
        self.sheet_prompt = sheet_prompt

    def run(self):
        try:
            from src import refs
            ref_paths, sheet = refs.prepare_references(
                self.source, self.workdir, self.logmsg.emit,
                sheet_path=self.sheet_path, sheet_prompt=self.sheet_prompt)
            self.ready.emit(ref_paths, sheet)
        except Exception as e:
            self.failed.emit(str(e))


class RunWorker(QThread):
    """One prompt, one build. No rounds, rating or retries to configure."""
    progress = Signal(dict)
    failed = Signal(str)
    finished_ok = Signal(dict)

    def __init__(self, source, output, api_key, prepared_refs=None,
                 segment_prompt="person", blend_file=None, **_deprecated):
        super().__init__()
        self.source = source
        self.output = output
        self.api_key = api_key
        self.prepared_refs = prepared_refs
        self.segment_prompt = segment_prompt
        self.blend_file = blend_file
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def _prepare_source(self):
        if self.source.lower().endswith(".gif"):
            from PIL import Image
            out = os.path.splitext(self.source)[0] + "_frame.png"
            img = Image.open(self.source)
            img.seek(0)
            img.convert("RGB").save(out)
            return out
        return self.source

    def run(self):
        try:
            if self.api_key:
                os.environ["MODEL_API_KEY"] = self.api_key
            else:
                os.environ.pop("MODEL_API_KEY", None)
            from src import loop
            summary = loop.run(
                self._prepare_source(), self.output,
                on_progress=self.progress.emit, cancel=self.cancel_event,
                prepared_refs=self.prepared_refs,
                segment_prompt=self.segment_prompt,
                blend_file=self.blend_file)
            self.finished_ok.emit(summary)
        except Exception as e:
            self.failed.emit(str(e))
