import asyncio
import sqlite3
import AO3
import aiosmtplib
import aiofiles
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
            self.updated = True
            self.is_new = True
            print(f"New work found: {self.title}.")
        else:
            self.is_new = False

    async def download_work(self, s3_api):
        path = f"pdfs/{self.title}.pdf"

        if self.work is None:
            self.work = await asyncio.to_thread(AO3.Work, self.work_id)

        async with aiofiles.open(path, "wb") as f:
            await f.write(await asyncio.to_thread(self.work.download, "PDF"))

        print(f"Downloaded: {self.title} ({self.work_id})")
        s3_path = f"fanfic/{path.split('/')[1]}"
        try:
            await s3_api.deleteItem(s3_path)
        except Exception:
            pass
        await s3_api.uploadFile(path, s3_path)

    async def check_for_update(self):
        if self.work is None:
            self.work = await asyncio.to_thread(AO3.Work, self.work_id)
        await asyncio.to_thread(self.work.reload)
        new_chapter_count = len(self.work.chapters)
        if new_chapter_count != self.chapter_count:
            self.chapter_count = new_chapter_count
            self.updated = True

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

        with open("config/email_auth.txt") as f:
            self.email_address = f.readline().strip()
            self.password = f.read().strip()

    async def monitor_loop(self):
        async with S3Api("config/aws_auth.txt") as self.s3_api:
            await asyncio.gather(*[self.process_work(work) for work in self.works])

            while True:
                await asyncio.gather(*[self.process_work(work) for work in self.works])
                await asyncio.sleep(3600)

    async def process_work(self, work):
        try:
            if work.is_new:
                await work.download_work(self.s3_api)
                await self.send_email_notification(work)
            else:
                await work.check_for_update()
                if work.updated:
                    print(f"Update found: {work.title}. Downloading.")
                    await work.download_work(self.s3_api)
                    await self.send_email_notification(work)
                else:
                    print(f"No update: {work.title}")
        except Exception as e:
            print(f"Error processing {work.title}: {e}")

        work.updated = False
        work.is_new = False
        work.database_update()

    async def send_email_notification(self, work):
        print(f"Sending email notification for {work.title}.")

        message = email.message.EmailMessage()
        message["From"] = self.email_address
        message["To"] = self.email_address
        message["Subject"] = f"Update for {work.title}"
        message.set_content(f"{work.title} has been updated and uploaded to S3.")

        await aiosmtplib.send(message, hostname="smtp.gmail.com", port=465, username=self.email_address, password=self.password, use_tls=True)
        print(f"Email notification sent for {work.title}.")


if __name__ == "__main__":
    connection = sqlite3.connect("resources/works.db")
    cursor = connection.cursor()
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS works "
        "(work_id STRING PRIMARY KEY, chapter_count INTEGER, updated BOOLEAN, title STRING)"
    )
    connection.commit()

    work_ids = [
        55658536,
        44789995,
        28310742,
    ]

    works = [Work(work_id, cursor, connection) for work_id in work_ids]
    monitor = AO3Monitor(works)
    asyncio.run(monitor.monitor_loop())