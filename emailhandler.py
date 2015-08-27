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
import email
import email.utils 
from email.utils import parseaddr
from redis import StrictRedis
from validate_email import validate_email
import argparse
import shutil
import subprocess

FILESIZE=1024*1024*1024 #1MB

instance = "0"

logger = logging.getLogger('mailHandler')
logging.basicConfig(stream=sys.stdout,level=logging.DEBUG)

OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

#below regex objs are for handling new thread mails
taddrcomp = re.compile('([\w.-]+)@'+OUR_DOMAIN)

rclient = StrictRedis()

def returnHeader(title):
    response = """
<!DOCTYPE html>
<html lang="en">
<head>
        <title>%s</title>
        <link rel="stylesheet" type="text/css" href="/css/bootstrap.css" media="all" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body>
    <div class="row">
        <div class="col-md-12">
    """ % (title)
    return response

def returnFooter():
    response = """
                    </div>
                <div class="col-md-8 col-md-offset-1 footer">
                <hr />
                <a href="http://redr.in/>Email Recodrer</a>
                </div>
            </body>
        </html>
    """
    return response

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

def save_mail_attachments_to_folders(mail, folder):

    returnTrue = False

    try:
        att_date = str(time.strftime("%Y/%m/", email.utils.parsedate(mail['Date'])))
    except TypeError:
        att_date = str("2000/1/")

    if not os.path.exists(os.path.join(folder, att_date, str(mail_id), "attachments/")):
        os.makedirs(os.path.join(folder, att_date, str(mail_id), "attachments/"))
    else:
        remove(os.path.join(folder, att_date, str(mail_id), "attachments/"))
        os.makedirs(os.path.join(folder, att_date, str(mail_id), "attachments/"))
 
    with open(os.path.join(folder, att_date, str(mail_id), "attachments/index.html"), "w") as att_index_file:
        att_index_file.write(returnHeader("Attachments for mail: " + str(mail_id) + ".", "../../../../inc"))
        att_index_file.write(returnMenu("../../../../../", activeItem=folder))
        att_index_file.write("<h1>Attachments for mail: " + str(mail_id) + "</h1>\n")
        att_index_file.write("<ul>\n")
        att_index_file.close()

    for part in mail.walk():
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get('Content-Disposition') == None:
            continue
        decoded_filename = part.get_filename()
        filename_header = None
        try:
            filename_header = decode_header(part.get_filename())
        except (UnicodeEncodeError, UnicodeDecodeError):
            filename_header = None

        if filename_header:
            filename_header = filename_header[0][0]
            att_filename = re.sub(r'[^.a-zA-Z0-9 :;,\.\?]', "_", filename_header.replace(":", "").replace("/", "").replace("\\", ""))
        else:
            att_filename = re.sub(r'[^.a-zA-Z0-9 :;,\.\?]', "_", decoded_filename.replace(":", "").replace("/", "").replace("\\", ""))

        if last_att_filename == att_filename:
            att_filename = str(att_count) + "." + att_filename
        
        last_att_filename = att_filename
        att_count += 1
            

        att_path = os.path.join(folder, att_date, str(mail_id), "attachments", att_filename)
        att_dir = os.path.join(folder, att_date, str(mail_id), "attachments")

        att_locs = []
        with open(att_path, 'wb') as att_file:
            try:
                att_file.write(part.get_payload(decode=True))
            except Exception as e:
                att_file.write("Error writing attachment: " + str(e) + ".\n")
                print("Error writing attachment: " + str(e) + ".\n")
                return False
            att_file.close()

        with open(att_dir + "/index.html", "a") as att_dir_index:
            att_dir_index.write("<li><a href=\"" + str(att_filename) + "\">" + str(att_filename) + "</a></li>\n")
            att_dir_index.close()
            returnTrue = True
    
    with open(os.path.join(folder, att_date, str(mail_id), "attachments/index.html"), "a") as att_index_file:
        att_index_file.write("</ul>")
        att_index_file.write(returnFooter())
        att_index_file.close()
        if returnTrue:
            return True
        else:
            return False          

def emailHandler(ev):
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
  
  dstdir = os.path.join (FOLDER_ROOT_DIR, folder)
 
  logger.info("Destination folder : {} , url {}".format(dstdir, folder))
  try :
    os.mkdir(dstdir, 0o700)
  except FileExistsError:
    logger.info("Destination folder : {} exists".format(dstdir))
    return False

  mail = email.message_from_string(ev['msg']['raw_msg'])
  if not mail:
    logger.info('Could not parse email')
    return False

  #TODO make use of tempfile 
  maildumpfile = os.path.join(dstdir, 'email.dump') 
  edumpfp = open(maildumpfile, 'w')
  edumpfp.write(mail)
  edumpfp.close()

  mail_subject = decode_header(mail.get('Subject'))[0][0]
  mail_subject_encoding = decode_header(mail.get('Subject'))[0][1]
  if not mail_subject_encoding:
    mail_subject_encoding = "utf-8"

  if not mail_subject:
    mail_subject = "(No Subject)"

  mail_from = email.utils.parseaddr(mail.get('From'))[1]

  mail_from_encoding = decode_header(mail.get('From'))[0][1]
  if not mail_from_encoding:
    mail_from_encoding = "utf-8"

  mail_to = email.utils.parseaddr(mail.get('To'))[1]
  mail_to_encoding = decode_header(mail.get('To'))[0][1]
  if not mail_to_encoding:
    mail_to_encoding = "utf-8"

  mail_date = decode_header(mail.get('Date'))[0][0]

  try:
      mail_subject = cgi.escape(unicode(mail_subject, mail_subject_encoding)).encode('ascii', 'xmlcharrefreplace')
      mail_to = cgi.escape(unicode(mail_to, mail_to_encoding)).encode('ascii', 'xmlcharrefreplace')
      mail_from = cgi.escape(unicode(mail_from, mail_from_encoding)).encode('ascii', 'xmlcharrefreplace')
      email_date = str(time.strftime("%d-%m-%Y %H:%m", email.utils.parsedate(mail_date)))
  except Exception:
      mail_subject = decode_string(mail_subject)
      mail_to = decode_string(mail_to)
      mail_from = decode_string(mail_from)
      email_date = "Error in Date"

  content_of_mail = {}
  content_of_mail['text'] = ""
  content_of_mail['html'] = ""
  content_of_mail['attachments'] = []

  for part in mail.walk():
      part_content_type = part.get_content_type()
      part_charset = part.get_charsets()
      if part_content_type == 'text/plain':
          part_decoded_contents = part.get_payload(decode=True)
          try:
              if part_charset[0]:
                  content_of_mail['text'] += cgi.escape(unicode(str(part_decoded_contents), part_charset[0])).encode('ascii', 'xmlcharrefreplace')
              else:
                  content_of_mail['text'] += cgi.escape(str(part_decoded_contents)).encode('ascii', 'xmlcharrefreplace')
          except Exception:
              try:
                  content_of_mail['text'] +=  decode_string(part_decoded_contents)
              except DecodeError:
                  content_of_mail['text'] += "Error decoding mail contents."
                  print("Error decoding mail contents")
          continue
      elif part_content_type == 'text/html':
          part_decoded_contents = part.get_payload(decode=True)
          try:
              if part_charset[0]:
                  content_of_mail['html'] += unicode(str(part_decoded_contents), part_charset[0]).encode('ascii', 'xmlcharrefreplace')
              else:
                  content_of_mail['html'] += str(part_decoded_contents).encode('ascii', 'xmlcharrefreplace')
          except Exception:
              try:
                  content_of_mail['html'] += decode_string(part_decoded_contents)
              except DecodeError:
                  content_of_mail['html'] += "Error decoding mail contents."
                  print("Error decoding mail contents")
          continue
      else:
        if part.get_content_maintype() == 'multipart':
            continue
        if part.get('Content-Disposition') == None:
            continue
        decoded_filename = part.get_filename()
        filename_header = None
        try:
            filename_header = decode_header(part.get_filename())
        except (UnicodeEncodeError, UnicodeDecodeError):
            filename_header = None

        if filename_header:
            filename_header = filename_header[0][0]
            att_filename = re.sub(r'[^.a-zA-Z0-9 :;,\.\?]', "_", filename_header.replace(":", "").replace("/", "").replace("\\", ""))
        else:
            att_filename = re.sub(r'[^.a-zA-Z0-9 :;,\.\?]', "_", decoded_filename.replace(":", "").replace("/", "").replace("\\", ""))

        if last_att_filename == att_filename:
            att_filename = str(att_count) + "." + att_filename
        
        last_att_filename = att_filename
        att_count += 1
            

        att_path = os.path.join(folder, att_filename)

        with open(att_path, 'wb') as att_file:
            try:
                att_file.write(part.get_payload(decode=True))
            except Exception as e:
                att_file.write("Error writing attachment: " + str(e) + ".\n")
                print("Error writing attachment: " + str(e) + ".\n")
                return False
            att_file.close()
        
        content_of_mail['attachments'].append(att_filename)

  mail_html_page = os.path.join(dstdir, "index.html")
  with open(mail_html_page, 'w') as mail_page:
      mail_page.write(returnHeader(mail_subject))
      mail_page.write("<table>\n")
      mail_page.write("\t<tr>\n")
      mail_page.write("\t\t<td>From: </td>\n")
      mail_page.write("\t\t<td>" + mail_from + "</td>\n")
      mail_page.write("\t</tr>\n")

      mail_page.write("\t<tr>\n")
      mail_page.write("\t\t<td>To: </td>\n")
      mail_page.write("\t\t<td>" + mail_to + "</td>\n")
      mail_page.write("\t</tr>\n")

      mail_page.write("\t<tr>\n")
      mail_page.write("\t\t<td>Subject: </td>\n")
      mail_page.write("\t\t<td>" + mail_subject + "</td>\n")
      mail_page.write("\t</tr>\n")

      mail_page.write("\t<tr>\n")
      mail_page.write("\t\t<td>Date: </td>\n")
      mail_page.write("\t\t<td>" + mail_date + "</td>\n")
      mail_page.write("\t</tr>\n")

      mail_page.write("</table>\n")

      if content_of_mail['html']:
          strip_header = re.sub(r"(?i)<html>.*?<head>.*?</head>.*?<body>", "", content_of_mail['html'], flags=re.DOTALL)
          strip_header = re.sub(r"(?i)</body>.*?</html>", "", strip_header, flags=re.DOTALL)
          strip_header = re.sub(r"(?i)<!DOCTYPE.*?>", "", strip_header, flags=re.DOTALL)
          strip_header = re.sub(r"(?i)POSITION: absolute;", "", strip_header, flags=re.DOTALL)
          strip_header = re.sub(r"(?i)TOP: .*?;", "", strip_header, flags=re.DOTALL)
          mail_page.write(decodestring(strip_header))
      elif content_of_mail['text']:
          mail_page.write("<pre>")
          strip_header = re.sub(r"(?i)<html>.*?<head>.*?</head>.*?<body>", "", content_of_mail['text'], flags=re.DOTALL)
          strip_header = re.sub(r"(?i)</body>.*?</html>", "", strip_header, flags=re.DOTALL)
          strip_header = re.sub(r"(?i)<!DOCTYPE.*?>", "", strip_header, flags=re.DOTALL)
          strip_header = re.sub(r"(?i)POSITION: absolute;", "", strip_header, flags=re.DOTALL)
          strip_header = re.sub(r"(?i)TOP: .*?;", "", strip_header, flags=re.DOTALL)
          mail_page.write(decodestring(strip_header))
          mail_page.write("</pre>\n")

      if len(content_of_mail['attachments']) > 0:
        mail_page.write("<h5>Attachments<\h5>\n")
        mail_page.write("<table>\n")
        for att in content_of_mail['attachments']:
          mail_page.write("\t<tr>\n")
          mail_page.write("\t\t<td><a href=" + '"/' + folder + '/' + att + '"' + ">" + att + "</a></td>\n")
          mail_page.write("\t</tr>\n")
        mail_page.write("</table>\n")
     
      mail_page.write(returnFooter())

      mail_page.close()        
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

    emailHandler(ev)

    if(not backupmail):
      logger.info ('len of {} is : {}'.format(redrmailhandlerBackup, rclient.llen(redrmailhandlerBackup)))
      rclient.lrem(redrmailhandlerBackup, 0, pickledEv)
      logger.info ('len of {} is : {}'.format(redrmailhandlerBackup, rclient.llen(redrmailhandlerBackup)))

