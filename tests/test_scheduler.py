import contextlib
import shutil
import tempfile
import unittest

from scrapy.crawler import Crawler
from scrapy.core.scheduler import Scheduler
from scrapy.http import Request
from scrapy.pqueues import _scheduler_slot_read, _scheduler_slot_write
from scrapy.signals import request_reached_downloader, response_downloaded
from scrapy.spiders import Spider

class MockCrawler(Crawler):
    def __init__(self, priority_queue_cls, jobdir):

        settings = dict(LOG_UNSERIALIZABLE_REQUESTS=False,
                       SCHEDULER_DISK_QUEUE='scrapy.squeues.PickleLifoDiskQueue',
                       SCHEDULER_MEMORY_QUEUE='scrapy.squeues.LifoMemoryQueue',
                       SCHEDULER_PRIORITY_QUEUE=priority_queue_cls,
                       JOBDIR=jobdir,
                       DUPEFILTER_CLASS='scrapy.dupefilters.BaseDupeFilter')
        super(MockCrawler, self).__init__(Spider, settings)


class SchedulerHandler:
    priority_queue_cls = None
    jobdir = None

    def create_scheduler(self):
        self.mock_crawler = MockCrawler(self.priority_queue_cls, self.jobdir)
        self.scheduler = Scheduler.from_crawler(self.mock_crawler)
        self.spider = Spider(name='spider')
        self.scheduler.open(self.spider)

    def close_scheduler(self):
        self.scheduler.close('finished')
        self.mock_crawler.stop()

    def setUp(self):
        self.create_scheduler()

    def tearDown(self):
        self.close_scheduler()


_PRIORITIES = [("http://foo.com/a", -2),
               ("http://foo.com/d", 1),
               ("http://foo.com/b", -1),
               ("http://foo.com/c", 0),
               ("http://foo.com/e", 2)]


_URLS = {"http://foo.com/a", "http://foo.com/b", "http://foo.com/c"}


class BaseSchedulerInMemoryTester(SchedulerHandler):
    def test_length(self):
        self.assertFalse(self.scheduler.has_pending_requests())
        self.assertEqual(len(self.scheduler), 0)

        for url in _URLS:
            self.scheduler.enqueue_request(Request(url))

        self.assertTrue(self.scheduler.has_pending_requests())
        self.assertEqual(len(self.scheduler), len(_URLS))

    def test_dequeue(self):
        for url in _URLS:
            self.scheduler.enqueue_request(Request(url))

        urls = set()
        while self.scheduler.has_pending_requests():
            urls.add(self.scheduler.next_request().url)

        self.assertEqual(urls, _URLS)

    def test_dequeue_priorities(self):
        for url, priority in _PRIORITIES:
            self.scheduler.enqueue_request(Request(url, priority=priority))

        priorities = list()
        while self.scheduler.has_pending_requests():
            priorities.append(self.scheduler.next_request().priority)

        self.assertEqual(priorities, sorted([x[1] for x in _PRIORITIES], key=lambda x: -x))


class BaseSchedulerOnDiskTester(SchedulerHandler):

    def setUp(self):
        self.jobdir = tempfile.mkdtemp()
        self.create_scheduler()

    def tearDown(self):
        self.close_scheduler()

        shutil.rmtree(self.jobdir)
        self.jobdir = None

    def test_length(self):
        self.assertFalse(self.scheduler.has_pending_requests())
        self.assertEqual(len(self.scheduler), 0)

        for url in _URLS:
            self.scheduler.enqueue_request(Request(url))

        self.close_scheduler()
        self.create_scheduler()

        self.assertTrue(self.scheduler.has_pending_requests())
        self.assertEqual(len(self.scheduler), len(_URLS))

    def test_dequeue(self):
        for url in _URLS:
            self.scheduler.enqueue_request(Request(url))

        self.close_scheduler()
        self.create_scheduler()

        urls = set()
        while self.scheduler.has_pending_requests():
            urls.add(self.scheduler.next_request().url)

        self.assertEqual(urls, _URLS)

    def test_dequeue_priorities(self):
        for url, priority in _PRIORITIES:
            self.scheduler.enqueue_request(Request(url, priority=priority))

        self.close_scheduler()
        self.create_scheduler()

        priorities = list()
        while self.scheduler.has_pending_requests():
            priorities.append(self.scheduler.next_request().priority)

        self.assertEqual(priorities, sorted([x[1] for x in _PRIORITIES], key=lambda x: -x))


class TestSchedulerInMemory(BaseSchedulerInMemoryTester, unittest.TestCase):
    priority_queue_cls = 'queuelib.PriorityQueue'


class TestSchedulerOnDisk(BaseSchedulerOnDiskTester, unittest.TestCase):
    priority_queue_cls = 'queuelib.PriorityQueue'


_SLOTS = [("http://foo.com/a", 'a'),
          ("http://foo.com/b", 'a'),
          ("http://foo.com/c", 'b'),
          ("http://foo.com/d", 'b'),
          ("http://foo.com/e", 'd'),
          ("http://foo.com/f", 'd'),
          ("http://foo.com/g", 'c'),
          ("http://foo.com/h", 'c')]


class TestSchedulerWithRoundRobinInMemory(BaseSchedulerInMemoryTester, unittest.TestCase):
    priority_queue_cls = 'scrapy.pqueues.RoundRobinPriorityQueue'

    def test_round_robin(self):
        for url, slot in _SLOTS:
            request = Request(url)
            _scheduler_slot_write(request, slot)
            self.scheduler.enqueue_request(request)

        slots = list()
        while self.scheduler.has_pending_requests():
            slots.append(_scheduler_slot_read(self.scheduler.next_request()))

        for i in range(0, len(_SLOTS), 2):
            self.assertNotEqual(slots[i], slots[i+1])

    def test_is_meta_set(self):
        url = "http://foo.com/a"
        request = Request(url)
        if _scheduler_slot_read(request):
            _scheduler_slot_write(request, None)
        self.scheduler.enqueue_request(request)
        self.assertIsNotNone(_scheduler_slot_read(request, None), None)


class TestSchedulerWithRoundRobinOnDisk(BaseSchedulerOnDiskTester, unittest.TestCase):
    priority_queue_cls = 'scrapy.pqueues.RoundRobinPriorityQueue'

    def test_round_robin(self):
        for url, slot in _SLOTS:
            request = Request(url)
            _scheduler_slot_write(request, slot)
            self.scheduler.enqueue_request(request)

        self.close_scheduler()
        self.create_scheduler()

        slots = list()
        while self.scheduler.has_pending_requests():
            slots.append(_scheduler_slot_read(self.scheduler.next_request()))

        for i in range(0, len(_SLOTS), 2):
            self.assertNotEqual(slots[i], slots[i+1])

    def test_is_meta_set(self):
        url = "http://foo.com/a"
        request = Request(url)
        if _scheduler_slot_read(request):
            _scheduler_slot_write(request, None)
        self.scheduler.enqueue_request(request)

        self.close_scheduler()
        self.create_scheduler()

        self.assertIsNotNone(_scheduler_slot_read(request, None), None)


@contextlib.contextmanager
def mkdtemp():
    dir = tempfile.mkdtemp()
    yield dir
    shutil.rmtree(dir)


def _migration():

    with mkdtemp() as tmp_dir:
        prev_scheduler_handler = SchedulerHandler()
        prev_scheduler_handler.priority_queue_cls = 'queuelib.PriorityQueue'
        prev_scheduler_handler.jobdir = tmp_dir

        prev_scheduler_handler.create_scheduler()
        for url in _URLS:
            prev_scheduler_handler.scheduler.enqueue_request(Request(url))
        prev_scheduler_handler.close_scheduler()

        next_scheduler_handler = SchedulerHandler()
        next_scheduler_handler.priority_queue_cls = 'scrapy.pqueues.RoundRobinPriorityQueue'
        next_scheduler_handler.jobdir = tmp_dir

        next_scheduler_handler.create_scheduler()


class TestMigration(unittest.TestCase):
    def test_migration(self):
        self.assertRaises(ValueError, _migration)


class TestSchedulerWithDownloaderAwareInMemory(BaseSchedulerInMemoryTester, unittest.TestCase):
    priority_queue_cls = 'scrapy.pqueues.DownloaderAwarePriorityQueue'

    def test_logic(self):
        for url, slot in _SLOTS:
            request = Request(url)
            _scheduler_slot_write(request, slot)
            self.scheduler.enqueue_request(request)

        slots = list()
        requests = list()
        while self.scheduler.has_pending_requests():
            request = self.scheduler.next_request()
            slots.append(_scheduler_slot_read(self.scheduler.next_request()))
            self.mock_crawler.signals.send_catch_log(
                    signal=request_reached_downloader,
                    request=request,
                    spider=self.spider
                    )
            requests.append(request)

        for request in requests:
            self.mock_crawler.signals.send_catch_log(signal=response_downloaded,
                                                     request=request,
                                                     response=None,
                                                     spider=self.spider)

        unique_slots = len(set(s for _, s in _SLOTS))
        for i in range(0, len(_SLOTS), unique_slots):
            part = slots[i:i + unique_slots]
            self.assertEqual(len(part), len(set(part)))


class TestSchedulerWithDownloaderAwareOnDisk(BaseSchedulerOnDiskTester, unittest.TestCase):
    priority_queue_cls = 'scrapy.pqueues.DownloaderAwarePriorityQueue'
    def test_logic(self):
        for url, slot in _SLOTS:
            request = Request(url)
            _scheduler_slot_write(request, slot)
            self.scheduler.enqueue_request(request)

        self.close_scheduler()
        self.create_scheduler()

        slots = list()
        requests = list()
        while self.scheduler.has_pending_requests():
            request = self.scheduler.next_request()
            slots.append(_scheduler_slot_read(self.scheduler.next_request()))
            self.mock_crawler.signals.send_catch_log(
                    signal=request_reached_downloader,
                    request=request,
                    spider=self.spider
                    )
            requests.append(request)

        for request in requests:
            self.mock_crawler.signals.send_catch_log(signal=response_downloaded,
                                                     request=request,
                                                     response=None,
                                                     spider=self.spider)

        unique_slots = len(set(s for _, s in _SLOTS))
        for i in range(0, len(_SLOTS), unique_slots):
            part = slots[i:i + unique_slots]
            self.assertEqual(len(part), len(set(part)))
