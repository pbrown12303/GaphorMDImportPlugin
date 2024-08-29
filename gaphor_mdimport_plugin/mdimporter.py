import gi

from gi.repository import Gtk
from gaphor.core.modeling import ElementFactory
from gaphor.core.modeling.coremodel import Relationship
from gaphor.core.modeling.diagram import Diagram
from gaphor.core.modeling.coremodel import Comment
from gaphor.diagram.drop import drop 
from gaphor.UML import Abstraction, Actor, Association, Class, Classifier, DataType, Dependency, Enumeration, \
    EnumerationLiteral, Generalization, \
    Include, InstanceSpecification, \
    Interface, InterfaceRealization, Operation, \
    Package, Parameter, Profile, Property, Realization, Slot, Stereotype, UseCase 
from gaphor.transaction import Transaction
from gaphor.UML.recipes import create_extension
# from gaphor.extensions.ipython import auto_layout

from Lib.queue import Queue

import xml.etree.ElementTree as ET

class PendingEntry():
    def __init__(self, element:ET.Element, parent:ET.Element):
        self.element = element
        self.parent = parent

class ImportException(Exception):
    def __init__(self, message):
         self.message = message

class MDImporter():
    def __init__(self, window, element_factory:ElementFactory, event_manager):
        self.window = window
        self.element_factory = element_factory
        self.event_manager = event_manager
        self.pending_queue = Queue()
        self.diagram_queue = Queue()
        self.link_queue = Queue()
        self.diagram_reference_queue = Queue()

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
            # First we import any referenced profiles
            self.import_referenced_profiles(root)
            for child in root:
                if child.tag == "{http://www.omg.org/spec/UML/20131001}Profile":
                    self.import_Profile(child)
                elif child.tag == "{http://www.omg.org/spec/UML/20131001}Model":
                    self.import_Model(child)
            self.process_pending_queue()
            self.process_diagram_queue()
            self.process_diagram_reference_queue()

    def process_diagram_queue(self):
        while not self.diagram_queue.empty():
            entry = self.diagram_queue.get()
            element = entry.element
            match element.tag:
                case "ownedDiagram":
                    self.deferred_process_Diagram(element)
                case _:
                    raise ImportException("Element not processed in process_diagram_queue: " + element.tag)

    def process_diagram_reference_queue(self):
        while not self.diagram_reference_queue.empty():
            entry = self.diagram_reference_queue.get()
            element = entry.element
            diagram_element = entry.parent
            parent_id = diagram_element.get("{http://www.omg.org/spec/XMI/20131001}id")
            diagram = self.element_factory.lookup(parent_id)
            match element.tag:
                case "usedObjects":
                    used_object_id = element.get("href")[1:]
                    used_object = self.element_factory.lookup(used_object_id)
                    drop(used_object, diagram, x=0, y=0)

    def process_pending_queue(self):
        while not self.pending_queue.empty():
            entry = self.pending_queue.get()
            element = entry.element
            parent = entry.parent
            parent_id = None
            gaphor_parent = None
            if parent != None:
                parent_id = parent.get("{http://www.omg.org/spec/XMI/20131001}id")
                if parent_id != None:
                    gaphor_parent = self.element_factory.lookup(parent_id)
            match element.tag:
                case "client":
                    self.deferred_process_Dependency(element, gaphor_parent)
                case "classifier":
                    self.deferred_process_InstanceSpecification(element, gaphor_parent)
                case "generalization":
                    self.deferred_process_Generalization(element)
                case "include":
                    gaphor_parent_package = None
                    if gaphor_parent != None:
                        gaphor_parent_package = gaphor_parent.package
                    self.import_Include(element, gaphor_parent_package, gaphor_parent)
                case "interfaceRealization":
                    self.import_InterfaceRealization(element, gaphor_parent)
                case "memberEnd":
                    self.deferred_process_MemberEnd(element, gaphor_parent)
                case "ownedAttribute":
                    type = element.get("{http://www.omg.org/spec/XMI/20131001}type")
                    match type:
                        case "uml:Property":
                            self.deferred_process_Property(element)
                        case _:
                            print ("In process_pending_queue, ownedEnd type not handled for type: " + type)
                case "ownedEnd":
                    type = element.get("{http://www.omg.org/spec/XMI/20131001}type")
                    match type:
                        case "uml:Property":
                            self.deferred_process_Property(element)
                        case _:
                            print ("In process_pending_queue, ownedEnd type not handled for type: " + type)
                case "ownedParameter":
                    self.deferred_process_Parameter(element)
                case "supplier":
                    self.deferred_process_Dependency(element, gaphor_parent)
                case _:
                    print ("Element not processed in process_pending_queue: " + element.tag)
                    # raise ImportException("Element not processed in process_pending_queue: " + element.tag) 

    def deferred_process_Dependency(self, element:ET.Element, dependency:Dependency):
        if element.tag == "client":
            client_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
            client = self.element_factory.lookup(client_id)
            dependency.client = client
        elif element.tag == "supplier":
            supplier_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
            supplier = self.element_factory.lookup(supplier_id)
            dependency.supplier = supplier

    def deferred_process_Diagram(self, diagram_element:ET.Element):
        diagram_id = diagram_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        diagram = self.element_factory.lookup(diagram_id)
        if diagram == None:
            raise ImportException("Diagram not found in deferred_process_Diagram: " + diagram_id)
        representation_objects = diagram_element.iter("{http://www.nomagic.com/ns/magicdraw/core/diagram/1.0}DiagramRepresentationObject")
        for representation_object in representation_objects:
            diagram_type = representation_object.get("type")
            diagram.diagramType = diagram_type
            for used_object_element in representation_object.iter("usedObjects"):
                used_object_id = used_object_element.get("href")[1:]
                used_object = self.element_factory.lookup(used_object_id)
                if isinstance(used_object, Relationship):
                    entry = PendingEntry(used_object_element, None)
                    self.link_queue.put(entry)
                elif isinstance(used_object, Property): # skip properties
                    pass
                elif isinstance(used_object, Diagram):
                    if used_object_id != diagram_id:
                        entry = PendingEntry(used_object_element, diagram_element)
                        self.diagram_reference_queue.put(entry)
                else :
                    drop(used_object, diagram, x=0, y=0)
            while not self.link_queue.empty():
                queue_entry = self.link_queue.get()
                link_entry = queue_entry.element
                link_id = link_entry.get("href")[1:]
                link = self.element_factory.lookup(link_id)
                drop(link, diagram, x=0, y=0)
        # auto_layout(diagram)

    def deferred_process_Generalization(self, generalization_element:ET.Element):    
        generalization_id = generalization_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        generalization = self.element_factory.lookup(generalization_id)
        abstraction_id = generalization_element.get("general")
        abstraction = self.element_factory.lookup(abstraction_id)
        generalization.general = abstraction

    def deferred_process_InstanceSpecification(self, classifier_element:ET.Element, instance_specifiction:InstanceSpecification):
        raw_id = classifier_element.get("href")
        split_id = raw_id.split("#")
        if len(split_id) > 1:
            id = split_id[1]
        else:
            id = raw_id
        stereotype = self.element_factory.lookup(id)
        if stereotype == None:
            print ("Stereotype not found in deferred_process_InstanceSpecification: " + id)
        else:
            instance_specifiction.classifier = stereotype

    def deferred_process_MemberEnd(self, member_end_element:ET.Element, owner:Association):
        idref = member_end_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
        member_end = self.element_factory.lookup(idref)
        if member_end == None:
            print ("Member end not found in deferred_process_MemberEnd: " + idref)
            return
            # raise ImportException("Member end not found in deferred_process_MemberEnd: " + idref)
        owner.memberEnd = member_end

    def deferred_process_Parameter(self, element:ET.Element):
        parameter_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
        parameter = self.element_factory.lookup(parameter_id)
        type_id = element.get("type")
        if type_id != None:
            type = self.element_factory.lookup(type_id)
            parameter.type = type

    def deferred_process_Property(self, element:ET.Element):
        property_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
        property = self.element_factory.lookup(property_id)
        tag = element.tag
        match tag:
            case "ownedEnd":
                type_id = element.get("type")
                if type_id != None:
                    type = self.element_factory.lookup(type_id)
                    property.type = type
            case "ownedAttribute":
                association_id = element.get("association")
                if association_id != None:
                    association = self.element_factory.lookup(association_id)
                    if association == None:
                        print ("Association not found in deferred_process_Property: " + association_id)
                    else:
                        property.association = association
                type_id = element.get("type")
                if type_id == None:
                    for child in element:
                        if child.tag == "type":
                            type_reference = child.get("href")
                            match type_reference:
                                case 'http://www.omg.org/spec/UML/20131001/PrimitiveTypes.xmi#String':
                                    property.typeValue = "String"
                                case 'http://www.omg.org/spec/UML/20131001/PrimitiveTypes.xmi#Integer':
                                    property.typeValue = "Integer"
                                case 'http://www.omg.org/spec/UML/20131001/PrimitiveTypes.xmi#Boolean':
                                    property.typeValue = "Boolean"
                                case 'http://www.omg.org/spec/UML/20131001/PrimitiveTypes.xmi#Real':
                                    property.typeValue = "Real"
                                case 'http://www.omg.org/spec/UML/20131001/PrimitiveTypes.xmi#UnlimitedNatural':
                                    property.typeValue = "UnlimitedNatural"
                else:
                    type = self.element_factory.lookup(type_id)
                    property.type  = type
                lower_value_iterator = element.iter("lowerValue") 
                lower_value = next(lower_value_iterator, None)
                if lower_value != None:
                    value = lower_value.get("value")
                    if value != None:
                        property.lowerValue = value
                    else:
                        property.lowerValue = "0"
                upper_value_iterator = element.iter("upperValue")
                upper_value = next(upper_value_iterator, None)  
                if upper_value != None:
                    value = upper_value.get("value")
                    if value != None:
                        property.upperValue = value

    def get_abstraction(self, id, owner:Package, element:ET.Element) -> Abstraction:
        assert id != None
        abstraction = self.element_factory.lookup(id)
        if abstraction == None:
            abstraction = self.element_factory.create_as(Abstraction, id)
            for child in element:
                pending_queue_entry = PendingEntry(child, element)
                self.pending_queue.put(pending_queue_entry)
        return abstraction

    def get_actor(self, name, id, owner:Package) -> Actor:
        assert id != None
        actor = self.element_factory.lookup(id)
        if actor == None:
            actor = self.element_factory.create_as(id)
            actor.name = name
            actor.package = owner
        return actor

    def get_association(self, id, owner:Package | Class | None, element: ET.Element) -> Association:
        assert id != None
        association = self.element_factory.lookup(id)
        if association == None:
            association = self.element_factory.create_as(Association, id=id)
            if isinstance(owner, Package):
                association.package = owner
            elif isinstance(owner, Class):
                association.nestingClass = owner
            name = element.get("name")
            if name != None:
                association.name = name
            for child in element:
                tag = child.tag
                match tag:
                    case "memberEnd":
                        self.pending_queue.put(PendingEntry(child, element))
                    case "ownedEnd":
                        self.import_OwnedEnd(child, association)
                        # self.pending_queue.put(PendingEntry(child, packaged_element))
                    case "navigableOwnedEnd":
                        # TODO implement navigableOwnedEnd
                        print ("Import of packaged element Association child not processed for tag: " + tag)
                    case "ownedRule":
                        # TODO implement ownedRule
                        print ("Import of packaged element Association child not processed for tag: " + tag)
                    case "ownedComment":
                        self.import_OwnedComment(child, association)
                    case _:
                        raise ImportException("Import of packaged element Association child not processed for tag: " + tag)
        return association

    def get_class(self, name, id, owner:Package | Class, xml_element:ET.Element) -> Class:
        assert id != None
        uml_class:Class | None = None
        uml_class = self.element_factory.lookup(id)
        if uml_class == None: 
            uml_class = self.element_factory.create_as(Class, id=id)
            if owner != None: 
                if isinstance(owner, Package):
                    uml_class.package = owner
                elif isinstance(owner, Class):
                    owner.nestedClassifier = uml_class
            uml_class.name = name
            isAbstract = xml_element.get("isAbstract")
            if isAbstract == "true":
                uml_class.isAbstract = True
            isLeaf = xml_element.get("isLeaf")
            if isLeaf == "true":
                uml_class.isLeaf = True
            # TODO implement isFinalSpecialization after gaphor model is updated
            # isFinalSpecialization = xml_element.get("isFinalSpecialization")
            # if isFinalSpecialization == "true":
            #     uml_class.isFinalSpecialization = True
            visibility = xml_element.get("visibility")
            if visibility != None:
                uml_class.visibility = visibility
            for child in xml_element:
                tag = child.tag
                match tag:
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        # TODO implement Extension
                        print ("Import of packaged element Class child not processed for tag: " + tag)
                    case "generalization":
                        generalization_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                        generalization = self.get_generalization(generalization_id, uml_class)
                        pending_queue_entry = PendingEntry(child, xml_element)  
                        self.pending_queue.put(pending_queue_entry)
                    case "interfaceRealization":
                        pending_queue_entry = PendingEntry(child, xml_element)
                        self.pending_queue.put(pending_queue_entry)
                    case "nestedClassifier":
                        self.import_NestedClassifier(child, uml_class)
                    case "ownedAttribute":
                        self.import_OwnedAttribute(child, uml_class)
                    case "ownedComment":
                        self.import_OwnedComment(child, uml_class)
                    case "ownedConnector":
                        # TODO implement ownedConnector
                        print ("Import of packaged element Class child not processed for tag: " + tag)
                    case "ownedOperation":
                        self.import_OwnedOperation(child, uml_class)
                    case "ownedRule":
                        # TODO implement ownedRule
                        print ("Import of packaged element Class child not processed for tag: " + tag)
                    case "ownedTemplateSignature":
                        # TODO implement ownedTemplateSignature
                        print ("Import of packaged element Class child not processed for tag: " + tag)
                    case "templateBinding":
                        # TODO implement templateBinding
                        print ("Import of packaged element Class child not processed for tag: " + tag)
                    case _:
                        print ("Import of packaged element Class child not processed for tag: " + tag)
                        # raise ImportException("Import of packaged element Class child not processed for tag: " + tag)
        return uml_class

    def get_datatype(self, name, id, owner:Package | None) -> DataType:
        assert id != None
        datatype:DataType | None = None
        datatype = self.element_factory.lookup(id)
        if datatype == None: 
            datatype = self.element_factory.create_as(DataType, id=id)
            if owner != None:
                datatype.package = owner
        datatype.name = name
        return datatype

    def get_dependency(self, id, element:ET.Element) -> Dependency:
        assert id != None
        dependency = self.element_factory.lookup(id)
        if dependency == None:
            dependency = self.element_factory.create_as(Dependency, id)
            for child in element:
                pending_queue_entry = PendingEntry(child, element)
                self.pending_queue.put(pending_queue_entry)
        return dependency

    def get_diagram(self, name, id, owner:Package | None , element:ET.Element) -> Diagram:
        assert id != None
        diagram = self.element_factory.lookup(id)
        if diagram == None:
            diagram = self.element_factory.create_as(Diagram, id=id)
            diagram.name = name
            if owner != None:
                owner.ownedDiagram = diagram
            pending_diagram_entry = PendingEntry(element, None)
            self.diagram_queue.put(pending_diagram_entry)
        return diagram

    def get_enumeration(self, name, id, owner:Package) -> Enumeration:
        assert id != None
        enumeration:Enumeration | None = None
        enumeration = self.element_factory.lookup(id)
        if enumeration == None:
            enumeration = self.element_factory.create_as(Enumeration, id)
            enumeration.package = owner
            enumeration.name = name
        return enumeration

    def get_enumerationLiteral(self, name, id, owner:Enumeration) -> EnumerationLiteral:
        assert id != None
        enumerationLiteral = self.element_factory.lookup(id)
        if enumerationLiteral == None:
            enumerationLiteral = self.element_factory.create_as(EnumerationLiteral, id)
            enumerationLiteral.enumeration = owner
            enumerationLiteral.name = name
        return enumerationLiteral

    def get_generalization(self, id, owner:Class) -> Generalization:
        assert id != None
        generalization = self.element_factory.lookup(id)
        if generalization == None:
            generalization = self.element_factory.create_as(Generalization, id)
            owner.generalization = generalization
        return generalization

    def get_include(self, id, owner:Package) -> Include:
        assert id != None
        include = self.element_factory.lookup(id)
        if include == None:
            include = self.element_factory.create_as(Include, id)
        return include

    def get_instanceSpecification(self, id, owner:Package, element:ET.Element) -> InstanceSpecification:
        assert id != None
        instanceSpecification = self.element_factory.lookup(id)
        if instanceSpecification == None:
            instanceSpecification = self.element_factory.create_as(InstanceSpecification, id)
            owner.appliedStereotype = instanceSpecification
            for child in element:
                tag = child.tag
                match tag:
                    case "classifier":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "slot":
                        slot = self.get_slot(child, instanceSpecification)
                    case _:
                        print ("Import of packaged element InstanceSpecification child not processed for tag: " + tag)
                        # raise ImportException("Import of packaged element InstanceSpecification child not processed for tag: " + tag)
        return instanceSpecification

    def get_interface(self, name, id, owner:Package | None) -> Interface:
        assert id != None
        interface:Interface | None = None
        interface = self.element_factory.lookup(id)
        if interface == None:
            interface = self.element_factory.create_as(Interface, id=id)
            if owner != None:
                interface.package = owner
            interface.name = name
        return interface

    def get_interfaceRealization(self, id, owner:Class, element:ET.Element) -> InterfaceRealization:
        assert id != None
        interfaceRealization = self.element_factory.lookup(id)
        if interfaceRealization == None:
            interface_realization = self.element_factory.create_as(InterfaceRealization, id)
            interface_realization.implementatingClassifier = owner
            # TODO fix the following after the spelling has been corrected in the gaphor model
            interface_realization.implementatingClassifier = owner
            contract_id = element.get("contract")
            contract = self.element_factory.lookup(contract_id)
            interface_realization.contract = contract
            for child in element:
                tag = child.tag
                match tag:
                    case "client":
                        client_id = child.get("{http://www.omg.org/spec/XMI/20131001}idref")
                        client = self.element_factory.lookup(client_id)
                        interface_realization.client = client
                    case "supplier":
                        supplier_id = child.get("{http://www.omg.org/spec/XMI/20131001}idref")
                        supplier = self.element_factory.lookup(supplier_id)
                        interface_realization.supplier = supplier
                    case _:
                        print ("Import of interface realization child not processed for tag: " + tag)
        return interfaceRealization

    # def get_literalString(self, name, id, owner:Package | None) -> LiteralString: 
    #     literalString:LiteralString | None = None
    #     if id:
    #         literalString = self.element_factory.lookup(id)
    #         if literalString == None:
    #             literalString = self.element_factory.create_as(LiteralString, id=id)
    #             if owner != None:
    #                 literalString.package = owner
    #             literalString.name = name
    #     return literalString

    def get_operation(self, name, id, owner:Interface, element:ET.Element ) -> Operation:
        assert id != None
        operation = self.element_factory.lookup(id)
        if operation == None:
            operation = self.element_factory.create_as(Operation, id=id)
            owner.ownedOperation = operation
            operation.name = name
            visibility = element.get("visibility")
            if visibility != None:
                operation.visibility = visibility
            isAbstract = element.get("isAbstract")
            if isAbstract == "true":
                operation.isAbstract = True
            for child in element:
                tag = child.tag
                match tag:
                    case "ownedParameter":
                        self.import_OwnedParameter(child, operation)
                    case "ownedComment":
                        self.import_OwnedComment(child, operation)
                    case _:
                        print ("Import of owned operation child not processed for tag: " + tag)
        return operation

    def get_package(self, name, id, owner:Package | None) -> Package:
        assert id != None
        package = self.element_factory.lookup(id)
        if package == None: 
            package = self.element_factory.create_as(Package, id=id)
            if owner != None:
                package.package = owner
            package.name = name
        return package

    def get_parameter(self, name, id, owner:Operation, element:ET.Element) -> Parameter:
        assert id != None
        parameter = self.element_factory.lookup(id)
        if parameter == None:
            parameter = self.element_factory.create_as(Parameter, id)
            owner.ownedParameter = parameter
            parameter.name = name
            visibility = element.get("visibility")
            if visibility != None:
                parameter.visibility = visibility
            direction = element.get("direction")
            if direction != None:
                parameter.direction = direction
            pending_queue_entry = PendingEntry(element, None)
            self.pending_queue.put(pending_queue_entry)

        return parameter


    def get_profile(self, name, id) -> Profile:  
        profile:Profile | None = None
        if id:
            profile = self.element_factory.lookup(id)
            if profile == None: 
                profile = self.element_factory.create_as(Profile, id=id)
                profile.name = name
        else:
            profiles = self.element_factory.lselect(Profile)
            for profile in profiles:
                if profile.name == name:
                    return profile  
            profile = self.element_factory.create(Profile)
            profile.name = name
        return profile

    def get_property(self, name, owner:Class | Association, id, element:ET.Element) -> Property:
        assert id != None
        property = self.element_factory.lookup(id)
        if property == None:
            property = self.element_factory.create_as(Property, id)
            if name != None:
                property.name = name
            visibility = element.get("visibility")
            if visibility != None:
                property.visibility = visibility
            isStatic = element.get("isStatic")
            if isStatic == "true":
                property.isStatic = True
            isReadOnly = element.get("isReadOnly")
            if isReadOnly == "true":
                property.isReadOnly = True
            if isinstance(owner, Class):
                owner.ownedAttribute = property
            pending_queue_entry = PendingEntry(element, None)
            self.pending_queue.put(pending_queue_entry)
        return property

    def get_realization(self, id, owner:Package, element:ET.Element) -> Realization:
        assert id != None
        realization = self.element_factory.lookup(id)
        if realization == None:
            realization = self.element_factory.create_as(Realization, id)
            for child in element:
                pending_queue_entry = PendingEntry(child, element)
                self.pending_queue.put(pending_queue_entry)
        return realization

    def get_referent_type(self, referentTypeName, profile:Profile) -> Class:
        for child in profile.ownedElement:
            if child.name == referentTypeName and isinstance(child, Class):
                return child
        new_metatype = self.element_factory.create(Class)
        new_metatype.name = referentTypeName
        new_metatype.package = profile
        return new_metatype

    def get_slot(self, element:ET.Element, owner:InstanceSpecification) -> Slot:
        id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
        slot = self.element_factory.lookup(id)
        if slot == None:
            slot = self.element_factory.create_as(Slot, id)
            defining_feature_element = element.find("definingFeature")
            defining_feature_full_id = defining_feature_element.get("href")
            defining_feature_id = defining_feature_full_id.split("#")[1]
            defining_feature = self.element_factory.lookup(defining_feature_id)
            slot.definingFeature = defining_feature
            owner.slot = slot
            value_element = element.find("value")
            if value_element != None:
                value = value_element.get("value")
                if value != None:
                    slot.value = value
            # TODO implement value type after gaphor model is updated with LiteralString and other value types
        return slot

    def get_stereotype(self, name, id, owner:Package) -> Stereotype:  
        assert id != None
        stereotype = self.element_factory.lookup(id)
        if stereotype == None:
            stereotype = self.element_factory.create_as(Stereotype, id)
            stereotype.name = name
            stereotype.package = owner
        return stereotype
    
    def get_use_case(self, name, id, owner:Package | None) -> UseCase | None:
        assert id != None
        use_case = self.element_factory.lookup(id)
        if use_case == None: 
            use_case = self.element_factory.create_as(UseCase, id=id)
            if owner != None:
                use_case.package = owner
            use_case.name = name
        return use_case

    def import_Abstraction(self, abstraction_element:ET.Element, owner:Package):
        id = abstraction_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        abstraction = self.get_abstraction(id, owner, abstraction_element)

    def import_Include(self, include_element:ET.Element, owner:Package | None, use_case:UseCase):
        included_use_case_id = include_element.get("addition")
        included_use_case = self.element_factory.lookup(included_use_case_id)
        if included_use_case_id == None:
            raise ImportException("Included use case not found in import_Include: " + included_use_case_id)
        include_id = include_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        include = self.get_include(include_id, owner)
        include.addition = included_use_case
        include.includingCase = use_case

    def import_InterfaceRealization(self, interface_realization_element:ET.Element, owner:Class):
        id = interface_realization_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        interface_realization = self.get_interfaceRealization(id, owner, interface_realization_element)

    def import_Model(self, lib_element:ET.Element):
        model_name = lib_element.get("name")
        model_id = lib_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        model = self.get_package(model_name, model_id, None)
        for child in lib_element:
            tag = child.tag
            match tag:
                case "ownedComment":
                    self.import_OwnedComment(child, model)
                case "packagedElement":
                    self.import_PackagedElement(child, model)
                case '{http://www.omg.org/spec/XMI/20131001}Extension':
                    owned_diagram_elements = child.iter("ownedDiagram")
                    for owned_diagram_element in owned_diagram_elements:
                        diagram_id = owned_diagram_element.get("{http://www.omg.org/spec/XMI/20131001}id")
                        name = owned_diagram_element.get("name")
                        diagram = self.get_diagram(name, diagram_id, None , owned_diagram_element)

    def import_NestedClassifier(self, nested_classifier_element:ET.Element, owner:Class):
        name = nested_classifier_element.get("name")
        id = nested_classifier_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        elementType = nested_classifier_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match elementType:
            case "uml:Association":
                association = self.get_association(id, owner, nested_classifier_element)
            case "uml:Class":
                uml_class = self.get_class(name, id, owner, nested_classifier_element)
            case _:
                print ("Import of nested classifier not processed for element type: " + elementType)
                # raise ImportException("Import of nested classifier not processed for element type: " + elementType)
    
    def import_OwnedAttribute(self, ownedAttribute_element:ET.Element, owner:Class):
        id = ownedAttribute_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = ownedAttribute_element.get("name")
        attribute_type = ownedAttribute_element.get("{http://www.omg.org/spec/XMI/20131001}type")   
        match attribute_type:
            case "uml:Property":
                self.get_property(name, owner, id, ownedAttribute_element)

    def import_OwnedComment(self, ownedComment_element:ET.Element, owner:Package | Class | UseCase | Association | None):
        body = ownedComment_element.get("body")
        comment = self.element_factory.create(Comment)
        comment.body = body
        comment.annotatedElement = owner
        owner.comment = comment

    def import_OwnedEnd(self, ownedEnd_element:ET.Element, owner:Association):
        id = ownedEnd_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        owned_end_type = ownedEnd_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match owned_end_type:
            case "uml:Property":
                property = self.get_property(None, owner, id, ownedEnd_element) 
                owner.ownedEnd = property   

    def import_OwnedLiteral(self, ownedLiteral_element:ET.Element, owner:Enumeration) -> EnumerationLiteral:
        id = ownedLiteral_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        literalType = ownedLiteral_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        name = ownedLiteral_element.get("name")
        match literalType:
            case "uml:EnumerationLiteral":
                enumerationLiteral = self.get_enumerationLiteral(name, id, owner)
            case _:
                print("import_OwnedLiteral called with unhandled type: " + literalType)

    def import_OwnedOperation(self, ownedOperation_element:ET.Element, owner:Interface):
        id = ownedOperation_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = ownedOperation_element.get("name")
        operation = self.get_operation(name, id, owner, ownedOperation_element)

    def import_OwnedParameter(self, ownedParameter_element:ET.Element, owner:Operation):
        id = ownedParameter_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = ownedParameter_element.get("name")
        parameter = self.get_parameter(name, id, owner, ownedParameter_element)

    def import_PackagedElement(self, packaged_element:ET.Element, owner:Package | None):
        name = packaged_element.get("name")
        id = packaged_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        elementType = packaged_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match elementType:
            case "uml:Abstraction":
                self.import_Abstraction(packaged_element, owner)
            case "uml:Actor":
                self.get_actor(name, id, owner)
            case "uml:Association":
                association = self.get_association(id, owner, packaged_element)
            case "uml:Class":
                uml_class = self.get_class(name, id, owner, packaged_element)
            case "uml:Component":
                # TODO implement uml:Component
                print ("Import of packaged element Component not implemented")
            case "uml:DataType":
                self.get_datatype(name, id, owner)
            case "uml:Dependency":
                dependency = self.get_dependency(id, packaged_element)
            case "uml:Enumeration":
                enumeration = self.get_enumeration(name, id, owner)
                for child in packaged_element:
                    tag = child.tag
                    match tag:
                        case "ownedLiteral":
                            self.import_OwnedLiteral(child, enumeration)
            case "uml:Generalization":
                generalization = self.get_generalization(id, owner)
                pending_queue_entry = PendingEntry(packaged_element, None)
                self.pending_queue.put(pending_queue_entry)
            case "uml:InformationFlow":
                # TODO implement uml:InformationFlow
                print ("Import of packaged element InformationFlow not implemented")
            case "uml:InstanceSpecification":
                instanceSpecification = self.get_instanceSpecification(id, owner, packaged_element)
            case "uml:Interface":
                interface = self.get_interface(name, id, owner)
                isAbstract = packaged_element.get("isAbstract")
                if isAbstract != None:
                    if isAbstract == "true":
                        interface.isAbstract = True
                    else:
                        interface.isAbstract = False
                for child in packaged_element:
                    tag = child.tag
                    match tag:
                        case "ownedAttribute":
                            self.import_OwnedAttribute(child, interface)
                        case "ownedComment":
                            self.import_OwnedComment(child, interface)
                        case "ownedOperation":
                            self.import_OwnedOperation(child, interface)
                        case _:
                            print ("Import of packaged element Interface child not processed for tag: " + tag)
                            # raise ImportException("Import of packaged element Interface child not processed for tag: " + tag)
            case "uml:LiteralString":
                # TODO implement uml:LiteralString - intentionally ignored for now
                # self.get_literalString(name, id, owner)
                pass
            case "uml:Package":  
                package = self.get_package(name, id, owner)
                for child in packaged_element:
                    tag = child.tag
                    match tag:
                        case "ownedComment":
                            self.import_OwnedComment(child, package)
                        case "packagedElement":
                            self.import_PackagedElement(child, package)
                        case '{http://www.omg.org/spec/XMI/20131001}Extension':
                            owned_diagram_elements = child.iter("ownedDiagram")
                            for owned_diagram_element in owned_diagram_elements:
                                diagram_id = owned_diagram_element.get("{http://www.omg.org/spec/XMI/20131001}id")
                                name = owned_diagram_element.get("name")
                                diagram = self.get_diagram(name, diagram_id, package, owned_diagram_element)
                        case _:
                            raise ImportException("Import of packaged element Package child not processed for tag: " + tag)
            case "uml:Realization":
                realization = self.get_realization(id, owner, packaged_element)
            case "uml:TimeEvent":
                # TODO implement uml:TimeEvent
                print ("Import of packaged element TimeEvent not implemented")
            case "uml:Usage":
                # TODO implement uml:Usage
                print ("Import of packaged element Usage not implemented")
            case "uml:UseCase":
                use_case = self.get_use_case(name, id, owner)
                for child in packaged_element:
                    tag = child.tag
                    match tag:
                        case "include":
                            pending_queue_entry = PendingEntry(child, packaged_element)
                            self.pending_queue.put(pending_queue_entry)
                        case "ownedBehavior":
                            # TODO implement ownedBehavior
                            print ("Import of packaged element UseCase child not processed for tag: " + tag)
                        case "ownedUseCase":
                            # TODO implement ownedUseCase
                            print ("Import of packaged element UseCase child not processed for tag: " + tag)
                        case "ownedComment":
                            self.import_OwnedComment(child, use_case)
                        case "{http://www.omg.org/spec/XMI/20131001}Extension":
                            # TODO implement Extension
                            print ("Import of packaged element UseCase child not processed for tag: " + tag)
                        case _:
                            print ("Import of packaged element UseCase child not processed for tag: " + tag)
                            # raise ImportException("Import of packaged element UseCase child not processed for tag: " + tag)
            case _:
                print ("Import of packaged element not processed for element type: " + elementType)
#                raise ImportException("Import of packaged element not processed for element type: " + elementType)
                   
    def import_Profile(self, profile_element:ET.Element):
        name = profile_element.get("name")
        id = profile_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        profile = self.get_profile(name, id)
        for profile_child in profile_element.findall("packagedElement"):
            if profile_child.get("{http://www.omg.org/spec/XMI/20131001}type") == "uml:Stereotype":
                self.import_stereotype(profile_child, profile)

    def import_referenced_profiles(self, lib_element:ET.Element):
        stereotyp_hrefs = lib_element.iter("stereotypesHREFS")
        stereotype_dictionary = {}
        for stereotype_href in stereotyp_hrefs:
            stereotype_elements = stereotype_href.findall("stereotype")
            for stereotype_element in stereotype_elements:
                full_name = stereotype_element.get("name")
                split_name = full_name.split(":")
                profile_name = split_name[0]
                stereotype_name = split_name[1]
                profile = self.get_profile(profile_name, None)
                stereotypeHREF = stereotype_element.get("stereotypeHREF")
                stereotype_id = stereotypeHREF.split("#")[1]
                stereotype = self.get_stereotype(stereotype_name, stereotype_id, profile)
                stereotype_dictionary[full_name] = stereotype
                # Since we don't know the type to which the stereotype may be applied, we will create it as an extension of Element
                gaphor_metatype = self.get_referent_type("Element", profile) 
                extension = create_extension(gaphor_metatype, stereotype)
                extension.package = profile
            tag_elements = stereotype_href.findall("tag")
            for tag_element in tag_elements:
                tag_full_name = tag_element.get("name")
                split_full_name = tag_full_name.split(":")
                profile_name = split_full_name[0]
                stereotype_name = split_full_name[1]
                tag_name = split_full_name[2]
                stereotype = stereotype_dictionary[profile_name + ":" + stereotype_name]
                tag_full_id = tag_element.get("tagURI")
                tag_id = tag_full_id.split("#")[1]
                found = False
                for attribute in stereotype.ownedAttribute:
                    if attribute.name == tag_name:
                        found = True
                if found == False:
                    new_attribute = self.element_factory.create(Property)
                    new_attribute.name = tag_name
                    stereotype.ownedAttribute = new_attribute
        for child in lib_element:
            if child.tag == "referencedProfile":
                profile_id = child.get("{http://www.omg.org/spec/XMI/20131001}idref")
                profile = self.element_factory.lookup(profile_id)
                if profile == None:
                    raise ImportException("Referenced profile not found in import_referenced_profiles: " + profile_id)
                self.import_Profile(profile)

    def import_stereotype(self, stereotype_element:ET.Element, profile:Profile):
        stereotype_name = stereotype_element.get("name")
        stereotype_id = stereotype_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        stereotype = self.get_stereotype(stereotype_name, stereotype_id, profile)
        for stereotype_child in stereotype_element.findall("ownedAttribute"):
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
                        extension = create_extension(gaphor_metatype, stereotype)
                        extension.package = profile
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

    def pending_import_use_case(self, entry:PendingEntry):
        element = entry.element
        parent = entry.parent
        use_case_id = parent.get("{http://www.omg.org/spec/XMI/20131001}id")
        use_case = self.element_factory.lookup(use_case_id)
        if use_case == None:
            raise ImportException("Use case not found in pending_import_use_case")
            return
        use_case_package = use_case.package
        for child in element:
            if child.tag == "include":
                self.import_Include(child, element, use_case_package, use_case)
