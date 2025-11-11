# -*- coding: utf-8 -*-
import os
from redis import Redis
from rq import Worker, Queue

listen = ["meeting-jobs"]
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

conn = Redis.from_url(redis_url)

if __name__ == "__main__":
    # T?o các queue tuong ?ng và ch?y worker
    queues = [Queue(name, connection=conn) for name in listen]
    worker = Worker(queues)
    worker.work()
