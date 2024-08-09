import logging
import gi


from gaphor.abc import ActionProvider, Service
from gaphor.action import action
from gaphor.i18n import gettext


from gi.repository import Adw, Gtk

log = logging.getLogger(__name__)


class MDImportPlugin(Service, ActionProvider):

    def __init__(self, main_window, tools_menu, element_factory, event_manager):
        self.main_window = main_window
        tools_menu.add_actions(self)
        self.element_factory = element_factory
        self.event_manager = event_manager

    def shutdown(self):
        pass


    @action(
        name="mdimport",
        label=gettext("Import MD Model"),
        tooltip=gettext("This is the Import MD Model plugin!"),
    )
    def opwddProfile_action(self):
        global window
        window = self.main_window.window

        from gaphor_mdimport_plugin.mdimporter import MDImporter
        mdimporter = MDImporter(self.main_window.window, self.element_factory, self.event_manager)
        mdimporter.get_mdimportprofile()
        # open_file_dialog(window)

