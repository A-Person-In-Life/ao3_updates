import requests
from bs4 import BeautifulSoup
import time
import sqlite3
import sys

sys.path.append("s3_api")
from s3api import S3Api

class work:
    def __init__(self, url, cursor, connection):
        self.connection = connection
        self.cursor = cursor
        self.headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:135.0) Gecko/20100101 Firefox/135.0"}
        self.work_url = url
        self.work_id = ""
        self.base_url = "https://archiveofourown.org/works/"
        self.download_type = ".pdf"
        self.chapter_count = None
        self.updated = False
        self.title = ""

        self.get_work_id()
        if not self.set_from_database():
            print("Work not found in database. Fetching metadata and downloading work.")
            self.get_metadata()
            self.database_update()

    def get_work_id(self):
        self.work_id = self.work_url[len(self.base_url):]
        return
    
    def download_work(self):
        download_url = self.base_url + self.work_id + "/download" + self.download_type
        response = requests.get(download_url)

        if response.status_code != 200:
            print(f"Failed to download work with ID: {self.work_id}. Status code: {response.status_code}")
            return
        
        else:
            print(f"Successfully downloaded work with ID: {self.work_id}. Status code: {response.status_code}")
            filename = f"{self.work_id}_{self.title}.pdf"
            with open(f"pdfs/{filename}", "wb") as f:
                f.write(response.content)
    
    def get_metadata(self):
        metadata_url = self.base_url + self.work_id
        response = requests.get(metadata_url)
        if response.status_code != 200:
            print(f"Failed to fetch metadata for work with ID: {self.work_id}. Status code: {response.status_code}")
            return
        
        else:
            print(f"Successfully fetched metadata for work with ID: {self.work_id}. Status code: {response.status_code}")
            soup = BeautifulSoup(response.content, "html.parser")
            current_chapter_count = soup.find("dd", class_="chapters").text.strip()
            title = soup.find("h2", class_="title").text.strip()
            title = title.replace("/", "-").replace(":", "-")

            if self.chapter_count is None:
                self.chapter_count = current_chapter_count
                self.title = title

            elif current_chapter_count != self.chapter_count:
                self.chapter_count = current_chapter_count
                self.updated = True
                self.title = title
                self.database_update()

    def database_update(self):
        self.cursor.execute("INSERT OR REPLACE INTO works (work_id, chapter_count, updated, title) VALUES (?, ?, ?, ?)",
                            (self.work_id, self.chapter_count, self.updated, self.title))
        self.connection.commit()
        return

    def set_from_database(self):
        self.cursor.execute("SELECT chapter_count, updated, title FROM works WHERE work_id = ?", (self.work_id,))
        result = self.cursor.fetchone()
        
        if not result:
            return False
        else:
            self.chapter_count, self.updated, self.title = result
            return True

class ao3_monitor:
    def __init__(self, work_urls):
        self.works = work_urls
        self.s3_api = S3Api("s3_api/config/aws_auth.txt")
    
    def monitor_loop(self):
        running = True
        while running:
            for work in self.works:

                work.get_metadata()

                if work.updated:
                    print(f"Work with ID: {work.work_id} has been updated. Downloading new version.")
                    work.download_work()
                    work.updated = False
                    work.database_update()
                    self.s3_api.deleteFile(f"fanfic/{work.work_id}_{work.title}.pdf")
                    self.s3_api.uploadFile(f"pdfs/{work.work_id}_{work.title}.pdf", f"fanfic/{work.work_id}_{work.title}.pdf")

                else:
                    print(f"Work with ID: {work.work_id} has not been updated.")

            time.sleep(10)
        
if __name__ == "__main__":


    connection = sqlite3.connect("resources/works.db")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS works (work_id STRING PRIMARY KEY, chapter_count STRING NOT NULL, updated BOOLEAN NOT NULL, title STRING NOT NULL)")
    connection.commit()

    work_urls = [
        work("https://archiveofourown.org/works/55658536", cursor, connection)
    ]

    monitor = ao3_monitor(work_urls)
    monitor.monitor_loop()