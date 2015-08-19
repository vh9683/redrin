#! /usr/bin/python3.4

import os
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
import shutil
import subprocess

FILESIZE=1024*1024*1024 #1MB

mhcmd = 'mhonarc -nothread -nomultipg -nomain -noprintxcomments -quiet -single -nomailto '

instance = "0"

logger = logging.getLogger('mailHandler')

OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

#below regex objs are for handling new thread mails
taddrcomp = re.compile('([\w.-]+)@'+OUR_DOMAIN)

rclient = StrictRedis()

def getdomain(a):
  return a.split('@')[-1]
  
def getuserid(a):
  return a.split('@')[0]

def isourdomain( a):
  return getdomain(a) == OUR_DOMAIN

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

def processOpHtml (dstdir):
  opfile = os.path.join(dstdir, 'op.html')
  indexfile = os.path.join(dstdir, 'index.html')
  
  ignored = ['<em>Authentication-results</em>' , '<em>Delivered-to</em>', '<em>Dkim-signature</em>', '<em>In-reply-to</em>', '<em>References</em>', '<!--', '<!DOCTYPE HTML PUBLIC', "http://www.w3.org/TR/html4/loose.dtd" ]
  
  message = "<!DOCTYPE HTML>"
  opfp = open(opfile, 'r')
  for line in opfp:
    found = False
    for i in ignored:
      if i in line:
        found = True
        break

    if found == False:
      message += line.replace ('.//', '/')

  opfp.close()

  idfp = open(indexfile, 'w')
  idfp.write(message)
  idfp.close()

  return True


def emailHandler(ev, pickledEv):
  ''' 
    SPAM check is not done here ... it should have been handled in earlier stage of pipeline
  '''
  ev = emaildump
  
  toaddresses = ev['msg']['to']
  if len(toaddresses) != 1:
    return False

  to = toaddresses[0]

  if not taddrcomp.fullmatch(to):
    return False

  if not isourdomain(to):
    return False
 
  token = getuserid(to)
  if not token:
    return False
  
  tdata = rclient.get(token)
  if not tdata:
    return False

  folder = tdata['folder']
  if folder is None:
    return False
  
  if not valid_uuid4(folder):
    return False
  
  mhcmd += ' -attachmenturl ' + '/'+folder 

  mhcmd += ' -iconurlprefix ' + '/'+folder 
 
  dstdir = os.path.join (FOLDER_ROOT_DIR, folder)
 
  try :
    os.mkdir(dstdir, 0o700)
  except FileExitsUser:
    return False
 
  #TODO make use of tempfile 
  maildumpfile = os.path.join(dstdir, 'email.dump') 

  edumpfp = open(maildumpfile, 'w')
  edumpfp.write(ev['msg']['raw_msg'])
  edumpfp.close()

  mhcmd += ' ' + maildumpfile + ' ' + os.path.join(dstdir, 'op.html')
  if not  subprocess.call(mhcmd):
    return False
    
  processOpHtml(dstdir) 

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

