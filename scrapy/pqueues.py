from collections import deque
import hashlib
import logging
from six.moves.urllib.parse import urlparse

from queuelib import PriorityQueue

from scrapy.core.downloader import Downloader
from scrapy.http import Request


logger = logging.getLogger(__name__)


SCHEDULER_SLOT_META_KEY = Downloader.DOWNLOAD_SLOT


def _get_from_request(request, key, default=None):
    if isinstance(request, dict):
        return request.get(key, default)

    if isinstance(request, Request):
        return getattr(request, key, default)

    raise ValueError('Bad type of request "%s"' % (request.__class__, ))


def scheduler_slot(request):
    meta = _get_from_request(request, 'meta', dict())
    slot = meta.get(SCHEDULER_SLOT_META_KEY, None)

    if slot is None:
        url = _get_from_request(request, 'url')
        slot = urlparse(url).hostname or ''
        meta[SCHEDULER_SLOT_META_KEY] = slot

    return str(slot)


def _slot_as_path(slot):
    pathable_slot = "".join([c if c.isalnum() or c in '-._' else '_' for c in slot])

    """
        as we replace some letters we can get collision for different slots
        add we add unique part
    """
    unique_slot = hashlib.md5(slot.encode('utf8')).hexdigest()

    return '-'.join([pathable_slot, unique_slot])


class PriorityAsTupleQueue(PriorityQueue):

    def __init__(self, qfactory, startprios=()):
        self.queues = {}
        self.qfactory = qfactory
        startprios = [tuple(x) for x in startprios]
        for p in startprios:
            self.queues[p] = self.qfactory(p)
        self.curprio = min(startprios) if startprios else None


class RoundRobinQueue:

    def __init__(self, qfactory, startprios={}):
        self._slots = deque()
        self.pqueues = dict()     # slot -> priority queue
        self.qfactory = qfactory  # factory for creating new internal queues

        if not startprios:
            return

        if not isinstance(startprios, dict):
            raise ValueError("Looks like your priorities file malforfemed. "
                             "Possible reason: You run scrapy with previous "
                             "version. Interrupted it. Updated scrapy. And "
                             "run again.")

        for slot, prios in startprios.items():
            self._slots.append(slot)
            self.pqueues[slot] = PriorityAsTupleQueue(self.qfactory, prios)

    def push(self, request, priority):

        slot = scheduler_slot(request)
        if slot not in self.pqueues:
            self.pqueues[slot] = PriorityAsTupleQueue(self.qfactory)
            self._slots.append(slot)
        self.pqueues[slot].push(request, (priority, _slot_as_path(slot)))

    def pop(self):
        if not self._slots:
            return
        slot = self._slots.popleft()
        queue = self.pqueues[slot]
        request = queue.pop()

        if len(queue):
            self._slots.append(slot)
        else:
            del self.pqueues[slot]
        return request

    def close(self):
        startprios = dict()
        for slot, queue in self.pqueues.items():
            prios = queue.close()
            startprios[slot] = prios
        self.pqueues.clear()
        self._slots.clear()
        return startprios

    def __len__(self):
        return sum(len(x) for x in self.pqueues.values()) if self.pqueues else 0
