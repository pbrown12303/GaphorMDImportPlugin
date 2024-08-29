# Gaphor MagicDraw Model Import Plugin

This plugin is designed to import a MagicDraw model into an existing Gaphor model.

## Installation

To install the plugin, follow the plugin installation instructions in the [Gaphor Documentation](https://docs.gaphor.org/en/latest/plugins.html)

## MagicDraw Model Export

There are two ways to obtain the export of the MagicDraw model
1. Explicitly export the model. Select the model in the containment tree and from the File menu export the model as XMI (TBD: add details)
2. Use the model in the existing .mdzip file. There are two cases here:
    a. The .mdzip is not a Profile. Unzip the .mdzip file. Locate the file named ```com.nomagic.magicdraw.uml_model.model```. This is the file you want to import
    b. The .mdzip is a Profile. Unzip the .mdzip file. Locate the file named ```com.nomagic.magicdraw.uml_model.shared_model``` and import this file

## Importing the MagicDraw model

From the Gaphor main menu, select Tools->Import MD Model. In the file dialog, select the file you want to import.

### A Note on Profiles

Profiles that are not directly part of your imported model will be imported, but with limited information. The reference in the current model identifies the Stereotypes and their Slots (value holders), but it does not identfy the types of Elements to which the Stereotype may be applied, nor does it identify the types of the values in the Slots. For this reason, Stereotypes imported in this manner will be applicable to all Element types and the Slots will not identify a value type.

If you wish to have more complete information about a profile, you can import the profile from its mdzip file, but you must do this before you import your main model - otherwise the limited version of the profile described above will be imported when your main model is imported and the import logic will ignore the more complete model.

## Current Status

At present, the import has been fully tested with the MagicDrawDirectory/samples/diagrams/Class Diagrams model.

## Known Limitations

### Dependency Ownership

The UML specification defines a Dependency to be a subclass of PackageableElement, whose owner must be a Package. The Gaphor implementation makes the owner of the Dependency the client of the dependency. Thus, after import, the Dependency will be located in a different place in Gaphor than it was in your original model.
