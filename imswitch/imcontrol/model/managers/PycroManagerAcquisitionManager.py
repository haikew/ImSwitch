from traceback import format_exc
from pycromanager import Core, Acquisition, multi_d_acquisition_events, AcqNotification
from imswitch.imcommon.framework import Signal, SignalInterface, Thread, Worker
from imswitch.imcommon.framework.pycromanager import PycroManagerAcquisitionMode
from imswitch.imcommon.model import initLogger, SaveMode
from tifffile.tifffile import TiffWriter
import os
import numpy as np
        
class PycroManagerAcquisitionManager(SignalInterface):
    
    sigRecordingStarted = Signal()
    sigRecordingEnded = Signal()
    sigRecordingError = Signal(str) # (error)
    sigPycroManagerTimePointUpdated = Signal(int) # (timePoint)
    sigMemorySnapAvailable = Signal(
        str, np.ndarray, object, bool
    )  # (name, image, filePath, savedToDisk)
    sigMemoryRecordingAvailable = Signal(
        str, object, object, bool
    )  # (name, file, filePath, savedToDisk)
    
    def __init__(self, detectorsManager):
        super().__init__()
        self.__logger = initLogger(self)
        self.__detectorsManager = detectorsManager
        self.__core = Core()
        self.__acquisitionThread = Thread()
        self.__acquisitionWorker = PycroManagerAcquisitionWorker(self)
        self.__acquisitionWorker.moveToThread(self.__acquisitionThread)
        self.__acquisitionThread.started.connect(self.__acquisitionWorker.run)    
    
    def snap(self, folder: str, savename: str, saveMode: SaveMode, attrs: dict):
        """ Snaps an image calling an instance of the Pycro-Manager backend Core. 
        """
        # TODO: support multiple extension types?
        extension = ".ome.tiff"
        savename += extension
        fullPath = os.path.join(folder, savename)

        self.__core.snap_image()
        tagged_image = self.__core.get_tagged_image()
        pixels = np.reshape(tagged_image.pix, newshape=(1, tagged_image.tags['Height'], tagged_image.tags['Width']))
    	
        # TODO: add missing metadata fields
        metadata = {
                "axes" : "TYX",
                "PhysicalSizeX" : self.__core.get_pixel_size_um(),
                "PhysicalSizeXUnit" : "µm",
                "PhysicalSizeY" : self.__core.get_pixel_size_um(),
                "PhysicalSizeYUnit" : "µm",
                "PhysicalSizeZ" : 1,
                "PhysicalSizeZUnit" : "µm",
                "TimeIncrement": self.__core.get_exposure(),
                "TimeIncrementUnit": "ms",
        }

        if saveMode == SaveMode.Disk or saveMode == SaveMode.DiskAndRAM:
            self.__logger.info("Snapping to %s", fullPath)
            with TiffWriter(fullPath, ome=True) as tif:
                tif.write(pixels, metadata=metadata, software="ImSwitch")

        if saveMode == SaveMode.RAM or saveMode == SaveMode.DiskAndRAM:
            name = self.__core.get_camera_device()
            self.sigMemorySnapAvailable.emit(name, pixels, savename, saveMode == SaveMode.DiskAndRAM)

    @property
    def core(self) -> Core:
        return self.__core
        
    def startRecording(self, recMode: PycroManagerAcquisitionMode, recordingArgs: dict):
        self.__acquisitionWorker.recordingArgs = recordingArgs
        self.__acquisitionWorker.recMode = recMode
        
        self.__logger.info("Starting recording thread")
        self.__acquisitionThread.start()
        self.sigRecordingStarted.emit()
    
    def endRecording(self):
        self.sigRecordingEnded.emit()


class PycroManagerAcquisitionWorker(Worker):    
    def __init__(self, manager: PycroManagerAcquisitionManager):
        super().__init__()
        self.__logger = initLogger(self)
        self.recMode : PycroManagerAcquisitionMode = None
        self.recordingArgs : dict = None
        self.acquisitionManager = manager
        self.__notificationDict = {
            PycroManagerAcquisitionMode.Frames: self.__notify_new_time_point,
            PycroManagerAcquisitionMode.Time: self.__notify_new_time_point,
            PycroManagerAcquisitionMode.ZStack: self.__notify_new_z_point,
            # TODO: add missing notifications
        }
    
    def __notify_new_time_point(self, msg: AcqNotification):
        # time point is offset by 1, so we add 1 to the frame number
        if msg.is_image_saved_notification():
            self.acquisitionManager.sigPycroManagerTimePointUpdated.emit(msg.id["time"] + 1)
    
    def __notify_new_z_point(self, msg: AcqNotification):
        if msg.is_image_saved_notification():
            self.acquisitionManager.sigPycroManagerTimePointUpdated.emit(msg.id["z"] + 1)
    
    def run(self) -> None:

        self.__logger.info("Generating acquisition events")
        events = multi_d_acquisition_events(**self.recordingArgs["multi_d_acquisition_events"])
        self.recordingArgs["Acquisition"]["notification_callback_fn"] = self.__notificationDict[self.recMode]
        self.recordingArgs["Acquisition"]["debug"] = True
        try:
            self.__logger.info("Starting acquisition")
            with Acquisition(**self.recordingArgs["Acquisition"]) as acq:
                acq.acquire(events)

            self.__logger.info("Acquisition finished")
        except Exception as e:
            self.__logger.error(f"An error occurred during acquisition. Shutting down.")
            self.__logger.exception(f"{e}")
            self.acquisitionManager.sigRecordingError.emit(format_exc())
        finally:
            self.acquisitionManager.sigRecordingEnded.emit()