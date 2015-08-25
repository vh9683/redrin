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

#pandocCmd = '/usr/bin/pandoc '
pandocCmd = '/root/.cabal/bin/pandoc ' + ' '

html2wikiCmd = pandocCmd + '-r html {0}/html4.html -s -S -t mediawiki -o {0}/media.wiki'
wiki2html5Cmd = pandocCmd + '-f mediawiki -t html5 -s -S {0}/media.wiki -H ./template/header -B ./template/jumbo -A ./template/aferbody '
wiki2html5Cmd += ' --base-header-level=2  -T "redr.in - email for masses" -o {0}/intermediate.html'

mhBaseCmd = '/usr/bin/mhonarc -nothread -nomultipg -nomain -noprintxcomments -quiet -single -nomailto  -rcfile ./config/filters.mrc'

html2html5 = pandocCmd + ' -r html {0}/html4.html -t html5 -s -S  -H ./template/header -B ./template/jumbo -A ./template/aferbody  --base-header-level=3  -T "redr.in - email for masses" -o {0}/intermediate.html'

instance = "0"

logger = logging.getLogger('mailHandler')
logging.basicConfig(stream=sys.stdout,level=logging.DEBUG)

OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

#below regex objs are for handling new thread mails
taddrcomp = re.compile('([\w.-]+)@'+OUR_DOMAIN)

rclient = StrictRedis()

html5header = ''
with open('./template/header') as f:
    html5header = f.read()
    f.close()

jumbo = ''
with open('./template/jumbo') as f:
    jumbo = f.read()
    f.close()

adds = ''
with open('./template/aferbody') as f:
    adds = f.read()
    f.close()
 
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

def processMHOutPutHtml (dstdir):
  opfile = os.path.join(dstdir, 'op.html')
  html4file = os.path.join(dstdir, 'html4.html')
  
  ignored = ['<em>Authentication-results</em>' , '<em>Delivered-to</em>', '<em>Dkim-signature</em>', '<em>In-reply-to</em>', '<em>References</em>', '<!--', '<!DOCTYPE HTML PUBLIC', "http://www.w3.org/TR/html4/loose.dtd" , '<em>To</em>:']
  
  message = "<!DOCTYPE HTML>"
  opfp = open(opfile, 'r')
  for line in opfp:
    found = False
    for i in ignored:
      if i in line:
        found = True
        break

    if found == False:
      line1 = line.replace('<img src="">', '')
      message += line1.replace ('.//', '/')

  opfp.close()

  idfp = open(html4file, 'w')
  idfp.write(message)
  idfp.close()

  return True

def convertToHTML5 (dstdir):

# html2wikiCmd_copy = str(html2wikiCmd)
# html2wikiCmd_copy = html2wikiCmd_copy.format(dstdir)
# logger.info("Converting to html2wiki [{}]".format(html2wikiCmd_copy))

# try:
#   subprocess.call(html2wikiCmd_copy, shell=True)
# except:
#   logger.info("Converting to wiki failed\n")
#   raise

# wiki2html5Cmd_copy = str(wiki2html5Cmd)
# wiki2html5Cmd_copy = wiki2html5Cmd_copy.format(dstdir)

# logger.info("Converting to wiki2html5  [{}]".format(wiki2html5Cmd_copy))

# try:
#   subprocess.call(wiki2html5Cmd_copy, shell=True)
# except:
#   logger.info("Converting to html5 failed\n")
#   raise

# html5cmd = html5cmd.format(dstdir)
# print (html5cmd)
# try:
#   subprocess.call(html5cmd, shell=True)
# except:
#   logger.info("Converting to html5 failed\n")
#   raise

  html4file = os.path.join(dstdir, 'html4.html')

  message = ""
  html4fp = open(html4file, 'r')
  for line in html4fp:
      if '</head>' in line:
          message += html5header + '\n' + line
      elif '<body>' in line:
          message += '\n' + line + '\n' + jumbo
      elif '</body>' in line:
          message += adds
          message += '\n' + line
      else:
          message += line
  html4fp.close()

  #message = message.replace('<meta name="generator" content="pandoc">', '')
  message = message.replace('<h1>', '<h3>')
  message = message.replace('</h1>', '</h3>')
  indexfile = os.path.join(dstdir, 'index.html')
  idfp = open(indexfile, 'w')
  idfp.write(message)
  idfp.close()

  #TODO: Uncomment later
  #os.system( 'rm -f {0}/media.wiki {0}/op.html {0}/intermediate.html'.format(dstdir))

  return True


def emailHandler(ev, pickledEv):
  ''' 
    SPAM check is not done here ... it should have been handled in earlier stage of pipeline
  '''
  logger.info("TESTING \n")
  
  toaddresses = ev['msg']['to']
  if len(toaddresses) != 1:
    return False

  to = toaddresses[0][0]

  logger.info("To Address {} -> {}".format(toaddresses, to))

  if not taddrcomp.fullmatch(to):
    logger.info("To Address comparision failed \n")
    return False

  if not isourdomain(to):
    logger.info("Not Our Domain \n")
    return False
 
  token = getuserid(to)
  if not token:
    logger.info("getuserid failed\n")
    return False
  
  tdata = rclient.get(token)
  if not tdata:
    logger.info("No Data for token {}".format(token))
    return False
  
  tdata = pickle.loads(tdata)

  folder = tdata['folder']
  if folder is None:
    logger.info("No Folder {} Data for token {}".format(folder, token))
    return False
  
  if not valid_uuid4(folder):
    logger.info("Folder {} is not valid uuid \n".format(folder))
    return False
  
  mhcmd = 'cd ' + os.path.join(FOLDER_ROOT_DIR + folder) + '; '
  mhcmd += str(mhBaseCmd)

  mhcmd += ' -attachmenturl ' + '"' + '/'+folder +'"'

  mhcmd += ' -iconurlprefix ' + '"' + '/'+folder + '"'
 
  dstdir = os.path.join (FOLDER_ROOT_DIR, folder)
 
  logger.info("Destination folder : {} , url {}".format(dstdir, folder))
  try :
    os.mkdir(dstdir, 0o700)
  except FileExistsError:
    logger.info("Destination folder : {} exists".format(dstdir))
    return False

  #TODO make use of tempfile 
  maildumpfile = os.path.join(dstdir, 'email.dump') 

  edumpfp = open(maildumpfile, 'w')
  edumpfp.write(ev['msg']['raw_msg'])
  edumpfp.close()

  mhcmd += ' ' + maildumpfile + ' > ' + os.path.join(dstdir, 'op.html')
  #result = subprocess.call(mhcmd, shell=True)
  logger.info('command is {}'.format(mhcmd))
  try:
    #os.system(mhcmd)
    #subprocess.call(mhcmd)
    subprocess.call(mhcmd, shell=True)
  except:
    logger.info("SYSTEM CMD {}".format(mhcmd))
    raise
    
  logger.info("SYSTEM CMD {}".format(mhcmd))
  processMHOutPutHtml(dstdir) 

  convertToHTML5 (dstdir)


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
        logger.info("len of (" + redrmailhandlerBackup + " ) is {} ".format(rclient.llen(redrmailhandlerBackup)))
        evt = rclient.brpop (redrmailhandlerBackup)
        backupmail = True
        ev = pickle.loads(evt[1])
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

