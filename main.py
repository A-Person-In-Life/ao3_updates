import asyncio
import sqlite3
import AO3
import smtplib
import email
from bads3wrapper.s3_api import S3Api


class Work:
    def __init__(self, work_id, cursor, connection):
        self.connection = connection
        self.cursor = cursor
        self.work_id = str(work_id)
        self.work = None

        if not self.set_from_database():
            self.work = AO3.Work(work_id)
            self.title = self.work.title.replace("/", "-").replace(":", "-")
            self.chapter_count = len(self.work.chapters)
            self.updated = False
            self.is_new = True
            print(f"New work found: {self.title}.")
        else:
            self.is_new = False

    async def download_work(self, s3_api):
        if self.work is None:
            self.work = AO3.Work(self.work_id)
        with open(f"pdfs/{self.title}.pdf", "wb") as f:
            f.write(self.work.download("PDF"))
        print(f"Downloaded: {self.title} ({self.work_id})")
        s3_path = f"fanfic/{self.work_id}_{self.title}.pdf"
        try:
            await s3_api.deleteItem(s3_path)
        except Exception:
            pass
        await s3_api.uploadFile(f"pdfs/{self.title}.pdf", s3_path)

    def check_for_update(self):
        if self.work is None:
            self.work = AO3.Work(self.work_id)
        self.work.reload()
        new_chapter_count = len(self.work.chapters)
        if new_chapter_count != self.chapter_count:
            self.chapter_count = new_chapter_count
            self.updated = True
            self.database_update()

    def database_update(self):
        self.cursor.execute(
            "INSERT OR REPLACE INTO works (work_id, chapter_count, updated, title) VALUES (?, ?, ?, ?)",
            (self.work_id, self.chapter_count, self.updated, self.title),
        )
        self.connection.commit()

    def set_from_database(self):
        self.cursor.execute(
            "SELECT chapter_count, updated, title FROM works WHERE work_id = ?",
            (self.work_id,),
        )
        result = self.cursor.fetchone()
        if not result:
            return False
        self.chapter_count, self.updated, self.title = result
        return True


class AO3Monitor:
    def __init__(self, works):
        self.works = works

    async def monitor_loop(self):
        async with S3Api("config/aws_auth.txt") as s3_api:
            for work in self.works:
                if work.is_new:
                    await work.download_work(s3_api)
                    work.database_update()

            while True:
                for work in self.works:
                    work.check_for_update()

                    if work.updated:
                        print(f"Update found: {work.title}. Downloading.")
                        await work.download_work(s3_api)
                        work.updated = False
                        work.database_update()
                    else:
                        print(f"No update: {work.title}")

                await asyncio.sleep(3600)

    def send_email_notification(self, work):
        with open("config/email_auth.txt") as f:
            email_address = f.readline().strip()
            password = f.read().strip()


if __name__ == "__main__":
    connection = sqlite3.connect("resources/works.db")
    cursor = connection.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS works "
        "(work_id STRING PRIMARY KEY, chapter_count STRING, updated BOOLEAN, title STRING)"
    )
    connection.commit()

    work_ids = [
        55658536,
        44789995,
        28310742
    ]

    works = [Work(work_id, cursor, connection) for work_id in work_ids]
    monitor = AO3Monitor(works)
    asyncio.run(monitor.monitor_loop())