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
counter = 0

while len(tokens) < ((26**4)*0.9):
  token = newtempname()
  if token not in tokens:
    tokens.add(token)
    seed = random.randint(0,(10**6)*0.9)
    tdata = {'token': token, "tokenid": counter, "usecount": seed, 'seed': seed}
    db.tokens.insert(tdata)
    print(str(tdata))
    counter = counter + 1

key = uuid.uuid4().hex
pins = set()
attempts = 1
counter = 0
while len(pins) < (10**6):
    pin = oath.hotp(key,attempts)
    if pin not in pins:
        pins.add(pin)
        db.pins.insert({"pin": pin, "pinid": counter})
        print('added pin ' + pin + ' pinid ' + str(counter))
        counter = counter + 1
    attempts = attempts + 1

  
print('Done.')
