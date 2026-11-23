"""PRISM toolbar bridge: everything the HTML chrome (ui/chrome.js) can call.

Only the toolbar page, which lives in its own privileged profile, gets this
object over QWebChannel; websites never do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from urls import NEWTAB_URL

if TYPE_CHECKING:
    from window import PrismWindow


class Bridge(QObject):
    stateChanged = pyqtSignal(str)
    toast = pyqtSignal(str)

    def __init__(self, window: "PrismWindow"):
        super().__init__(window)
        self.w = window

    @pyqtSlot()
    def ready(self): self.w.emit_state()

    @pyqtSlot(str)
    def navigate(self, text): self.w.navigate(text)

    @pyqtSlot()
    def back(self): self.w.current().view.back()

    @pyqtSlot()
    def forward(self): self.w.current().view.forward()

    @pyqtSlot()
    def reload(self): self.w.current().view.reload()

    @pyqtSlot()
    def stop(self): self.w.current().view.stop()

    @pyqtSlot()
    def home(self): self.w.current().view.setUrl(NEWTAB_URL)

    @pyqtSlot()
    def newTab(self): self.w.new_tab(NEWTAB_URL, focus_address=True, container=self.w.current().container)

    @pyqtSlot()
    def newTabMenu(self): self.w.new_tab_menu()

    @pyqtSlot(int)
    def tabMenu(self, tab_id): self.w.tab_menu(tab_id)

    @pyqtSlot(int)
    def closeTab(self, tab_id): self.w.close_tab(tab_id)

    @pyqtSlot(int)
    def switchTab(self, tab_id): self.w.switch_tab(tab_id)

    @pyqtSlot()
    def toggleShield(self): self.w.toggle_shield()

    @pyqtSlot()
    def purge(self): self.w.purge()

    @pyqtSlot()
    def devtools(self): self.w.toggle_devtools()

    @pyqtSlot()
    def split(self): self.w.open_split()

    @pyqtSlot()
    def inspector(self): self.w.toggle_inspector()

    @pyqtSlot(str)
    def panel(self, section): self.w.toggle_panel(section or None)

    @pyqtSlot()
    def responsive(self): self.w.toggle_responsive()

    @pyqtSlot(str, int, int)
    def setDevice(self, name, w, h): self.w.set_device(name, w, h)

    @pyqtSlot()
    def rotateDevice(self): self.w.rotate_device()

    @pyqtSlot(str, bool, bool)
    def answerPermission(self, prompt_id, allow, remember): self.w.answer_permission(prompt_id, allow, remember)

    @pyqtSlot()
    def sandboxJs(self): self.w.toggle_sandbox_js()

    @pyqtSlot()
    def containerMenu(self): self.w.container_menu()

    @pyqtSlot(str, bool)
    def find(self, text, backwards): self.w.find(text, backwards)

    @pyqtSlot()
    def findClose(self): self.w.close_find()

    @pyqtSlot()
    def focusPage(self): self.w.current().view.setFocus()

    @pyqtSlot(int)
    def setChromeHeight(self, h):
        if 20 <= h <= 400:
            self.w.chrome.setFixedHeight(h)
