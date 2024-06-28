import importlib
import traceback
import logging
import argparse
import os 

import imswitch
from imswitch.imcommon import prepareApp, launchApp
from imswitch.imcommon.controller import ModuleCommunicationChannel, MultiModuleWindowController
from imswitch.imcommon.model import modulesconfigtools, pythontools, initLogger
from imswitch.imcommon.view import MultiModuleWindow, ModuleLoadErrorView

# FIXME: Add to configuration file
# python main.py --headless or 
# python -m imswitch --headless 1 --config-file example_virtual_microscope.json

def main():
    parser = argparse.ArgumentParser(description='Process some integers.')
    
    # specify if run in headless mode
    parser.add_argument('--headless', dest='headless', type=bool, default=0,
                        help='run in headless mode')
    
    # specify config file name - None for default
    parser.add_argument('--config-file', dest='config_file', type=str, default=None,
                        help='specify run with config file')
    
    args = parser.parse_args()
    imswitch.IS_HEADLESS = args.headless
    imswitch.DEFAULT_SETUP_FILE = args.config_file # e.g. example_virtual_microscope.json
    
    if imswitch.IS_HEADLESS:
        os.environ["DISPLAY"] = ":0"
        os.environ["QT_QPA_PLATFORM"] = "offscreen"

    try:
        logger = initLogger('main')
        logger.info(f'Starting ImSwitch {imswitch.__version__}')
        logger.info(f'Headless mode: {imswitch.IS_HEADLESS}')
        logger.info(f'Config file: {imswitch.DEFAULT_SETUP_FILE}')
        app = prepareApp()
        enabledModuleIds = modulesconfigtools.getEnabledModuleIds()

        if 'imscripting' in enabledModuleIds and not imswitch.IS_HEADLESS:
            # Ensure that imscripting is added last
            enabledModuleIds.append(enabledModuleIds.pop(enabledModuleIds.index('imscripting')))

        if 'imnotebook' in enabledModuleIds and not imswitch.IS_HEADLESS:
            # Ensure that imnotebook is added last
            try:
                from PyQt5 import QtWebEngine
                enabledModuleIds.append(enabledModuleIds.pop(enabledModuleIds.index('imnotebook')))
            except ImportError:
                logger.error('QtWebEngineWidgets not found, disabling imnotebook')
                enabledModuleIds.remove('imnotebook')
            
        modulePkgs = [importlib.import_module(pythontools.joinModulePath('imswitch', moduleId))
                    for moduleId in enabledModuleIds]

        moduleCommChannel = ModuleCommunicationChannel()

        if not imswitch.IS_HEADLESS:
            multiModuleWindow = MultiModuleWindow('ImSwitch')
            multiModuleWindowController = MultiModuleWindowController.create(
                multiModuleWindow, moduleCommChannel
            )
            multiModuleWindow.show(showLoadingScreen=True)
        else:
            multiModuleWindow = None
            multiModuleWindowController = None

        app.processEvents()  # Draw window before continuing

        # Register modules
        for modulePkg in modulePkgs:
            moduleCommChannel.register(modulePkg)

        # Load modules
        moduleMainControllers = dict()

        for i, modulePkg in enumerate(modulePkgs):
            moduleId = modulePkg.__name__
            moduleId = moduleId[moduleId.rindex('.') + 1:]  # E.g. "imswitch.imcontrol" -> "imcontrol"

            # The displayed module name will be the module's __title__, or alternatively its ID if
            # __title__ is not set
            moduleName = modulePkg.__title__ if hasattr(modulePkg, '__title__') else moduleId

            try:
                view, controller = modulePkg.getMainViewAndController(
                    moduleCommChannel=moduleCommChannel,
                    multiModuleWindowController=multiModuleWindowController,
                    moduleMainControllers=moduleMainControllers
                )
                logger.info(f'initialize module {moduleId}')
            except Exception as e:
                logger.error(f'Failed to initialize module {moduleId}')
                logger.error(e)
                logger.error(traceback.format_exc())
                moduleCommChannel.unregister(modulePkg)
                if not imswitch.IS_HEADLESS: multiModuleWindow.addModule(moduleId, moduleName, ModuleLoadErrorView(e))
            else:
                # Add module to window
                if not imswitch.IS_HEADLESS: multiModuleWindow.addModule(moduleId, moduleName, view)
                moduleMainControllers[moduleId] = controller

                # Update loading progress
                if not imswitch.IS_HEADLESS: multiModuleWindow.updateLoadingProgress(i / len(modulePkgs))
                app.processEvents()  # Draw window before continuing
        logger.info(f'init done')
        launchApp(app, multiModuleWindow, moduleMainControllers.values())
    except Exception as e:
        logging.error(traceback.format_exc())


if __name__ == '__main__':
    main()

# Copyright (C) 2020-2023 ImSwitch developers
# This file is part of ImSwitch.
#
# ImSwitch is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ImSwitch is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
