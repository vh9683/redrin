import re
from redis import StrictRedis
from shutil import rmtree

FOLDER_ROOT_DIR = "/tmp/redr/"

rclient = StrictRedis()

rclient.config_set('notify-keyspace-events','Ex')

uid = re.compile('[a-f0-9]{32}')
token = re.compile('[a-z]{4}')

ps = rclient.pubsub()
ps.subscribe(['__keyevent@0__:expired'])

for item in ps.listen():
  if item['type'] == 'message':
    key = item['data'].decode()
    print('received key event for ' + key)
    if uid.fullmatch(key):
      print('removing folder ' + FOLDER_ROOT_DIR + '/' + key)
      rmtree(FOLDER_ROOT_DIR+'/'+key,ignore_errors=True)
    elif token.fullmatch(key):
      print('added ' + key + ' to free list')
      rclient.rpush('tokenfreelist',pickle.dumps(key))
    else:
      print('unknown type of key expired, ignoring...')

