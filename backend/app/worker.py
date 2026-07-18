from redis import Redis
from rq import Queue, Worker

from .config import settings


def main() -> None:
    connection = Redis.from_url(settings.redis_url)
    queue = Queue(settings.queue_name, connection=connection)
    worker = Worker([queue], connection=connection, name="matias-3d-worker")
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
