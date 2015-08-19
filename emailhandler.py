#! /usr/bin/python3.4

import sys
import re
import base64
import pymongo
import pickle
import logging
import logging.handlers
import copy
import uuid
import time
import datetime
import email.utils 
from email.utils import parseaddr
from redis import StrictRedis
from validate_email import validate_email
import argparse

FILESIZE=1024*1024*1024 #1MB

instance = "0"
try:
  conn=pymongo.MongoClient()
  print ("Connected successfully!!!")
except pymongo.errors.ConnectionFailure as e:
  print ("Could not connect to MongoDB: %s" % e )

logger = logging.getLogger('mailHandler')

OUR_DOMAIN = 'redr.in'

db = conn.inbounddb

#below regex objs are for handling new thread mails
taddrcomp = re.compile('([\w.-]+(__)[\w.-]+)@'+OUR_DOMAIN)

subcomp = re.compile('__')

rclient = StrictRedis()

def getdomain(a):
  return a.split('@')[-1]
  
def getuserid(a):
  return a.split('@')[0]

def isourdomain( a):
  return getdomain(a) == OUR_DOMAIN

def isknowndomain(a):
  if isourdomain(a):
    return True
  known = db.domains.find_one({'domain': getdomain(a)})
  if not known:
    return False
  return True

def getuser(a):
  if isourdomain(a):
    user = db.users.find_one({'mapped': a})
  else:
    user = db.users.find_one({'actual': a})
  return user

def valid_uuid4(a):
  userid = getuserid(a)
  try:
    val = uuid.UUID(userid, version=4)
  except ValueError:
    # If it's a value error, then the string 
    # is not a valid hex code for a UUID.
    return False

  # If the uuid_string is a valid hex code, 
  # but an invalid uuid4,
  # the UUID.__init__ will convert it to a 
  # valid uuid4. This is bad for validation purposes.
  return val.hex == userid

def isregistereduser(a):
  """ check whether the user address is a registered one or generated one """
  return not valid_uuid4(a)

def valid_email_addresses (msg,allrecipients,from_email):
  for id,name in allrecipients:
    success = isregistereduser(id)
    if success:
      return True
  success =  getuser(from_email)
  if success:
    return True
  return False
 
def isUserEmailTaggedForLI(a):
  """ Check if the user address is tagged for LI """
  user = getuser(a)
  if user and 'tagged' in user: 
    return user['tagged']
  return None

def getactual(a):
  user = getuser(a)
  if not user:
    return None
  return user['actual']

def emailHandler(ev, pickledEv):
  ''' 
    SPAM check is not done here ... it should have been handled in earlier stage of pipeline
  '''
  emaildump = (ev['msg']['raw_msg'])
  
  prepareEmailDisplay
  
 
  #sendInvite(totalinvitercpts, fromname)
  return True

if __name__ == '__main__':
  parser = argparse.ArgumentParser(description='Redr-EmailHandler .')
  parser.add_argument('-i','--instance', help='Instance Num of this script ', required=True)
  args = parser.parse_args()
  argsdict = vars(args)
  instance = argsdict['instance']

  formatter = logging.Formatter('REDR-MAILHANDLER-['+instance+']:%(asctime)s %(levelname)s - %(message)s')
  hdlr = logging.handlers.RotatingFileHandler('/var/tmp/redrin_mailhandler_'+instance+'.log', maxBytes=FILESIZE, backupCount=10)
  hdlr.setFormatter(formatter)
  logger.addHandler(hdlr) 
  logger.setLevel(logging.DEBUG)

  redrmailhandlerBackup = 'redrredrmailhandlerBackup_' + instance
  logger.info("MailHandlerBackUp ListName : {} ".format(redrmailhandlerBackup))

  while True:
    backupmail = False
    if (rclient.llen(redrmailhandlerBackup)):
        ev = rclient.brpop (redrmailhandlerBackup)
        backupmail = True
        pickledEv = pickle.dumps(ev)
        logger.info("Getting events from {}".format(redrmailhandlerBackup))
    else:
        pickledEv = rclient.brpoplpush('redrmailhandler', redrmailhandlerBackup)
        ev = pickle.loads(pickledEv)
        logger.info("Getting events from {}".format('redrmailhandler'))
    emailHandler(ev, pickledEv)
    if(not backupmail):
      logger.info ('len of {} is : {}'.format(redrmailhandlerBackup, rclient.llen(redrmailhandlerBackup)))
      rclient.lrem(redrmailhandlerBackup, 0, pickledEv)
      logger.info ('len of {} is : {}'.format(redrmailhandlerBackup, rclient.llen(redrmailhandlerBackup)))

