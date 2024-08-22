# Gaphor MagicDraw Model Import Plugin

This plugin is designed to import a MagicDraw model into an existing Gaphor model.

## Installation

To install the plugin, follow the plugin installation instructions in the [Gaphor Documentation](https://docs.gaphor.org/en/latest/plugins.html)

## MagicDraw Model Export

There are two ways to obtain the export of the MagicDraw model
1. Explicitly export the model. Select the model in the containment tree and from the File menu export the model as XMI (TBD: add details)
2. Use the model in the existing .mdzip file. There are two cases here:
    a. The .mdzip is not a plugin. Unzip the .mdzip file. Locate the file named ```com.nomagic.magicdraw.uml_model.model```. This is the file you want to import
    b. The .mdzip is a plugin. Unzip the .mdzip file. Locate the file named ```com.nomagic.magicdraw.uml_model.shared_model```

## Importing the MagicDraw model

From the Gaphor main menu, select Tools->Import MD Model. In the file dialog, select the file you want to import.

Note that Gaphor does not at present support incorporating one model into another by reference. The consequence is that if your MagicDraw model depends on plugins other than the default UML and SysML plugins, you need to first import the MagicDraw plugin into your model and then import your MagicDraw model into your model. 
