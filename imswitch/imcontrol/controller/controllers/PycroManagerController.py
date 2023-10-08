import os, time, json, numpy as np
from typing import Optional, Union, List
from imswitch.imcommon.framework import Signal
from imswitch.imcommon.framework.pycromanager import (
    PycroManagerAcquisitionMode,
    PycroManagerZStack,
    PycroManagerXYScan,
    PycroManagerXYZScan,
    PycroManagerXYPoint,
    PycroManagerXYZPoint
)

from imswitch.imcommon.model import (
    ostools,
    APIExport,
    SaveMode,
    initLogger
)
from ..basecontrollers import ImConWidgetController


class PycroManagerController(ImConWidgetController):
    """ Linked to RecordingWidget. """
    
    sigFailedToLoadJSON = Signal(str, str)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__logger = initLogger(self)

        self.settingAttr = False
        self.lapseTotal = 0

        self._widget.setSnapSaveMode(SaveMode.Disk.value)
        self._widget.setSnapSaveModeVisible(self._setupInfo.hasWidget('Image'))

        self._widget.setRecSaveMode(SaveMode.Disk.value)
        self._widget.setRecSaveModeVisible(
            self._moduleCommChannel.isModuleRegistered('imreconstruct')
        )

        self.specFrames()

        # Connect CommunicationChannel signals
        self._commChannel.sigRecordingStarted.connect(self.recordingStarted)
        self._commChannel.sigRecordingEnded.connect(self.recordingEnded)
        self._commChannel.sigUpdatePycroManagerTimePoint.connect(self.updateProgressBar)
        self._commChannel.sharedAttrs.sigAttributeSet.connect(self.attrChanged)
        self._commChannel.sigSnapImg.connect(self.snap)
        self._commChannel.sigStartRecordingExternal.connect(self.startRecording)

        # Connect PycroManagerWidget signals
        self._widget.sigOpenRecFolderClicked.connect(self.openFolder)
        self._widget.sigSpecFileToggled.connect(self._widget.setCustomFilenameEnabled)

        self._widget.sigSpecFramesPicked.connect(self.specFrames)
        self._widget.sigSpecTimePicked.connect(self.specTime)
        self._widget.sigSpecZStackPicked.connect(self.specZStack)
        self._widget.sigSpecXYListPicked.connect(self.specXYList)
        self._widget.sigSpecXYZListPicked.connect(self.specXYZList)

        self._widget.sigSnapRequested.connect(self.snap)
        self._widget.sigRecToggled.connect(self.toggleREC)
        
        self._widget.sigTableDataDumped.connect(self.parseTableData)
        self._widget.sigTableLoaded.connect(self.readPointsJSONData)
        self.xyScan = None
        self.xyzScan = None
        
        # Feedback signal to the widget in case of failure to load JSON file
        self.sigFailedToLoadJSON.connect(self._widget.displayFailedJSONLoad)

    def openFolder(self):
        """ Opens current folder in File Explorer. """
        folder = self._widget.getRecFolder()
        if not os.path.exists(folder):
            os.makedirs(folder)
        ostools.openFolderInOS(folder)

    def snapSaveModeChanged(self):
        saveMode = SaveMode(self._widget.getSnapSaveMode())
        self._widget.setsaveFormatEnabled(saveMode != SaveMode.RAM)

    def snap(self):
        self.updateRecAttrs(isSnapping=True)

        attrs = {
            self._master.pycroManagerAcquisition.currentDetector: self._commChannel.sharedAttrs.getHDF5Attributes()
        }

        folder = self._widget.getRecFolder()
        if not os.path.exists(folder):
            os.makedirs(folder)
        time.sleep(0.01)
        
        savename =  self.getFileName() + '_snap'
        self._master.pycroManagerAcquisition.snap(folder, savename, SaveMode(self._widget.getSnapSaveMode()), attrs)

    # TODO: refactor this method and call it "start recording" or something;
    # then connect hook function callbacks to notify end recording
    def toggleREC(self, checked):
        if checked:
            """ Start or end recording. """
            self.updateRecAttrs(isSnapping=False)

            folder = self._widget.getRecFolder()
            if not os.path.exists(folder):
                os.makedirs(folder)
            time.sleep(0.01)
            savename = os.path.join(folder, self.getFileName()) + '_rec'
            
            maximumValueProgressBar = 100
            
            if self.recMode == PycroManagerAcquisitionMode.Frames:
                maximumValueProgressBar = self._widget.getNumExpositions()
            elif self.recMode == PycroManagerAcquisitionMode.Time:
                maximumValueProgressBar = self._widget.getTimeToRec() * 1000 // self._master.pycroManagerAcquisition.exposureTime
            elif self.recMode == PycroManagerAcquisitionMode.ZStack:
                start, stop, step = self._widget.getZStackArgs()
                maximumValueProgressBar = len(np.linspace(start, stop, (stop - start) / step))
            elif self.recMode == PycroManagerAcquisitionMode.XYList:
                maximumValueProgressBar = len(self.xyScan)
            elif self.recMode == PycroManagerAcquisitionMode.XYZList:
                maximumValueProgressBar = len(self.xyzScan)
            
            self._widget.setProgressBarMaximum(maximumValueProgressBar)
            
            # packing arguments
            recordingArgs = {
                "Acquisition" : {
                    "directory" : folder,
                    "name" : savename,
                    "image_process_fn": None,
                    "event_generation_hook_fn": None,
                    "pre_hardware_hook_fn":  None,
                    "post_hardware_hook_fn":  None,
                    "post_camera_hook_fn": None,
                    "notification_callback_fn": None,
                    "image_saved_fn":  None,
                    "napari_viewer" : None,
                    "debug" : False,    
                },
                "multi_d_acquisition_events" : {
                    "num_time_points": self.__calculateNumTimePoints(),
                    "time_interval_s": self.__calculateTimeIntervalS(),
                    "z_start": self._widget.getZStackArgs()[0] if self.recMode == PycroManagerAcquisitionMode.ZStack else None,
                    "z_end": self._widget.getZStackArgs()[1] if self.recMode == PycroManagerAcquisitionMode.ZStack else None,
                    "z_step": self._widget.getZStackArgs()[2] if self.recMode == PycroManagerAcquisitionMode.ZStack else None,
                    "channel_group": None,
                    "channels": None,
                    "channel_exposures_ms": None,
                    "xy_positions": np.array(self.xyScan) if self.recMode == PycroManagerAcquisitionMode.XYList else None,
                    "xyz_positions": np.array(self.xyzScan) if self.recMode == PycroManagerAcquisitionMode.XYZList else None,
                    "position_labels": self.__checkLabels(),
                    "order": "tpcz" # todo: make this a parameter in the widget
                }
            }
            
            self.__logger.info(f"Recording {maximumValueProgressBar} time points at {self._master.pycroManagerAcquisition.exposureTime} ms")
            self._widget.setProgressBarVisibility(True)
            self._master.pycroManagerAcquisition.startRecording(self.recMode, recordingArgs)
        else:
            # do nothing... for now
            pass
    
    def __calculateNumTimePoints(self) -> list:
        if self.recMode == PycroManagerAcquisitionMode.Frames:
            return self._widget.getNumExpositions()
        if self.recMode == PycroManagerAcquisitionMode.Time:
            return self._widget.getTimeToRec() * 1000 // self._master.pycroManagerAcquisition.exposureTime
        else:
            return None
    
    def __calculateTimeIntervalS(self) -> int:
        if self.recMode == PycroManagerAcquisitionMode.Time:
            return (self._widget.getTimeToRec() * 1000 / self._master.pycroManagerAcquisition.exposureTime) * 1e-3
        else:
            return 0
    
    def __checkLabels(self) -> Union[None, list]:
        if self.recMode == PycroManagerAcquisitionMode.XYList:
            return self.xyScan.labels()
        elif self.recMode == PycroManagerAcquisitionMode.XYZList:
            return self.xyzScan.labels()
        else:
            return None

    def recordingStarted(self):
        self._widget.setFieldsEnabled(False)

    def recordingCycleEnded(self):
        self._widget.updateProgressBar(0)
        self._widget.setRecButtonChecked(False)
        self._widget.setFieldsEnabled(True)

    def recordingEnded(self):
        self.recordingCycleEnded()
    
    def setProgressBarMaximum(self, maximum: int):
        self._widget.setProgressBarMaximum(maximum)
    
    def updateProgressBar(self, timePoint: int):
        self._widget.updateProgressBar(timePoint)

    def specFrames(self):
        self._widget.checkSpecFrames()
        self._widget.setEnabledParams(specFrames=True)
        self.recMode = PycroManagerAcquisitionMode.Frames

    def specTime(self):
        self._widget.checkSpecTime()
        self._widget.setEnabledParams(specTime=True)
        self.recMode = PycroManagerAcquisitionMode.Time
    
    def specZStack(self):
        self._widget.checkSpecZStack()
        self._widget.setEnabledParams(specZStack=True)
        self.recMode = PycroManagerAcquisitionMode.ZStack
    
    def specXYList(self):
        self._widget.checkXYList()
        self._widget.setEnabledParams(specXYList=True)
        self.recMode = PycroManagerAcquisitionMode.XYList
    
    def specXYZList(self):
        self._widget.checkXYZList()
        self._widget.setEnabledParams(specXYZList=True)
        self.recMode = PycroManagerAcquisitionMode.XYZList

    def setRecMode(self, recMode):
        if recMode == PycroManagerAcquisitionMode.Frames:
            self.specFrames()
        elif recMode == PycroManagerAcquisitionMode.Time:
            self.specTime()
        elif recMode == PycroManagerAcquisitionMode.ZStack:
            self.specZStack()
        elif recMode == PycroManagerAcquisitionMode.XYList:
            self.specXYList()
        elif recMode == PycroManagerAcquisitionMode.XYZList:
            self.specXYZList()
        else:
            raise ValueError(f'Invalid RecMode {recMode} specified')
    
    def parseTableData(self, coordinates: str, points: list):
        """ Parses the table data from the widget and creates a list of points.
        Required for sanity check of the data points.
        """
        if coordinates == 'XY':
            self.xyScan = PycroManagerXYScan(
                [
                    PycroManagerXYPoint(**point) for point in points
                ]
            )
        else:
            self.xyzScan = PycroManagerXYZScan(
                [
                    PycroManagerXYZPoint(**point) for point in points
                ]
            )
        
    def readPointsJSONData(self, coordinates: str, filePath: str):
        """ Reads the JSON file containing the points data and creates a list of points.
        Required for sanity check of the data points.
        """
        with open(filePath, "r") as file:
            try:
                if coordinates == 'XY':
                    self.xyScan = PycroManagerXYScan(
                        [
                            PycroManagerXYPoint(**data) for data in json.load(file)
                        ]
                    )
                else:
                    self.xyzScan = PycroManagerXYZScan(
                        [
                            PycroManagerXYZPoint(**data) for data in json.load(file)
                        ]
                    )
            except Exception as e:
                errorMsg = f"Error reading JSON file {filePath}: {e}"
                self.__logger.error(errorMsg)
                self.sigFailedToLoadJSON.emit(coordinates, errorMsg)

    def getFileName(self):
        """ Gets the filename of the data to save. """
        filename = self._widget.getCustomFilename()
        if filename is None:
            filename = time.strftime('%Hh%Mm%Ss')
        return filename

    def attrChanged(self, key, value):
        if self.settingAttr or len(key) != 2 or key[0] != _attrCategory or value == 'null':
            return

        if key[1] == _recModeAttr:
            if value == 'Snap':
                return
            self.setRecMode(PycroManagerAcquisitionMode[value])
        elif key[1] == _framesAttr:
            self._widget.setNumExpositions(value)
        elif key[1] == _timeAttr:
            self._widget.setTimeToRec(value)

    def setSharedAttr(self, attr, value):
        self.settingAttr = True
        try:
            self._commChannel.sharedAttrs[(_attrCategory, attr)] = value
        finally:
            self.settingAttr = False

    def updateRecAttrs(self, *, isSnapping):
        self.setSharedAttr(_framesAttr, 'null')
        self.setSharedAttr(_timeAttr, 'null')

        if isSnapping:
            self.setSharedAttr(_recModeAttr, 'Snap')
        else:
            self.setSharedAttr(_recModeAttr, self.recMode.name)
            if self.recMode == PycroManagerAcquisitionMode.Frames:
                self.setSharedAttr(_framesAttr, self._widget.getNumExpositions())
            elif self.recMode == PycroManagerAcquisitionMode.Time:
                self.setSharedAttr(_timeAttr, self._widget.getTimeToRec())

    @APIExport(runOnUIThread=True)
    def snapImage(self, output: bool = False) -> Optional[np.ndarray]:
        """ Take a snap and save it to a .tiff file at the set file path. """
        if output:
            return self.snapNumpy()
        else:
            self.snap()

    @APIExport(runOnUIThread=True)
    def startRecording(self) -> None:
        """ Starts recording with the set settings to the set file path. """
        self._widget.setRecButtonChecked(True)

    @APIExport(runOnUIThread=True)
    def stopRecording(self) -> None:
        """ Stops recording. """
        self._widget.setRecButtonChecked(False)

    @APIExport(runOnUIThread=True)
    def setRecModeSpecFrames(self, numFrames: int) -> None:
        """ Sets the recording mode to record a specific number of frames. """
        self.specFrames()
        self._widget.setNumExpositions(numFrames)

    @APIExport(runOnUIThread=True)
    def setRecModeSpecTime(self, secondsToRec: Union[int, float]) -> None:
        """ Sets the recording mode to record for a specific amount of time.
        """
        self.specTime()
        self._widget.setTimeToRec(secondsToRec)

    @APIExport(runOnUIThread=True)
    def setRecModeScanOnce(self) -> None:
        """ Sets the recording mode to record a single scan. """
        self.recScanOnce()

    @APIExport(runOnUIThread=True)
    def setRecModeScanTimelapse(self, lapsesToRec: int, freqSeconds: float,
                                timelapseSingleFile: bool = False) -> None:
        """ Sets the recording mode to record a timelapse of scans. """
        self.recScanLapse()
        self._widget.setTimelapseTime(lapsesToRec)
        self._widget.setTimelapseFreq(freqSeconds)
        self._widget.setTimelapseSingleFile(timelapseSingleFile)

    @APIExport(runOnUIThread=True)
    def setDetectorToRecord(self, detectorName: Union[List[str], str, int],
                            multiDetectorSingleFile: bool = False) -> None:
        """ Sets which detectors to record. One can also pass -1 as the
        argument to record the current detector, or -2 to record all detectors.
        """
        if isinstance(detectorName, int):
            self._widget.setDetectorMode(detectorName)
        else:
            if isinstance(detectorName, str):
                detectorName = [detectorName]
            self._widget.setDetectorMode(-3)
            self._widget.setSelectedSpecificDetectors(detectorName)
            self._widget.setMultiDetectorSingleFile(multiDetectorSingleFile)

    @APIExport(runOnUIThread=True)
    def setRecFilename(self, filename: Optional[str]) -> None:
        """ Sets the name of the file to record to. This only sets the name of
        the file, not the full path. One can also pass None as the argument to
        use a default time-based filename. """
        if filename is not None:
            self._widget.setCustomFilename(filename)
        else:
            self._widget.setCustomFilenameEnabled(False)

    @APIExport(runOnUIThread=True)
    def setRecFolder(self, folderPath: str) -> None:
        """ Sets the folder to save recordings into. """
        self._widget.setRecFolder(folderPath)


_attrCategory = 'Rec'
_recModeAttr = 'Mode'
_framesAttr = 'Frames'
_timeAttr = 'Time'


# Copyright (C) 2020-2021 ImSwitch developers
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
