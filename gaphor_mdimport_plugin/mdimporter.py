import gi
import os

import math
from decimal import Decimal as UnlimitedNatural
from gi.repository import Gtk
from gaphor.core.modeling import ElementFactory
from gaphor.diagram.drop import drop 
from gaphor.diagram.tools.txtool import TxData
from gaphor.UML import Abstraction, AcceptEventAction, Activity, ActivityEdge, ActivityFinalNode, ActivityNode, ActivityParameterNode, \
    ActivityPartition, Actor, Association, Behavior, CallAction, CallBehaviorAction, Class, Collaboration, Comment, ControlFlow, \
    Constraint, DataType, DecisionNode, Dependency, Diagram, ElementImport, Enumeration, \
    EnumerationLiteral, Event, Extend, Extension, ExtensionEnd, ExtensionPoint, FlowFinalNode, FinalState, ForkNode, Generalization, \
    Include, InitialNode, InputPin, InstanceSpecification, \
    Interaction, Interface, InterfaceRealization, JoinNode, LiteralBoolean, LiteralInteger, LiteralString, LiteralUnlimitedNatural, MergeNode, \
    Namespace, ObjectFlow, ObjectNode, OpaqueAction, OpaqueBehavior, Operation, OutputPin, \
    Package, Parameter, Pin, PrimitiveType, Profile, Property, Pseudostate, Realization, Region, \
    Relationship, SendSignalAction, Slot, State, StateMachine, Stereotype, Trigger, UseCase, ValueSpecification 
from gaphor.transaction import Transaction
from gaphor.UML.recipes import create_extension
from gaphor.plugins.autolayout import AutoLayout

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
        self.partition_node_queue = Queue()
        self.pin_queue = Queue()
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
            file_result, textIter = file.load_bytes()
            file_result_string = file_result.get_data().decode("utf-8")

            # Before we process the file, we need to import the UML Standard Profile
            uml_profile_file = open("./gaphor_mdimport_plugin/profiles/com.nomagic.magicdraw.uml_model.shared_model")
            uml_profile_file_contents = uml_profile_file.read()
            self.process_file_contents(uml_profile_file_contents)
            uml_profile_file.close()

            self.process_file_contents(file_result_string)

        dialog.open(parent=self.window, cancellable=None, callback=response)

    def process_file_contents(self, resultString):
        root = ET.fromstring(resultString)
        txData = TxData(self.event_manager)
        with Transaction(self.event_manager) as ctx:
            # First we import any referenced profiles
            # self.import_referenced_profiles(root)
            for child in root:
                if child.tag == "{http://www.omg.org/spec/UML/20131001}Package":
                    self.import_Package(child, None)
                elif child.tag == "{http://www.omg.org/spec/UML/20131001}Model":
                    self.import_Model(child, None)
            self.process_pending_queue()
            self.process_diagram_queue()
            self.process_diagram_reference_queue()
            self.layout_diagrams()

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
                    assert used_object != None
                    if isinstance(used_object, ActivityNode) and used_object.inPartition != None:
                        continue
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
                case "constrainedElement":
                    target_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                    target = self.element_factory.lookup(target_id)
                    if target != None:
                        gaphor_parent.constrainedElement = target
                case "elementImport":
                    element_import_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
                    element_import = self.element_factory.lookup(element_import_id)
                    imported_element_id = element.get("importedElement")
                    imported_element = self.element_factory.lookup(imported_element_id)
                    if imported_element == None:
                        print("Imported Element not found for ElementImport with ID: " + element_import_id)
                    else:
                        element_import.importedElement = imported_element
                case "extend":
                    extend_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
                    extend = self.element_factory.lookup(extend_id)
                    extended_case_id = element.get("extendedCase")
                    extended_case = self.element_factory.lookup(extended_case_id)
                    extend.extendedCase = extended_case
                case "extension":
                    extension_point_id = parent.get("{http://www.omg.org/spec/XMI/20131001}id")
                    extension_point = self.element_factory.lookup(extension_point_id)
                    extension_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                    extension = self.element_factory.lookup(extension_id)
                    extension.extensionLocation = extension_point
                case "extensionLocation":
                    extend_id = parent.get("{http://www.omg.org/spec/XMI/20131001}id")
                    extend = self.element_factory.lookup(extend_id)
                    extension_point_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                    extension_point = self.element_factory.lookup(extension_point_id)
                    if extension_point != None:
                        extend.extensionLocation = extension_point
                case "generalization":
                    self.deferred_process_Generalization(element)
                case "include":
                    gaphor_parent_package = None
                    if gaphor_parent != None:
                        gaphor_parent_package = gaphor_parent.package
                    self.import_Include(element, gaphor_parent_package, gaphor_parent)
                case "inPartition":
                    partition_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                    partition = self.element_factory.lookup(partition_id)
                    gaphor_parent.inPartition = partition
                case "interfaceRealization":
                    self.import_InterfaceRealization(element, gaphor_parent)
                case "memberEnd":
                    self.deferred_process_MemberEnd(element, gaphor_parent)
                case "navigableOwnedEnd":
                    self.deferred_process_NavigibleOwnedEnd(element, gaphor_parent)    
                case "node":
                    node_type = element.get("{http://www.omg.org/spec/XMI/20131001}type")
                    match node_type:
                        case "uml:ActivityParameterNode":
                            activity_parameter_node_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
                            activity_parameter_node = self.element_factory.lookup(activity_parameter_node_id)   
                            parameter_id = element.get("parameter")
                            parameter = self.element_factory.lookup(parameter_id)
                            activity_parameter_node.parameter = parameter
                        case "uml:CentralBufferNode":
                            # TODO update data type to CentralBufferNode after it is added to Gaphor model
                            central_buffer_node_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
                            central_buffer_node = self.element_factory.lookup(central_buffer_node_id)
                            type_id = element.get("type")
                            type = self.element_factory.lookup(type_id)
                            central_buffer_node.type = type
                            # TODO implement inState attribute after it is added to Gaphor model
                        case _:
                            print ("Deferred processing of activity node not processed for node type: " + node_type)    
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
                case "precondition":
                    precondition_id = element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                    precondition = self.element_factory.lookup(precondition_id)
                    parent.precondition = precondition
                case "supplier":
                    self.deferred_process_Dependency(element, gaphor_parent)
                case "trigger":
                    trigger_id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
                    trigger = self.element_factory.lookup(trigger_id)
                    assert trigger != None
                    event_id = element.get("event")
                    event = self.element_factory.lookup(event_id)
                    if event != None:
                        trigger.event = event
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
                if used_object == None:
                    continue
                elif isinstance(used_object, Pin):
                    entry = PendingEntry(used_object_element, None)
                    self.pin_queue.put(entry)
                elif isinstance(used_object, Relationship) or isinstance(used_object, ActivityEdge):
                    entry = PendingEntry(used_object_element, None)
                    self.link_queue.put(entry)
                elif isinstance(used_object, Property): # skip properties
                    pass
                elif isinstance(used_object, Diagram):
                    if used_object_id != diagram_id:
                        entry = PendingEntry(used_object_element, diagram_element)
                        self.diagram_reference_queue.put(entry)
                elif isinstance(used_object, ActivityNode) and used_object.inPartition != None:
                    entry = PendingEntry(used_object_element, None)
                    self.partition_node_queue.put(entry)
                else :
                    drop(used_object, diagram, x=0, y=0)
            while not self.partition_node_queue.empty():
                queue_entry = self.partition_node_queue.get()
                partition_node_entry = queue_entry.element
                partition_node_id = partition_node_entry.get("href")[1:]
                partition_node = self.element_factory.lookup(partition_node_id)
                drop(partition_node, diagram, x=0, y=0)
            while not self.pin_queue.empty():
                queue_entry = self.pin_queue.get()
                pin_entry = queue_entry.element
                pin_id = pin_entry.get("href")[1:]
                pin = self.element_factory.lookup(pin_id)
                drop(pin, diagram, x=0, y=0)
            while not self.link_queue.empty():
                queue_entry = self.link_queue.get()
                link_entry = queue_entry.element
                link_id = link_entry.get("href")[1:]
                link = self.element_factory.lookup(link_id)
                if link == None:
                    print ("Link not found in deferred_process_Diagram: " + link_id)
                    continue
                drop(link, diagram, x=0, y=0)

    def deferred_process_Generalization(self, generalization_element:ET.Element):    
        generalization_id = generalization_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        generalization = self.element_factory.lookup(generalization_id)
        assert generalization != None
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

    def deferred_process_NavigibleOwnedEnd(self, navigible_owned_end_element:ET.Element, owner:Association):
        idref = navigible_owned_end_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
        navigible_owned_end = self.element_factory.lookup(idref)
        if navigible_owned_end == None:
            print ("navigible_owned_end not found in deferred_process_NavigibleOwnedEnd: " + idref)
            return
            # raise ImportException("navigible_owned_end not found in deferred_process_NavigibleOwnedEnd: " + idref)
        if isinstance(owner, Extension):
            # Have to ask the Extension question first because Extension is also a subclass of Association
            owner.ownedEnd = navigible_owned_end
        elif isinstance(owner, Association):
            owner.navigableOwnedEnd = navigible_owned_end
            

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
                # Owned Attributes may belong to either associations or stereotypes. Each requires different treatment
                owner = property.owner
                if isinstance(owner, Association):
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
                        value = self.import_lower_value(lower_value)
                        if value != None:
                            property.lowerValue = value
                    upper_value_iterator = element.iter("upperValue")
                    upper_value = next(upper_value_iterator, None)  
                    if upper_value != None:
                        value = self.import_upper_value(upper_value)
                        if value != None:
                            property.upperValue = value
                elif isinstance(owner, Stereotype):
                    type_id = element.get("type")
                    if type_id != None:
                        type = self.element_factory.lookup(type_id)
                        property.type = type
                        name = element.get("name")
                        if name == "base_element":
                            # This is the base type of the stereotype, create an extension
                            found = False
                            for attribute in owner.ownedAttribute:
                                if attribute.name == "baseClass":
                                    found = True
                            if found == False:
                                extension = create_extension(type, owner)
                                extension.package = owner.package

    def layout_diagrams(self):
        for diagram in self.element_factory.select(Diagram):
            auto_layout = AutoLayout(self.event_manager)
            auto_layout.layout(diagram)

    def get_abstraction(self, id, owner:Package, element:ET.Element) -> Abstraction:
        assert id != None
        abstraction = self.element_factory.lookup(id)
        if abstraction == None:
            abstraction = self.element_factory.create_as(Abstraction, id)
            for child in element:
                pending_queue_entry = PendingEntry(child, element)
                self.pending_queue.put(pending_queue_entry)
        abstraction.owningPackage = owner
        return abstraction

    def get_accept_event_action(self, element:ET.Element, owner:Activity) -> AcceptEventAction:
        id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
        assert id != None
        accept_event_action = self.element_factory.lookup(id)
        if accept_event_action == None:
            accept_event_action = self.element_factory.create_as(AcceptEventAction, id)
            accept_event_action.activity = owner
            name = element.get("name")
            accept_event_action.name = name
            for child in element:
                tag = child.tag
                match tag:
                    case "trigger":
                        type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match type:
                            case "uml:Trigger":
                                trigger_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                                trigger = self.get_trigger(trigger_id, accept_event_action, child)
                    case "inInterruptibleRegion":
                        # TODO implement when InterruptibleActivityRegion is implemeted in Gaphor model
                        print ("Import of packaged element AcceptEventAction child not implemented for tag: " + tag)
                    case "inPartition":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        pass
                    case _:
                        print ("Import of packaged element AcceptEventAction child not processed for tag: " + tag)
                        # raise ImportException("Import of packaged element AcceptEventAction child not processed for tag: " + tag)
        return accept_event_action

    def get_activity(self, name, id, owner:Package | UseCase | None, element:ET.Element) -> Activity:
        assert id != None
        activity = self.element_factory.lookup(id)
        if activity == None:
            activity = self.element_factory.create_as(Activity, id=id)
            if isinstance(owner, Package):
                activity.package = owner
            elif isinstance(owner, UseCase):
                owner.ownedBehavior = activity
            activity.name = name
            isReentrant = element.get("isReentrant")
            if isReentrant == "true":
                activity.isReentrant = True
            elif isReentrant == "false":
                activity.isReentrant = False
            for owned_parameter_element in element.findall("ownedParameter"):
                self.import_OwnedParameter(owned_parameter_element, activity)
            owned_diagram_elements = element.iter("ownedDiagram")
            for owned_diagram_element in owned_diagram_elements:
                diagram_id = owned_diagram_element.get("{http://www.omg.org/spec/XMI/20131001}id")
                diagram_name = owned_diagram_element.get("name")
                diagram = self.get_diagram(diagram_name, diagram_id, activity, owned_diagram_element)
            for node_element in element.findall("node"):
                self.import_node(node_element, activity)
            for edge_element in element.findall("edge"):
                self.import_edge(edge_element, activity)   
            for group_element in element.findall("group"):
                self.import_group(group_element, activity)
        return activity

    def get_activity_final_node(self, node_element:ET.Element, owner:Activity) -> ActivityFinalNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        activity_final_node = self.element_factory.lookup(id)
        if activity_final_node == None:
            activity_final_node = self.element_factory.create_as(ActivityFinalNode, id)
            activity_final_node.activity = owner
            name = node_element.get("name")
            activity_final_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                activity_final_node.visibility = visibility
        return activity_final_node

    def get_activity_node(self, node_element:ET.Element, owner:Activity) -> ActivityNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        activity_node = self.element_factory.lookup(id)
        if activity_node == None:
            activity_node = self.element_factory.create_as(ActivityNode, id)
            activity_node.activity = owner
            name = node_element.get("name")
            activity_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                activity_node.visibility = visibility
        return activity_node

    def get_activity_parameter_node(self, node_element:ET.Element, owner:Activity) -> ActivityParameterNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        activity_parameter_node = self.element_factory.lookup(id)
        if activity_parameter_node == None:
            activity_parameter_node = self.element_factory.create_as(ActivityParameterNode, id)
            activity_parameter_node.activity = owner
            name = node_element.get("name")
            activity_parameter_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                activity_parameter_node.visibility = visibility
            pending_queue_entry = PendingEntry(node_element, None)
            self.pending_queue.put(pending_queue_entry)
        return activity_parameter_node

    def get_activity_partition(self, name, id, owner:Activity, element:ET.Element) -> ActivityPartition:
        assert id != None
        group = self.element_factory.lookup(id)
        if group == None:
            group = self.element_factory.create_as(ActivityPartition, id)
            group.activity = owner
            group.name = name
            for node_element in element.findall("node"):
                node_id = node_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                node = self.element_factory.lookup(node_id)
                node.inPartition = group
                node.inGroup = group
                group.node = node
                group.nodeContents = node
            for edge_element in element.findall("edge"):
                edge_id = edge_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
                edge = self.element_factory.lookup(edge_id)
                edge.inGroup = group
                group.edgeContents = edge
            for child in element:
                tag = child.tag
                match tag:
                    case "node":
                        pass
                    case "edge":
                        pass
                    case _:
                        print ("Import of packaged element ActivityPartition child not processed for tag: " + tag)
        return group

    def get_actor(self, name, id, owner:Package, element:ET.Element) -> Actor:
        assert id != None
        actor = self.element_factory.lookup(id)
        if actor == None:
            actor = self.element_factory.create_as(Actor, id)
            actor.name = name
            actor.package = owner
            for child in element:
                tag = child.tag
                match tag:
                    case "generalization":
                        generalization_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")   
                        generalization = self.get_generalization(generalization_id, actor, child)
                    case "ownedAttribute":
                        self.import_OwnedAttribute(child, actor)
                    case "ownedOperation":
                        self.import_OwnedOperation(child, actor)
                    case "ownedComment":
                        self.import_OwnedComment(child, actor)
                    case _:
                        print ("Import of packaged element Actor child not processed for tag: " + tag)
                        # raise ImportException("Import of packaged element Actor child not processed for tag: " + tag)
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
                        self.pending_queue.put(PendingEntry(child, element))
                    case "ownedRule":
                        rule_type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match rule_type:
                            case "uml:Constraint":
                                constraint = self.import_constraint(child)
                                association.ownedRule = constraint
                                constraint.context = association
                            case _:
                                print ("Import of packaged element Collaboration child not processed for tag: " + tag +" with rule type " + rule_type)
                    case "ownedComment":
                        self.import_OwnedComment(child, association)
                    case _:
                        raise ImportException("Import of packaged element Association child not processed for tag: " + tag)
        return association

    def get_call_behavior_action(self, node_element:ET.Element, owner:Activity) -> CallBehaviorAction:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        call_behavior_action = self.element_factory.lookup(id)
        if call_behavior_action == None:
            call_behavior_action = self.element_factory.create_as(CallBehaviorAction, id)
            call_behavior_action.activity = owner
            name = node_element.get("name")
            call_behavior_action.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                call_behavior_action.visibility = visibility
            for child in node_element:
                tag = child.tag
                match tag:
                    case "argument":
                        type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match type:
                            case "uml:InputPin":
                                input_pin_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                                input_pin = self.element_factory.create_as(InputPin, input_pin_id)
                                call_behavior_action.inputValue = input_pin
                                input_pin_name = child.get("name")
                                input_pin.name = input_pin_name
                                visibility = child.get("visibility")
                                if visibility != None:
                                    input_pin.visibility = visibility
                                call_behavior_action.inputValue = input_pin
                                input_pin.opaqueAction = call_behavior_action
                    case "result":
                        type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match type:
                            case "uml:OutputPin":
                                output_pin_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                                output_pin = self.element_factory.create_as(OutputPin, output_pin_id)
                                call_behavior_action.outputValue = output_pin
                                output_pin_name = child.get("name")
                                output_pin.name = output_pin_name
                                visibility = child.get("visibility")
                                if visibility != None:
                                    output_pin.visibility = visibility
                                call_behavior_action.outputValue = output_pin
                                output_pin.opaqueAction = call_behavior_action
                    case "inInterruptibleRegion":
                        # TODO implement when InterruptibleActivityRegion is implemeted in Gaphor model
                        print ("Import of packaged element CallBehaviorAction child not implemented for tag: " + tag)
                    case "inPartition":
                        pending_queue_entry = PendingEntry(child, node_element)
                        self.pending_queue.put(pending_queue_entry)
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        pass
                    case _:
                        print ("Import of packaged element CallBehaviorAction child not processed for tag: " + tag)
                        # raise ImportException("Import of packaged element CallBehaviorAction child not processed for tag: " + tag)
        return call_behavior_action

    def get_call_operation_action(self, node_element:ET.Element, owner:Activity) -> CallAction:
        # TODO Change return type to CallOperationAction after it is added to Gaphor model
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        call_operation_action = self.element_factory.lookup(id)
        if call_operation_action == None:
            call_operation_action = self.element_factory.create_as(CallAction, id)
            call_operation_action.activity = owner
            name = node_element.get("name")
            call_operation_action.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                call_operation_action.visibility = visibility
        return call_operation_action

    def get_central_buffer_node(self, node_element:ET.Element, owner:Activity) -> ObjectNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        central_buffer_node = self.element_factory.lookup(id)
        if central_buffer_node == None:
            central_buffer_node = self.element_factory.create_as(ObjectNode, id)
            central_buffer_node.activity = owner
            name = node_element.get("name")
            central_buffer_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                central_buffer_node.visibility = visibility
            pending_queue_entry = PendingEntry(node_element, None)
            self.pending_queue.put(pending_queue_entry)
        return central_buffer_node

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
            # TODO implement isLeaf after it is added to Gaphor model
            # isLeaf = xml_element.get("isLeaf")
            # if isLeaf == "true":
            #     uml_class.isLeaf = True
            isFinalSpecialization = xml_element.get("isFinalSpecialization")
            if isFinalSpecialization == "true":
                uml_class.isFinalSpecialization = True
            visibility = xml_element.get("visibility")
            if visibility != None:
                uml_class.visibility = visibility
            for child in xml_element:
                tag = child.tag
                match tag:
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        extender = child.get("extender")
                        match extender:
                            case "MagicDraw UML 2024x":
                                pass
                            case _:
                                print ("Import of packaged element Class child not processed for tag: " + tag + " and extender "+ extender)
                    case "generalization":
                        generalization_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                        generalization = self.get_generalization(generalization_id, uml_class, child)
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
                        rule_type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match rule_type:
                            case "uml:Constraint":
                                constraint = self.import_constraint(child)
                                uml_class.ownedRule = constraint
                                constraint.context = uml_class
                            case _:
                                print ("Import of Class child not processed for tag: " + tag +" with rule type " + rule_type)
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

    def get_collaboration(self, name, id, owner:Package, element:ET.Element) -> Collaboration:
        assert id != None
        collaboration = self.element_factory.lookup(id)
        if collaboration == None:
            collaboration = self.element_factory.create_as(Collaboration, id)
            collaboration.name = name
            collaboration.package = owner
            for child in element:
                tag = child.tag
                match tag:
                    case "ownedAttribute":
                        self.import_OwnedAttribute(child, collaboration)
                    case "ownedBehavior":
                        self.import_OwnedBehavior(child, collaboration)
                    case "ownedComment":
                        self.import_OwnedComment(child, collaboration)
                    case "ownedConnector":
                        # TODO implement ownedConnector
                        print ("Import of packaged element Collaboration child not processed for tag: " + tag)
                    case "ownedDiagram":
                        self.import_OwnedDiagram(child, collaboration)
                    case "ownedOperation":
                        self.import_OwnedOperation(child, collaboration)
                    case "ownedRule":
                        rule_type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match rule_type:
                            case "uml:Constraint":
                                constraint = self.import_constraint(child)   
                                collaboration.ownedRule = constraint
                                constraint.context = collaboration
                            case _:
                                print ("Import of Collaboration child not processed for tag: " + tag +" with rule type " + rule_type)
                    case "ownedTemplateSignature":
                        # TODO implement ownedTemplateSignature
                        print ("Import of packaged element Collaboration child not processed for tag: " + tag)
                    case "templateBinding":
                        # TODO implement templateBinding
                        print ("Import of packaged element Collaboration child not processed for tag: " + tag)
                    case _:
                        print ("Import of packaged element Collaboration child not processed for tag: " + tag)
        return collaboration

    def get_conditional_node(self, node_element:ET.Element, owner:Activity) -> OpaqueAction:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        conditional_node = self.element_factory.lookup(id)
        if conditional_node == None:
            conditional_node = self.element_factory.create_as(OpaqueAction, id)
            conditional_node.activity = owner
            name = node_element.get("name")
            conditional_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                conditional_node.visibility = visibility
            print ("Conditional node " + name + " importerd as OpaqueAction. Conditional nodes are presently not implemented in Gaphor")
        return conditional_node

    def get_constraint(self, constraint_element:ET.Element) -> Constraint:
        id = constraint_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        assert id != None
        constraint = self.element_factory.lookup(id)
        if constraint == None:
            constraint = self.element_factory.create_as(Constraint, id)
            name = constraint_element.get("name")
            if name != None:
                constraint.name = name
        return constraint


    def get_control_flow(self, element:ET.Element, owner:Activity) -> ControlFlow:
        id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
        assert id != None
        control_flow = self.element_factory.lookup(id)
        if control_flow == None:
            control_flow = self.element_factory.create_as(ControlFlow, id)
            control_flow.activity = owner
            source_id = element.get("source")
            source = self.element_factory.lookup(source_id)
            control_flow.source = source
            source.outgoing = control_flow
            target_id = element.get("target")   
            target = self.element_factory.lookup(target_id)
            control_flow.target = target
            target.incoming = control_flow
            visibility = element.get("visibility")
            if visibility != None:
                control_flow.visibility = visibility
            # TODO implement weight after it is added to Gaphor model
        return control_flow

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

    def get_decision_node(self, node_element:ET.Element, owner:Activity) -> DecisionNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        decision_node = self.element_factory.lookup(id)
        if decision_node == None:
            decision_node = self.element_factory.create_as(DecisionNode, id)
            decision_node.activity = owner
            name = node_element.get("name")
            decision_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                decision_node.visibility = visibility
        return decision_node

    def get_dependency(self, id, element:ET.Element, owner:Package) -> Dependency:
        assert id != None
        dependency = self.element_factory.lookup(id)
        if dependency == None:
            dependency = self.element_factory.create_as(Dependency, id)
            for child in element:
                pending_queue_entry = PendingEntry(child, element)
                self.pending_queue.put(pending_queue_entry)
        dependency.owningPackage = owner
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

    def get_element_import(self, id, name) -> ElementImport:
        assert id != None
        element_import = self.element_factory.lookup(id)
        if element_import == None:
            element_import = self.element_factory.create_as(ElementImport, id)
            if name != None:
                element_import.name = name
        return element_import

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

    def get_extension(self, id) -> Extension:
        assert id != None
        extension = self.element_factory.lookup(id)
        if extension == None:
            extension = self.element_factory.create_as(Extension, id)
        return extension

    def get_extension_end(self,id) -> ExtensionEnd:
        assert id != None
        extension_end = self.element_factory.lookup(id)
        if extension_end == None:
            extension_end = self.element_factory.create_as(ExtensionEnd, id)
        return extension_end

    def get_flow_final_node(self, node_element:ET.Element, owner:Activity) -> FlowFinalNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        flow_final_node = self.element_factory.lookup(id)
        if flow_final_node == None:
            flow_final_node = self.element_factory.create_as(FlowFinalNode, id)
            flow_final_node.activity = owner
            name = node_element.get("name")
            flow_final_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                flow_final_node.visibility = visibility
        return flow_final_node

    def get_fork_node(self, node_element:ET.Element, owner:Activity) -> ForkNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        fork_node = self.element_factory.lookup(id)
        if fork_node == None:
            fork_node = self.element_factory.create_as(ForkNode, id)
            fork_node.activity = owner
            name = node_element.get("name")
            fork_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                fork_node.visibility = visibility
        return fork_node

    def get_generalization(self, id, owner:Class, element:ET.Element) -> Generalization:
        assert id != None
        generalization = self.element_factory.lookup(id)
        if generalization == None:
            generalization = self.element_factory.create_as(Generalization, id)
            owner.generalization = generalization
            generalization.specific = owner
            self.pending_queue.put(PendingEntry(element, None))
        return generalization

    def get_include(self, id, owner:Package) -> Include:
        assert id != None
        include = self.element_factory.lookup(id)
        if include == None:
            include = self.element_factory.create_as(Include, id)
        return include

    def get_initial_node(self, node_element:ET.Element, owner:Activity) -> InitialNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        initial_node = self.element_factory.lookup(id)
        if initial_node == None:
            initial_node = self.element_factory.create_as(InitialNode, id)
            initial_node.activity = owner
            name = node_element.get("name")
            initial_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                initial_node.visibility = visibility
        return initial_node

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

    def get_interaction(self, name, id, owner:Package, element:ET.Element) -> Interaction:
        assert id != None
        interaction = self.element_factory.lookup(id)
        if interaction == None:
            interaction = self.element_factory.create_as(Interaction, id)
            interaction.name = name
            owner.ownedBehavior = interaction
            isReentrant = element.get("isReentrant")
            if isReentrant == 'true':
                interaction.isReentrant = "True"
            elif isReentrant == 'false':
                interaction.isReentrant = "False"
            for child in element:
                tag = child.tag
                match tag:
                    case "fragment":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "lifeline":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "message":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "ownedComment":
                        self.import_OwnedComment(child, interaction)
                    case "ownedRule":
                        rule_type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match rule_type:
                            case "uml:Constraint":
                                constraint = self.import_constraint(child)
                                interaction.ownedRule = constraint
                                constraint.context = interaction
                            case _:
                                print ("Import of Interaction child not processed for tag: " + tag +" with rule type " + rule_type)
                    case "precondition":
                        pending_queue_entry = PendingEntry(child, element)
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        owned_diagram_child = child.find("ownedDiagram")
                        if owned_diagram_child != None:
                            diagram_id = owned_diagram_child.get("{http://www.omg.org/spec/XMI/20131001}idref")
                            diagram_name = owned_diagram_child.get("name")
                            owned_diagram = self.get_diagram(diagram_name, diagram_id, interaction, owned_diagram_child)
                    case _:
                        print ("Import of Interaction child not processed for tag: " + tag)
        return interaction

    def get_interfaceRealization(self, id, owner:Class, element:ET.Element) -> InterfaceRealization:
        assert id != None
        interface_realization = self.element_factory.lookup(id)
        if interface_realization == None:
            interface_realization = self.element_factory.create_as(InterfaceRealization, id)
            interface_realization.implementingClassifier = owner
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
        interface_realization.owningPackage = owner.package
        return interface_realization

    def get_literalBoolean(self, id, owner:Package | Namespace | None, element:ET.Element) -> LiteralBoolean: 
        literalBoolean:LiteralBoolean | None = None
        if id:
            literalBoolean = self.element_factory.lookup(id)
            if literalBoolean == None:
                literalBoolean = self.element_factory.create_as(LiteralBoolean, id=id)
                if owner != None:
                    if isinstance(owner, Package):
                        literalBoolean.package = owner
                    else:
                        literalBoolean.namespace = owner
                value = element.get("value")
                if value != None:
                    literalBoolean.value = bool(value) 
        return literalBoolean

    def get_literalInteger(self, id, owner:Package | Namespace | None, element:ET.Element) -> LiteralInteger: 
        literalInteger:LiteralInteger | None = None
        if id:
            literalInteger = self.element_factory.lookup(id)
            if literalInteger == None:
                literalInteger = self.element_factory.create_as(LiteralInteger, id=id)
                if owner != None:
                    if isinstance(owner, Package):
                        literalInteger.package = owner
                    else:
                        literalInteger.namespace = owner
                value = element.get("value")
                if value != None:
                    literalInteger.value = int(value) 
        return literalInteger

    def get_literalString(self, id, owner:Package | Namespace | None, element:ET.Element) -> LiteralString: 
        literalString:LiteralString | None = None
        if id:
            literalString = self.element_factory.lookup(id)
            if literalString == None:
                literalString = self.element_factory.create_as(LiteralString, id=id)
                if owner != None:
                    if isinstance(owner, Package):
                        literalString.package = owner
                    else:
                        literalString.namespace = owner
                value = element.get("value")
                if value != None:
                    literalString.value = value 
        return literalString

    def get_literalUnlimitedNatural(self, id, owner:Package | Namespace | None, element:ET.Element) -> LiteralUnlimitedNatural: 
        literalUnlimitedNatural:LiteralUnlimitedNatural | None = None
        if id:
            literalUnlimitedNatural = self.element_factory.lookup(id)
            if literalUnlimitedNatural == None:
                literalUnlimitedNatural = self.element_factory.create_as(LiteralUnlimitedNatural, id=id)
                if owner != None:
                    if isinstance(owner, Package):
                        literalUnlimitedNatural.package = owner
                    else:
                        literalUnlimitedNatural.namespace = owner
                value = element.get("value")
                if value != None:
                    if value == "*":
                        literalUnlimitedNatural.value = UnlimitedNatural(math.inf)
                    else:
                        literalUnlimitedNatural.value = UnlimitedNatural(int(value)) 
        return literalUnlimitedNatural

    # TODO uncomment get_interruptable_activity_region after it is added to Gaphor model
    # def get_interruptable_activity_region(self, name, id, owner:Activity, element:ET.Element) -> InterruptibleActivityRegion:
    #     assert id != None
    #     group = self.element_factory.lookup(id)
    #     if group == None:
    #         group = self.element_factory.create_as(InterruptibleActivityRegion, id)
    #         group.activity = owner
    #         group.name = name
    #         for node_element in element.findall("node"):
    #             self.import_node(node_element, group)
    #         for edge_element in element.findall("edge"):
    #             self.import_edge(edge_element, group)
    #         for interrupting_edge_element in element.findall("interruptingEdge"):
    #             interrupting_edge_id = interrupting_edge_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
    #             interrupting_edge = self.element_factory.lookup(interrupting_edge_id)
    #             group.interruptingEdge = interrupting_edge
    #     return group

    def get_join_node(self, node_element:ET.Element, owner:Activity) -> JoinNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        join_node = self.element_factory.lookup(id)
        if join_node == None:
            join_node = self.element_factory.create_as(JoinNode, id)
            join_node.activity = owner
            name = node_element.get("name")
            join_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                join_node.visibility = visibility
        return join_node

    # def get_literal_integer(self, id) -> LiteralInteger:

    def get_loop_node(self, node_element:ET.Element, owner:Activity) -> OpaqueAction:
        # TODO Change return type to LoopNode after it is added to Gaphor model 
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        loop_node = self.element_factory.lookup(id)
        if loop_node == None:
            loop_node = self.element_factory.create_as(OpaqueAction, id)
            loop_node.activity = owner
            name = node_element.get("name")
            loop_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                loop_node.visibility = visibility
            print ("Loop node " + name + " importerd as OpaqueAction. Loop nodes are presently not implemented in Gaphor")
            # for child_node_element in node_element.findall("node"):
            #     self.import_node(child_node_element, loop_node)
            # for child_edge_element in node_element.findall("edge"):
            #     self.import_edge(child_edge_element, loop_node)
            # for body_part_element in node_element.findall("bodyPart"):
            #     body_part_id = body_part_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
            #     body_part = self.element_factory.lookup(body_part_id)
            #     loop_node.bodyPart = body_part
            # for setup_part_element in node_element.findall("setupPart"):
            #     setup_part_id = setup_part_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
            #     setup_part = self.element_factory.lookup(setup_part_id)
            #     loop_node.setupPart = setup_part
            # for test_element in node_element.findall("test"):
            #     test_id = test_element.get("{http://www.omg.org/spec/XMI/20131001}idref")
            #     test = self.element_factory.lookup(test_id)
            #     loop_node.test = test
        return loop_node

    def get_merge_node(self, node_element:ET.Element, owner:Activity) -> MergeNode:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        merge_node = self.element_factory.lookup(id)
        if merge_node == None:
            merge_node = self.element_factory.create_as(MergeNode, id)
            merge_node.activity = owner
            name = node_element.get("name")
            merge_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                merge_node.visibility = visibility
        return merge_node

    def get_object_flow(self, element:ET.Element, owner:Activity) -> ObjectFlow:
        id = element.get("{http://www.omg.org/spec/XMI/20131001}id")
        assert id != None
        object_flow = self.element_factory.lookup(id)
        if object_flow == None:
            object_flow = self.element_factory.create_as(ObjectFlow, id)
            object_flow.activity = owner
            source_id = element.get("source")
            source = self.element_factory.lookup(source_id)
            object_flow.source = source
            source.outgoing = object_flow
            target_id = element.get("target")   
            target = self.element_factory.lookup(target_id)
            object_flow.target = target
            target.incoming = object_flow
            visibility = element.get("visibility")
            if visibility != None:
                object_flow.visibility = visibility
            # TODO implement weight after it is added to Gaphor model
        return object_flow

    def get_opaque_action(self, node_element:ET.Element, owner:Activity) -> OpaqueAction:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        opaque_action = self.element_factory.lookup(id)
        if opaque_action == None:
            opaque_action = self.element_factory.create_as(OpaqueAction, id)
            opaque_action.activity = owner
            name = node_element.get("name")
            opaque_action.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                opaque_action.visibility = visibility
        return opaque_action

    def get_opaque_behavior(self, opaque_behavior_element:ET.Element, owner:Package) -> OpaqueBehavior:
        id = opaque_behavior_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        opaque_behavior = self.element_factory.lookup(id)
        if opaque_behavior == None:
            opaque_behavior = self.element_factory.create_as(OpaqueBehavior, id)
            opaque_behavior.owningPackage = owner
            name = opaque_behavior_element.get("name")
            opaque_behavior.name = name
        return opaque_behavior

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

    def get_parameter(self, name, id) -> Parameter:
        assert id != None
        parameter = self.element_factory.lookup(id)
        if parameter == None:
            parameter = self.element_factory.create_as(Parameter, id)
            parameter.name = name
        return parameter

    def get_primitive_type(self, name, id, owner:Package) -> PrimitiveType:
        assert id != None
        primitive_type = self.element_factory.lookup(id)
        if primitive_type == None:
            primitive_type = self.element_factory.create_as(PrimitiveType, id)
            primitive_type.name = name
            primitive_type.owningPackage = owner
        return primitive_type

    def get_profile(self, name, id, owner:Package) -> Profile:  
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
        profile.nestingPackage = owner
        return profile

    def get_property(self, id) -> Property:
        assert id != None
        property = self.element_factory.lookup(id)
        if property == None:
            property = self.element_factory.create_as(Property, id)
        return property

    def get_realization(self, id, owner:Package, element:ET.Element) -> Realization:
        assert id != None
        realization = self.element_factory.lookup(id)
        if realization == None:
            realization = self.element_factory.create_as(Realization, id)
            for child in element:
                pending_queue_entry = PendingEntry(child, element)
                self.pending_queue.put(pending_queue_entry)
        realization.owningPackage = owner
        return realization

    def get_region(self, id, owner:StateMachine, element:ET.Element) -> Region:
        assert id != None
        region = self.element_factory.lookup(id)
        if region == None:
            region = self.element_factory.create_as(Region, id)
            for child in element:
                tag = child.tag
                match tag:
                    case "subvertex":
                        type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                        match type:
                            case "uml:State":
                                state_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                                state = self.get_state(state_id, region, child)
                            case "uml:Pseudostate":
                                pseudostate_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                                pseudostate = self.get_pseudostate(pseudostate_id, region, child)
                            case "uml:FinalState":
                                final_state_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                                final_state = self.get_final_state(final_state_id, region, child)
                            case _:
                                print ("Import of region child not processed for tag: " + tag + " and type: " + type)
        return region

    def get_referent_type(self, referentTypeName, profile:Profile) -> Class:
        for child in profile.ownedElement:
            if child.name == referentTypeName and isinstance(child, Class):
                return child
        new_metatype = self.element_factory.create(Class)
        new_metatype.name = referentTypeName
        new_metatype.package = profile
        return new_metatype

    def get_send_signal_action(self, node_element:ET.Element, owner:Activity) -> SendSignalAction:
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        send_signal_action = self.element_factory.lookup(id)
        if send_signal_action == None:
            send_signal_action = self.element_factory.create_as(SendSignalAction, id)
            send_signal_action.activity = owner
            name = node_element.get("name")
            send_signal_action.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                send_signal_action.visibility = visibility
            # TODO implement signal attribute after gaphor model is updated
        return send_signal_action

    def get_sequence_node(self, node_element:ET.Element, owner:Activity) -> OpaqueAction:
        # TODO Change return type to SequenceNode after it is added to Gaphor model 
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        sequence_node = self.element_factory.lookup(id)
        if sequence_node == None:
            sequence_node = self.element_factory.create_as(OpaqueAction, id)
            sequence_node.activity = owner
            name = node_element.get("name")
            sequence_node.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                sequence_node.visibility = visibility
            print ("Sequence node " + name + " importerd as OpaqueAction. Sequence nodes are presently not implemented in Gaphor")
        return sequence_node

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

    def get_state(self, id, owner:Region, element:ET.Element) -> State:
        assert id != None
        state = self.element_factory.lookup(id)
        if state == None:
            state = self.element_factory.create_as(State, id)
            state.region = owner
            name = element.get("name")
            if name != None:
                state.name = name
            visibility = element.get("visibility")
            if visibility != None:
                state.visibility = visibility
            for child in element:
                tag = child.tag
                match tag:
                    case "connection":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "connectionPoint":
                        connection_point_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                        connection_point = self.get_connection_point(connection_point_id, state, child)
                    case "ownedAttribute":
                        self.import_OwnedAttribute(child, state)
                    case "ownedBehavior":
                        behavior = self.import_OwnedBehavior(child, state)
                    case "ownedComment":
                        self.import_OwnedComment(child, state)
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        # TODO implement Extension
                        print ("Import of state child not processed for tag: " + tag)
                    case _:
                        print ("Import of state child not processed for tag: " + tag)
        return state

    def get_state_machine(self, name, id, owner:Package, element:ET.Element) -> StateMachine:
        assert id != None
        state_machine = self.element_factory.lookup(id)
        if state_machine == None:
            state_machine = self.element_factory.create_as(StateMachine, id)
            state_machine.package = owner
            state_machine.name = name
            for child in element:
                tag = child.tag
                match tag:
                    case "region":
                        region_id = child.get("{http://www.omg.org/spec/XMI/20131001}id")
                        region = self.get_region(region_id, state_machine, child)
                    case "ownedAttribute":
                        self.import_OwnedAttribute(child, state_machine)
                    case "ownedBehavior":
                        behavior = self.import_OwnedBehavior(child, state_machine)
                    case "ownedComment":
                        self.import_OwnedComment(child, state_machine)
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        # TODO implement Extension
                        print ("Import of state machine child not processed for tag: " + tag)
                    case _:
                        print ("Import of state machine child not processed for tag: " + tag)
        return state_machine

    def get_stereotype(self, name, id, owner:Package) -> Stereotype:  
        assert id != None
        stereotype = self.element_factory.lookup(id)
        if stereotype == None:
            stereotype = self.element_factory.create_as(Stereotype, id)
            stereotype.name = name
            stereotype.package = owner
        return stereotype

    def get_time_event(self, node_element:ET.Element, owner:Package) -> Event:
        # TODO Change return type to TimeEvent after it is added to Gaphor model
        id = node_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        time_event = self.element_factory.lookup(id)
        if time_event == None:
            time_event = self.element_factory.create_as(Event, id)
            # TODO Figure out TimeEvent ownership after TimeEvents are implemented in Gaphor
            time_event.owningPackage = owner
            name = node_element.get("name")
            time_event.name = name
            visibility = node_element.get("visibility")
            if visibility != None:
                time_event.visibility = visibility
            print ("TimeEvent " + id + " imported as Event. TimeEvents are not presently implemented in Gaphor.")
            # TODO implement when clause for TimeEvent
        return time_event

    def get_trigger(self, id, acceptEventAction:AcceptEventAction, element:ET.Element) -> Trigger:
        assert id != None
        trigger = self.element_factory.lookup(id)
        if trigger == None:
            trigger = self.element_factory.create_as(Trigger, id)
            # TODO Implement this when trigger.acceptEventAction is added to Gaphor
            # trigger.acceptEventAction = acceptEventAction
            self.pending_queue.put(PendingEntry(element, None))
            visibility = element.get("visibility")
            if visibility != None:
                trigger.visibility = visibility
        return trigger

    def get_use_case(self, name, id, owner:Package | None, element:ET.Element) -> UseCase | None:
        assert id != None
        use_case = self.element_factory.lookup(id)
        if use_case == None: 
            use_case = self.element_factory.create_as(UseCase, id=id)
            if owner != None:
                use_case.package = owner
            use_case.name = name
            for child in element:
                tag = child.tag
                match tag:
                    case "extend":
                        extend = self.import_extend(child, use_case)
                    case "extensionPoint":
                        extension_point = self.import_extension_point(child, use_case)
                    case "include":
                        pending_queue_entry = PendingEntry(child, element)
                        self.pending_queue.put(pending_queue_entry)
                    case "ownedBehavior":
                        behavior = self.import_OwnedBehavior(child, use_case)
                    case "ownedUseCase":
                        # TODO implement ownedUseCase
                        print ("Import of packaged element UseCase child not processed for tag: " + tag)
                    case "ownedComment":
                        self.import_OwnedComment(child, use_case)
                    case "{http://www.omg.org/spec/XMI/20131001}Extension":
                        # TODO implement Extension
                        print ("get_use_case child not processed for tag: " + tag)
                    case _:
                        print ("get_use_case child not processed for tag: " + tag)
        return use_case

    def import_Abstraction(self, abstraction_element:ET.Element, owner:Package):
        id = abstraction_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        abstraction = self.get_abstraction(id, owner, abstraction_element)

    def import_constraint(self, constraint_element:ET.Element) -> Constraint:
        constraint = self.get_constraint(constraint_element)
        for child in constraint_element:
            tag = child.tag
            match tag:
                case "specification":
                    match child.get("{http://www.omg.org/spec/XMI/20131001}type"):
                        case "uml:OpaqueExpression":
                            expression = self.import_opaque_expression(child)
                            constraint.specification = expression
                case "constrainedElement":
                    pending_queue_entry = PendingEntry(child, constraint_element)
                    self.pending_queue.put(pending_queue_entry)
                case "ownedComment":
                    self.import_OwnedComment(child, constraint)
                case _:
                    print ("Import of constraint child not processed for tag: " + tag)
        return constraint

    def import_edge(self, edge_element:ET.Element, owner:Activity):
        edge_type = edge_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match edge_type:
            case "uml:ControlFlow":
                control_flow = self.get_control_flow(edge_element, owner)
            case "uml:ObjectFlow":
                object_flow = self.get_object_flow(edge_element, owner)
            case None:
                print ("Import of edge not processed, there is no type given.")
            case _:
                print ("Import of edge not processed for edge type: " + edge_type)

    def import_extension(self, extension_element:ET.Element, owner:Package):
        id = extension_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        extension = self.get_extension(id)
        extension.package = owner
        for child in extension_element:
            tag = child.tag
            match tag:
                case "memberEnd":
                    self.pending_queue.put(PendingEntry(child, extension_element))
                case "ownedEnd":
                    self.import_extension_end(child, extension)
                case "ownedAttribute":
                    self.import_OwnedAttribute(child, extension)
                case "ownedComment":
                    self.import_OwnedComment(child, extension)
                case "navigableOwnedEnd":
                    self.pending_queue.put(PendingEntry(child, extension_element))
                case _:
                    print ("Import of packaged element Extension child not processed for tag: " + tag)
                    # raise ImportException("Import of packaged element Extension child not processed for tag: " + tag)

    def import_extension_end(self, extension_end_element:ET.Element, owner:Extension):
        id = extension_end_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        extension_end = self.get_extension_end(id)
        name = extension_end_element.get("name")
        if name != None:
            extension_end.name = name
        owner.ownedEnd = extension_end
        for child in extension_end_element:
            tag = child.tag
            match tag:
                case "ownedEnd":
                    self.import_OwnedEnd(child, extension_end)
                case "ownedAttribute":
                    self.import_OwnedAttribute(child, extension_end)
                case "ownedComment":
                    self.import_OwnedComment(child, extension_end)
                case "navigableOwnedEnd":
                    self.pending_queue.put(PendingEntry(child, extension_end_element))
                case _:
                    print ("Import of extension element child not processed for tag: " + tag)
            

    def import_element_import(self, element_import_element:ET.Element, package:Package) -> ElementImport:
        id = element_import_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = element_import_element.get("name")
        import_element = self.get_element_import(id, name)
        import_element.importingNamespace = package
        pending_entry = PendingEntry(element_import_element, None)
        self.pending_queue.put(pending_entry)
        return import_element

    def import_extend(self, extend_element:ET.Element, owner:UseCase) -> Extend:
        id = extend_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        extend = self.element_factory.lookup(id)
        if extend == None:
            extend = self.element_factory.create_as(Extend, id)
            extend.extension = owner
            self.pending_queue.put(PendingEntry(extend_element, None))
            for child in extend_element:
                tag = child.tag
                match tag:
                    case "ownedComment":
                        self.import_OwnedComment(child, extend)
                    case "condition":
                        match child.get("{http://www.omg.org/spec/XMI/20131001}type"):
                            case "uml:Constraint":
                                constraint = self.import_constraint(child)
                                extend.constraint = constraint
                    case "extensionLocation":
                        self.pending_queue.put(PendingEntry(child, extend_element))
                    case _:
                        print ("Import of extend not processed for tag: " + tag)
        return extend

    def import_extension_point(self, extension_point_element:ET.Element, owner:UseCase) -> ExtensionPoint:
        id = extension_point_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        extension_point = self.element_factory.lookup(id)
        if extension_point == None:
            extension_point = self.element_factory.create_as(ExtensionPoint, id)
            extension_point.useCase = owner
            name = extension_point_element.get("name")
            extension_point.name = name
            visibility = extension_point_element.get("visibility")
            if visibility != None:
                extension_point.visibility = visibility
            for child in extension_point_element:
                tag = child.tag
                match tag:
                    case "extension":
                        self.pending_queue.put(PendingEntry(child, extension_point_element))
                    case _:
                        print ("Import of extension point child not processed for tag: " + tag)
        return extension_point

    def import_group(self, group_element:ET.Element, owner:Package):
        id = group_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = group_element.get("name")
        type = group_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match type:
            case "uml:ActivityPartition":
                self.get_activity_partition(name, id, owner, group_element)
            case "uml:InterruptibleActivityRegion":
                # TODO uncomment get_interruptable_activity_region after it is added to Gaphor model
                # self.get_interruptable_activity_region(name, id, owner, group_element)
                print ("Import of InterruptibleActivityRegion not implemented. ")
            case _:
                print ("Import of group not processed for group type: " + type)

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

    def import_lower_value(self, lower_value_element:ET.Element) -> ValueSpecification:
        id = lower_value_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        type = lower_value_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match type:
            case "uml:LiteralInteger":
                lower_value = self.get_literalInteger(id, None, lower_value_element)
                return lower_value

    def import_Model(self, lib_element:ET.Element, owner:Package):
        model_name = lib_element.get("name")
        model_id = lib_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        model = self.get_package(model_name, model_id, None)
        if owner != None:
            model.nestingPackage = owner
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
                        diagram = self.get_diagram(name, diagram_id, model , owned_diagram_element)

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
    
    def import_node(self, node_element, activity):
        node_type = node_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match node_type:
            case "uml:AcceptEventAction":
                accept_event_action = self.get_accept_event_action(node_element, activity)
            case "uml:ActivityFinalNode":
                activity_final_node = self.get_activity_final_node(node_element, activity)
            case "uml:ActivityParameterNode":
                activity_parameter_node = self.get_activity_parameter_node(node_element, activity)
            case "uml:CentralBufferNode":
                cantral_buffer_node = self.get_central_buffer_node(node_element, activity)
            case "uml:CallBehaviorAction":
                call_behavior_action_node = self.get_call_behavior_action(node_element, activity)
            case "uml:CallOperationAction":
                call_operation_action_node = self.get_call_operation_action(node_element, activity)
            case "uml:ConditionalNode":
                conditional_node = self.get_conditional_node(node_element, activity)
            case "uml:DecisionNode":
                decision_node = self.get_decision_node(node_element, activity)
            case "uml:FlowFinalNode":
                flow_final_node = self.get_flow_final_node(node_element, activity)
            case "uml:ForkNode":
                activity_node = self.get_fork_node(node_element, activity)
            case "uml:InitialNode":
                initial_node = self.get_initial_node(node_element, activity)
            case "uml:JoinNode":
                join_node = self.get_join_node(node_element, activity)
            case "uml:LoopNode":
                loop_node = self.get_loop_node(node_element, activity)
            case "uml:MergeNode":
                merge_node = self.get_merge_node(node_element, activity)
            case "uml:OpaqueAction":
                opaque_action = self.get_opaque_action(node_element, activity)
            case "uml:SendSignalAction":
                send_signal_action = self.get_send_signal_action(node_element, activity)
            case "uml:SequenceNode":
                sequence_node = self.get_sequence_node(node_element, activity)
            case None:
                print ("Import of activity node not processed, there is no type given.")
            case _:
                print ("Import of activity node not processed for node type: " + node_type)

    def import_opaque_behavior(self,opaque_behavior_element:ET.Element, owner:Package) -> OpaqueBehavior:
        opaque_behavior = self.get_opaque_behavior(opaque_behavior_element, owner)
        for child in opaque_behavior_element:
            tag = child.tag
            match tag:
                case "body":
                    body = child.text
                    opaque_behavior.body = body
                case "language":
                    language = child.get("language")
                    opaque_behavior.language = language
                case "ownedComment":
                    self.import_OwnedComment(child, opaque_behavior)
                case "ownedParameter":
                    self.import_OwnedParameter(child, opaque_behavior)
                case _:
                    print ("Import of opaque behavior child not processed for tag: " + tag)
        return opaque_behavior

    def import_opaque_expression(self, opaque_expression_element:ET.Element) -> str:
        specification_element = opaque_expression_element.find("specification")
        if specification_element == None:
            return None
        body = specification_element.get("body")
        if body == None:
            return None
        return body.get("value")
        # TODO Change return type to OpaqueExpression after it is added to Gaphor model
        # id = opaque_expression_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        # opaque_expression = self.element_factory.lookup(id)
        # if opaque_expression == None:
        #     opaque_expression = self.element_factory.create_as(OpaqueExpression, id)
        #     for child in opaque_expression_element:
        #         tag = child.tag
        #         match tag:
        #             case "body":
        #                 body = child.get("value")
        #                 opaque_expression.body = body
        #             case "language":
        #                 language = child.get("value")
        #                 opaque_expression.language = language
        #             case _:
        #                 print ("Import of opaque expression child not processed for tag: " + tag)
        return opaque_expression

    def import_OwnedAttribute(self, ownedAttribute_element:ET.Element, owner:Class):
        id = ownedAttribute_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = ownedAttribute_element.get("name")
        attribute_type = ownedAttribute_element.get("{http://www.omg.org/spec/XMI/20131001}type")   
        match attribute_type:
            case "uml:Property":
                property = self.import_property(ownedAttribute_element)
                owner.ownedAttribute = property
            case _:
                print ("Import of owned attribute not processed for type: " + attribute_type)


    def import_OwnedBehavior(self, ownedBehavior_element:ET.Element, owner:UseCase):  
        id = ownedBehavior_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = ownedBehavior_element.get("name")
        type = ownedBehavior_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match type:
            case "uml:Activity":
                activity = self.get_activity(name, id, owner, ownedBehavior_element)
            case "uml:Interaction":
                interaction = self.get_interaction(name, id, owner, ownedBehavior_element)
            case _:
                print ("Import of owned behavior not processed for type: " + type)



    def import_OwnedComment(self, ownedComment_element:ET.Element, owner:Package | Class | UseCase | Association | None):
        body = ownedComment_element.get("body")
        comment = self.element_factory.create(Comment)
        comment.body = body
        comment.annotatedElement = owner
        owner.comment = comment

    def import_OwnedEnd(self, ownedEnd_element:ET.Element, owner:Association | Extension):
        id = ownedEnd_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        owned_end_type = ownedEnd_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match owned_end_type:
            case "uml:Property":
                property = self.import_property(ownedEnd_element) 
                owner.ownedEnd = property   
            case _: 
                print ("Import of owned end not processed for type: " + owned_end_type)

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

    def import_OwnedParameter(self, ownedParameter_element:ET.Element, owner:Operation | Behavior) -> Parameter:
        id = ownedParameter_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        name = ownedParameter_element.get("name")
        parameter = self.get_parameter(name, id)
        owner.ownedParameter = parameter
        if isinstance(owner, Operation):
            parameter.operation = owner
        elif isinstance(owner, Behavior):
            parameter.behavior = owner
        visibility = ownedParameter_element.get("visibility")
        if visibility != None:
            parameter.visibility = visibility
        direction = ownedParameter_element.get("direction")
        if direction != None:
            parameter.direction = direction
        pending_queue_entry = PendingEntry(ownedParameter_element, None)
        self.pending_queue.put(pending_queue_entry)
        return parameter

    def import_Package(self, package_element:ET.Element, owner:Package):
        name = package_element.get("name")
        id = package_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        package = self.get_package(name, id, None)
        if owner != None:
            package.nestingPackage = owner
        for child in package_element:
            tag = child.tag
            match tag:
                case "elementImport":
                    element_import = self.import_element_import(child, package)
                case "ownedComment":
                    self.import_OwnedComment(child, package)
                case "ownedRule":
                    rule_type = child.get("{http://www.omg.org/spec/XMI/20131001}type")
                    match rule_type:
                        case "uml:Constraint":
                            constraint = self.import_constraint(child)
                            package.ownedRule = constraint
                            constraint.context = package
                        case _:
                            print ("Import of Package ownedRule not processed for type: " + rule_type)
                case "packagedElement":
                    self.import_PackagedElement(child, package)
                case '{http://www.omg.org/spec/XMI/20131001}Extension':
                    owned_diagram_elements = child.iter("ownedDiagram")
                    for owned_diagram_element in owned_diagram_elements:
                        diagram_id = owned_diagram_element.get("{http://www.omg.org/spec/XMI/20131001}id")
                        name = owned_diagram_element.get("name")
                        diagram = self.get_diagram(name, diagram_id, package, owned_diagram_element)
                case _:
                    print ("Import of Package child not processed for tag: " + tag)
                    # raise ImportException("Import of package child not processed for tag: " + tag)

    def import_PackagedElement(self, packaged_element:ET.Element, owner:Package | None):
        name = packaged_element.get("name")
        id = packaged_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        elementType = packaged_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match elementType:
            case "uml:Abstraction":
                self.import_Abstraction(packaged_element, owner)
            case "uml:Activity":
                self.get_activity(name, id, owner, packaged_element)
            case "uml:Actor":
                self.get_actor(name, id, owner, packaged_element)
            case "uml:Association":
                association = self.get_association(id, owner, packaged_element)
            case "uml:Class":
                uml_class = self.get_class(name, id, owner, packaged_element)
            case "uml:Collaboration":
                collaboration = self.get_collaboration(name, id, owner, packaged_element)
            case "uml:Component":
                # TODO implement uml:Component
                print ("Import of packaged element Component not implemented")
            case "uml:DataType":
                self.get_datatype(name, id, owner)
            case "uml:Dependency":
                dependency = self.get_dependency(id, packaged_element, owner)
            case "uml:Enumeration":
                enumeration = self.get_enumeration(name, id, owner)
                for child in packaged_element:
                    tag = child.tag
                    match tag:
                        case "ownedLiteral":
                            self.import_OwnedLiteral(child, enumeration)
            case "uml:Extension":
                self.import_extension(packaged_element, owner)
            case "uml:ExtensionPoint":
                extension_point = self.import_extension_point(name, packaged_element, owner)
            case "uml:Generalization":
                generalization = self.get_generalization(id, owner, packaged_element)
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
                literalString = self.get_literalString(name, id, owner, packaged_element)
            case "uml:Model":
                self.import_Model(packaged_element, owner)
            case "uml:OpaqueBehavior":
                opaque_behavior = self.import_opaque_behavior(packaged_element, owner)
            case "uml:Package":  
                self.import_Package(packaged_element, owner)
            case "uml:PrimitiveType":
                self.import_primitive_type(packaged_element, owner)
            case "uml:Profile":
                self.import_Profile(packaged_element, owner)
            case "uml:Realization":
                realization = self.get_realization(id, owner, packaged_element)
            case "uml:StateMachine":
                state_machine = self.get_state_machine(name, id, owner, packaged_element)
            case "uml:Stereotype":
                stereotype = self.import_stereotype(packaged_element, owner)
            case "uml:TimeEvent":
                time_event = self.get_time_event(packaged_element, owner)
            case "uml:Usage":
                # TODO implement uml:Usage
                print ("Import of packaged element Usage not implemented")
            case "uml:UseCase":
                use_case = self.get_use_case(name, id, owner, packaged_element)
            case _:
                print ("Import of packaged element not processed for element type: " + elementType)
#                raise ImportException("Import of packaged element not processed for element type: " + elementType)

    def import_primitive_type(self, primitive_type_element:ET.Element, owner:Package):
        name = primitive_type_element.get("name")
        id = primitive_type_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        primitive_type = self.get_primitive_type(name, id, owner)
        for primitive_type_child in primitive_type_element:
            tag = primitive_type_child.tag
            match tag:
                case "generalization":
                    id = primitive_type_child.get("{http://www.omg.org/spec/XMI/20131001}id")
                    generalization = self.get_generalization(id, primitive_type, primitive_type_child)
                case "ownedComment":
                    self.import_OwnedComment(primitive_type_child, primitive_type)
                case _:
                    print ("Import of primitive type child not processed for tag: " + tag)

    def import_Profile(self, profile_element:ET.Element, owner:Package):
        name = profile_element.get("name")
        id = profile_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        profile = self.get_profile(name, id, owner)
        for profile_child in profile_element.findall("packagedElement"):
            self.import_PackagedElement(profile_child, profile)
            # if profile_child.get("{http://www.omg.org/spec/XMI/20131001}type") == "uml:Stereotype":
            #     self.import_stereotype(profile_child, profile)

    def import_property(self, property_element:ET.Element) -> Property:
        id = property_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        property = self.get_property(id)
        name = property_element.get("name")
        if name != None:
            property.name = name
        visibility = property_element.get("visibility")
        if visibility != None:
            property.visibility = visibility
        isStatic = property_element.get("isStatic")
        if isStatic == "true":
            property.isStatic = True
        isReadOnly = property_element.get("isReadOnly")
        if isReadOnly == "true":
            property.isReadOnly = True
        pending_queue_entry = PendingEntry(property_element, None)
        self.pending_queue.put(pending_queue_entry)
        for child in property_element:
            tag = child.tag
            match tag:
                case "ownedComment":
                    self.import_OwnedComment(child, property)
                case "type":
                    pending_queue_entry = PendingEntry(child, property_element)
                    self.pending_queue.put(pending_queue_entry)
                case "lowerValue":
                    lower_value = self.import_lower_value(child)
                    property.lowerValue = lower_value
                case "upperValue":
                    upper_value = self.import_upper_value(child)
                    property.upperValue = upper_value
                case _:
                    print ("Import of property child not processed for tag: " + tag)
        return property

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
                profile = self.get_profile(profile_name, None, None)
                stereotypeHREF = stereotype_element.get("stereotypeHREF")
                stereotype_id = stereotypeHREF.split("#")[1]
                stereotype = self.get_stereotype(stereotype_name, stereotype_id, profile)
                stereotype_dictionary[full_name] = stereotype
                # Since we don't know the type to which the stereotype may be applied, we will create it as an extension of Element
                # gaphor_metatype = self.get_referent_type("Element", profile) 
                # extension = create_extension(gaphor_metatype, stereotype)
                # extension.package = profile
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
                # This is an attribute of the stereotype
                property_id = stereotype_child.get("{http://www.omg.org/spec/XMI/20131001}id")
                property_name = stereotype_child.get("name")
                property = self.import_property(stereotype_child)
                stereotype.ownedAttribute = property

    def import_upper_value(self, upper_value_element:ET.Element) -> ValueSpecification:
        id = upper_value_element.get("{http://www.omg.org/spec/XMI/20131001}id")
        type = upper_value_element.get("{http://www.omg.org/spec/XMI/20131001}type")
        match type:
            case "uml:LiteralUnlimitedNatural":
                upper_value = self.get_literalUnlimitedNatural(id, None, upper_value_element)
                return upper_value

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
