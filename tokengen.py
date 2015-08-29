import random
import pymongo
import oath
import uuid

characters = "abcdefghijklmnopqrstuvwxyz"

def newtempname(ln=4):
    choose = random.Random().choice
    letters = [choose(characters) for dummy in range(ln)]
    return ''.join(letters)

try:
    conn=pymongo.MongoClient()
    print ("Connected successfully!!!")
except pymongo.errors.ConnectionFailure as e:
    print ("Could not connect to MongoDB: %s" % e )
    import sys
    sys.exit()

db = conn.redrdb
tokens = set()

while len(tokens) < (26**4):
  token = newtempname()
  if token not in tokens:
    tokens.add(token)

counter = 0
for token in tokens:
  key = uuid.uuid4().hex
  pins = set()
  attempts = 1
  while len(pins) < (10**6):
    pin = oath.hotp(key,attempts)
    if pin not in pins:
      pdata = {'token': token, 'pin': pin, 'linkid': counter}
      pins.add(pin)
      db.tokens.insert(pdata)
      counter = counter + 1
    attempts = attempts + 1
  del pins
  
print('Done.')
