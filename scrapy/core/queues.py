import uuid
import os.path


from queuelib.queue import (
        FifoDiskQueue,
        LifoDiskQueue,
        FifoSQLiteQueue,
        LifoSQLiteQueue,
        )


def unique_files_queue(queue_class):

    class UniqueFilesQueue(queue_class):
        def __init__(self, path):
            path = path + "-" + uuid.uuid4().hex
            while os.path.exists(path):
                path = path + "-" + uuid.uuid4().hex

            super().__init__(path)

    return UniqueFilesQueue


UniqueFileFifoDiskQueue = unique_files_queue(FifoDiskQueue)
UniqueFileLifoDiskQueue = unique_files_queue(LifoDiskQueue)
UniqueFileFifoSQLiteQueue = unique_files_queue(FifoSQLiteQueue)
UniqueFileLifoSQLiteQueue = unique_files_queue(LifoSQLiteQueue)
