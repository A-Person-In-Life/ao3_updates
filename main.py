import time
import sqlite3
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup
from bads3wrapper.s3_api import S3Api

HEADERS = {}
HEADERS["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Firefox/135.0"

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

class Work:
    def __init__(self, url, cursor, connection):
        self.connection = connection
        self.cursor = cursor
        self.work_url = url
        self.work_id = ""
        self.base_url = "https://archiveofourown.org/works/"
        self.chapter_count = None
        self.updated = False
        self.title = ""
        self.get_work_id()
        if not self.set_from_database():
            start_time = time.time()
            print("Work not found in database. Fetching metadata and downloading work.")
            self.get_metadata()
            self.download_work()
            self.database_update()
            end_time = time.time()
            print("Took " + str(end_time - start_time) + " seconds to fetch metadata and download work with ID " + self.work_id + ".")

    def get_work_id(self):
        path = urlparse(self.work_url).path 
        self.work_id = path.strip("/").split("/")[-1]
    
    def download_work(self):
        download_url = self.base_url + self.work_id + "/download?format=epub&view_adult=true"        
        response = SESSION.get(download_url)

        if response.status_code != 200:
            print(f"Failed to download work with ID: {self.work_id}. Status code: {response.status_code}")
            return False

        if "application/epub+zip" not in response.headers.get("Content-Type", ""):
            print("Download did not return an epub")
            return False

        filename = self.work_id + "_" + self.title + ".epub"
        with open("pdfs/" + filename, "wb") as file:
            file.write(response.content)
            file.close()

        print("Successfully downloaded EPUB for work " + self.work_id)
        return True
    
    def get_metadata(self):
        metadata_url = self.base_url + self.work_id + "?view_adult=true"
        response = SESSION.get(metadata_url)
        if response.status_code != 200:
            print(f"Failed to fetch metadata for work with ID: {self.work_id}. Status code: {response.status_code}")
            return
        
        else:
            print(f"Successfully fetched metadata for work with ID: {self.work_id}. Status code: {response.status_code}")
            soup = BeautifulSoup(response.content, "html.parser")

            title_tag = soup.find("h2", class_="title")
            chapters_tag = soup.find("dd", class_="chapters")

            if not title_tag or not chapters_tag:
                print("Metadata page missing expected fields")
                return

            title = title_tag.text.strip().replace("/", "-").replace(":", "-")
            current_chapter_count = chapters_tag.text.strip()

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
        self.s3_api = S3Api("config/aws_auth.txt")
    
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
                    try:
                        self.s3_api.deleteItem("fanfic/" + work.work_id + "_" + work.title + ".epub")
                    except Exception:
                        pass                    
                    self.s3_api.uploadFile(f"pdfs/{work.work_id}_{work.title}.epub", f"fanfic/{work.work_id}_{work.title}.epub")

                else:
                    print(f"Work with ID: {work.work_id} has not been updated.")

            time.sleep(3600)
        
if __name__ == "__main__":


    connection = sqlite3.connect("resources/works.db")
    cursor = connection.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS works (work_id STRING PRIMARY KEY, chapter_count STRING, updated BOOLEAN, title STRING)")
    connection.commit()

    work_urls = [
        Work("https://archiveofourown.org/works/55658536", cursor, connection),
        Work("https://archiveofourown.org/works/44789995", cursor, connection)
    ]

    monitor = ao3_monitor(work_urls)
    monitor.monitor_loop()