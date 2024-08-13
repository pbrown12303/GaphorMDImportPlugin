import gi

from gi.repository import Gtk
from gaphor.core.modeling import ElementFactory
from gaphor.UML import Profile, Stereotype, Class, Extension, Property
from gaphor.transaction import Transaction
from gaphor.UML.recipes import create_extension
import xml.etree.ElementTree as ET



class MDImporter():
    def __init__(self, window, element_factory:ElementFactory, event_manager):
        self.window = window
        self.element_factory = element_factory
        self.event_manager = event_manager

    def import_md_model(self):
        self.open_file_dialog()
    
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
        result, textIter = file.load_bytes()
        resultString = result.get_data().decode("utf-8")
        root = ET.fromstring(resultString)
        with Transaction(self.event_manager):
            for child in root:
                if child.tag == "{http://www.omg.org/spec/UML/20131001}Profile":
                    self.import_Profile(child)
 
    def get_profile(self, name, id) -> Profile:  
        profile:Profile | None = None
        if id:
            profile = self.element_factory.lookup(id)
            if profile == None: 
                profile = self.element_factory.create_as(Profile, id=id)
        else:
            profile = self.element_factory.create(Profile)
        profile.name = name
        return profile

    def create_stereotype(self, name, id) -> Profile:  
        stereotype = self.element_factory.create_as(Stereotype, id)
        stereotype.name = name
        return stereotype
    
    def import_Profile(self, profile_element:ET.Element):
        name = profile_element.get("name")
        id = profile_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        profile = self.get_profile(name, id)
        for profile_child in profile_element.findall("packagedElement"):
            if profile_child.get("{http://www.omg.org/spec/XMI/20131001}type") == "uml:Stereotype":
                self.import_stereotype(profile_child, profile)

    def import_stereotype(self, stereotype_element:ET.Element, profile:Profile):
        stereotype_name = stereotype_element.get("name")
        stereotype_id = stereotype_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        stereotype = self.create_stereotype(stereotype_name, stereotype_id)
        stereotype.package = profile
        for stereotype_child in stereotype_element.findall("ownedAttribute"):
            print("property name: " + stereotype_child.get("name"))
            if stereotype_child.get("{http://www.omg.org/spec/XMI/20131001}type") == "uml:Property":
                propertyType = stereotype_child.find("type")
                typeReferent = propertyType.get("href")
                baseTypeName = typeReferent.split("#")[1]
                if stereotype_child.get("association") != None: 
                    # This is the base type of the stereotype, create an extension
                    found = False
                    for attribute in stereotype.ownedAttribute:
                        if attribute.name == "baseClass":
                            found = True
                    if found == False:
                        gaphor_metatype = self.get_referent_type(baseTypeName, profile)
                        create_extension(gaphor_metatype, stereotype)
                else:
                    # This is an attribute of the stereotype
                    found = False
                    for attribute in stereotype.ownedAttribute:
                        if attribute.name == stereotype_child.get("name"):
                            found = True
                    if found == False:
                        new_attribute = self.element_factory.create(Property)
                        new_attribute.name = stereotype_child.get("name")
                        stereotype.ownedAttribute = new_attribute
                        new_attribute.typeValue = baseTypeName





    def get_referent_type(self, referentTypeName, profile:Profile) -> Class:
        for child in profile.ownedElement:
            if child.name == referentTypeName and isinstance(child, Class):
                return child
        new_metatype = self.element_factory.create(Class)
        new_metatype.name = referentTypeName
        new_metatype.package = profile
        return new_metatype