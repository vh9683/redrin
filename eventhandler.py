import re
import pymongo
from redis import StrictRedis
from shutil import rmtree

FOLDER_ROOT_DIR = "/tmp/redr/"

rclient = StrictRedis()

try:
    conn=pymongo.MongoClient()
    print ("Connected successfully!!!")
except pymongo.errors.ConnectionFailure as e:
    print ("Could not connect to MongoDB: %s" % e )
    import sys
    sys.exit()

db = conn.redrdb

rclient.config_set('notify-keyspace-events','Ex')

token = re.compile('[a-z]{4}')

ps = rclient.pubsub()
ps.subscribe(['__keyevent@0__:expired'])

for item in ps.listen():
  if item['type'] == 'message':
    key = item['data'].decode()
    print('received key event for ' + key)
    if token.fullmatch(key):
        print('added ' + key + ' to free list')
        rclient.rpush('tokenfreelist',pickle.dumps(key))
        link = db.links.find_one({'token': key})
        if link:
            rmtree(FOLDER_ROOT_DIR+link['folder'],ignore_errors=True)   
