import gi

from gi.repository import Gtk
from gaphor.core.modeling import ElementFactory
from gaphor.UML import Profile
from gaphor.transaction import Transaction
import xml.etree.ElementTree as ET



class MDImporter():
    def __init__(self, window, element_factory:ElementFactory, event_manager):
        self.window = window
        self.element_factory = element_factory
        self.event_manager = event_manager

    def open_file_dialog(self):
        dialog = Gtk.FileDialog.new()
        dialog.set_title("Select MagicDraw file")

        def response(dialog, result):
            if result.had_error():
                # File dialog was cancelled
                return

            file = dialog.open_finish(result)
            self.process_file(file)

        dialog.open(parent=self.window, cancellable=None, callback=response)

    def process_file(self, file):
        # Implement your file processing logic here
        # For demonstration, let's just display the contents of the selected file
        result, textIter = file.load_bytes()
        resultString = result.get_data().decode("utf-8")
        root = ET.fromstring(resultString)
        print(root.tag, root.attrib)
        attributes = root.attrib
        for key in attributes:
            print(key+" "+str(attributes[key])) 
        print("************************")
        for child in root:
            print(child.tag, child.attrib)
        self.create_mdimportprofile()

    def get_mdimportprofile(self) -> Profile:
        profiles = self.element_factory.select(Profile)
        for profile in profiles:
            if profile.name == "MDImportProfile":
                return profile
        return self.create_mdimportprofile()

    def create_mdimportprofile(self) -> Profile:  
        with Transaction(self.event_manager):
            profile = self.element_factory.create(Profile)
            profile.name = "MDImportProfile"
            return profile

 