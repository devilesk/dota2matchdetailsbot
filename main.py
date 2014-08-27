import time
import re
import json
import requests
from bs4 import BeautifulSoup
import praw
import ConfigParser
import sqlite3

Config = ConfigParser.ConfigParser()
Config.read('config.ini')

def handle_ratelimit(func, *args, **kwargs):
    while True:
        try:
            func(*args, **kwargs)
            break
        except praw.errors.RateLimitExceeded as error:
            print '\tSleeping for %d seconds' % error.sleep_time
            time.sleep(error.sleep_time)
            
def get_dotabuff_link(text):
    regex = re.compile("http://dotabuff.com/matches/[0-9]*")
    return regex.findall(text)
    
def escape(text):
    text = text.replace('|','&#124;')
    text = text.replace('[','&#91;')
    text = text.replace('\\','&#92;')
    text = text.replace(']','&#93;')
    text = text.replace('^','&#94;')
    text = text.replace('_','&#95;')
    text = text.replace('`','&#96;')
    text = text.replace('*','&#42;')
    text = text.replace('~','&#126;')
    return text
    
def create_message_from_link(link):
    r = requests.get(link)
    soup = BeautifulSoup(r.text)
    radiant_rows = soup.find("section", { "class" : "radiant" }).find("table").find("tbody").find_all("tr")
    dire_rows = soup.find("section", { "class" : "dire" }).find("table").find("tbody").find_all("tr")
    data = {}
    data['link'] = link
    data['id'] = soup.find("h1").get_text()
    data['result'] = soup.find("div", {"class": "match-result"}).get_text().ljust(15,'_')
    data['duration'] = soup.find("dt", text="Duration").nextSibling.get_text()
    data['mode'] = soup.find("dt", text="Game Mode").nextSibling.get_text()
    data['radiant'] = get_data_from_table(radiant_rows)
    data['dire'] = get_data_from_table(dire_rows)
    #print data
    return create_reply(data)
    
def create_reply(data):
    reply = ''
    reply += '####&#009;\n\n'
    reply += '######&#009;\n\n'
    reply += '####&#009;\n\n'
    reply += 'Hello, I noticed you mentioned a match in your post. Here are some details about that match:\n\n'
    reply += '[' + data['id'] + '](' + data['link'] + ')\n\n'
    reply += '[' + data['result'] + '](/spoiler). Duration: [' + data['duration'] + '](/spoiler). Mode: ' + data['mode'] + '.\n\n'
    reply += 'Radiant\n\n' + get_reply_table(data['radiant'])
    reply += '\n\n'
    reply += 'Dire\n\n' + get_reply_table(data['dire'])
    return reply
    
def get_reply_table(data):
    reply = "|Hero|Player|Level|K |D |A |Gold|LH|DN|XPM|GPM|HD|HH|TD|\n" \
            "|----|------|-----|-:|-:|-:|---:|-:|-:|--:|--:|-:|-:|-:|\n"
    for row in data:
        reply += get_row_string(row)
    return reply
    
def get_row_string(row):
    data = '|' + row[0] + '|'
    if row[1][0]:
        data += '[' + escape(row[1][1]) + '](' + 'http://dotabuff.com' + row[1][0] + ')|'
    else:
        data += escape(row[1][1]) + '|'
    data += '|'.join(row[2:]) + '\n'
    return data
    
def get_data_from_table(rows):
    data = []
    for row in rows:
        row_data = []
        cells = row.find_all("td")
        for i in range(0, len(cells)):
            c = cells[i]
            if i == 0:
                img = c.find("img")
                row_data.append(img['alt'])
            if i == 1:
                a = c.find("a")
                if a:
                    row_data.append((a['href'], c.get_text()))
                else:
                    row_data.append((None, c.get_text()))
            elif i >= 3 and i <= 14:
                row_data.append(c.get_text())
        data.append(row_data)
    return data

def ConfigSectionMap(section):
    dict1 = {}
    options = Config.options(section)
    for option in options:
        try:
            dict1[option] = Config.get(section, option)
            if dict1[option] == -1:
                DebugPrint('skip: %s' % option)
        except:
            print('exception on %s!' % option)
            dict1[option] = None
    return dict1

class Database(object):
    @property
    def conn(self):
        if not hasattr(self, '_connection'):
            self._connection = sqlite3.connect(ConfigSectionMap('settings')['database'])
        return self._connection

    def cursor(self):
        return self.conn.cursor()

    def init(self, clean=False):
        cur = self.cursor()
        if clean:
            cur.execute('DROP TABLE IF EXISTS posts')

        cur.execute(
            'CREATE TABLE IF NOT EXISTS posts (id INTEGER PRIMARY KEY ASC, thing_id TEXT UNIQUE)'
        )
        self.conn.commit()

    def has_processed(self, thing_id):
        c = self.cursor()
        c.execute('SELECT thing_id FROM posts WHERE thing_id = ?', (thing_id,))
        return c.fetchone() is not None

    def mark_as_processed(self, thing_id):
        c = self.cursor()
        c.execute('INSERT INTO posts (thing_id) VALUES (?)', (thing_id,))
        self.conn.commit()

db = Database()
db.init()

user_name = ConfigSectionMap('settings')['user']
password = ConfigSectionMap('settings')['pass']
subreddit = ConfigSectionMap('settings')['subreddit']
user_agent = ConfigSectionMap('settings')['useragent']

r = praw.Reddit(user_agent)
r.login(user_name, password)

subreddit_comments = praw.helpers.comment_stream(r, subreddit, limit=None)
for comment in subreddit_comments:
    dotabuff_links = get_dotabuff_link(comment.body.encode('utf8'))
    if str(comment.author)!=user_name and not db.has_processed(comment.id) and dotabuff_links:
        for link in dotabuff_links:
            msg = create_message_from_link(link)
            handle_ratelimit(comment.reply, msg)
        db.mark_as_processed(comment.id)
        time.sleep(5)