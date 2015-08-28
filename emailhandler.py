#! /usr/bin/python3.4

import argparse
import email
from email.header import decode_header
import email.utils
import json
import logging
import logging.handlers
import os
import pickle
import re
from redis import StrictRedis
from shutil import rmtree
import sys
import uuid


FILESIZE = 1024 * 1024 * 1024  # 1MB

instance = "0"

logger = logging.getLogger('mailHandler')
logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

# below regex objs are for handling new thread mails
taddrcomp = re.compile('([\w.-]+)@' + OUR_DOMAIN)

rclient = StrictRedis()


def returnHeader(title):
    imghead = '''
    <style>
    img { max-width: 100%; height: auto; }
    </style>
    '''
    response = """
<!DOCTYPE html>
<html lang="en">
%s
<head>
        <title>%s</title>
        <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.5/css/bootstrap.min.css" media="all" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://ajax.googleapis.com/ajax/libs/jquery/1.11.3/jquery.min.js"></script>
        <script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.5/js/bootstrap.min.js"></script>
</head>
<body>
    <div class="row">
        <div class="col-md-12">
    """ % (imghead, title)
    return response


def returnFooter():
    response = """
                    </div>
                <div class="col-md-8 col-md-offset-1 footer">
                <hr />
                <a href="http://redr.in/>Email Recodrer</a>
                </div>
               </div>
             </div>
           </body>
        </html>
    """
    return response


def decode_string(string):
    return string
    # for charset in ("utf-8", 'latin-1', 'iso-8859-1', 'us-ascii', 'windows-1252','us-ascii'):
    #    try:
    #        return cgi.escape(string).encode('ascii', 'xmlcharrefreplace')
    #    except Exception:
    #        continue
    # raise ValueError("Could not decode string")


def getdomain(a):
    return a.split('@')[-1]


def getuserid(a):
    return a.split('@')[0]


def isourdomain(a):
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


def emailHandler(ev, debug=False):
    toaddresses = ev['msg']['to']
    if len(toaddresses) != 1:
        return False

    to = toaddresses[0][0]

    logger.info("To Address {} -> {}".format(toaddresses, to))

    if not debug:
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

    else:
        folder = 'test'

    dstdir = os.path.join(FOLDER_ROOT_DIR, folder)

    logger.info("Destination folder : {} , url {}".format(dstdir, folder))
    try:
        os.mkdir(dstdir, 0o700)
    except FileExistsError:
        if debug:
            rmtree(dstdir, ignore_errors=True)
            os.mkdir(dstdir, 0o700)
        else:
            logger.info("Destination folder : {} exists".format(dstdir))
            return False

    rawmail = ev['msg']['raw_msg']

    mail = email.message_from_string(rawmail)
    if not mail:
        logger.info('Could not parse email')
        return False

    # TODO make use of tempfile
    maildumpfile = os.path.join(dstdir, 'email.dump')
    edumpfp = open(maildumpfile, 'w')
    edumpfp.write(rawmail)
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

    mail_date = decode_header(mail.get('Date'))[0][0]

    content_of_mail = {}
    content_of_mail['text'] = ""
    content_of_mail['html'] = ""
    content_of_mail['attachments'] = []
    content_of_mail['inline_attachments'] = []

    for part in mail.walk():
        part_content_type = part.get_content_type()
        if part_content_type == 'text/plain':
            part_decoded_contents = part.get_payload(decode=True)
            try:
                content_of_mail['text'] += str(part_decoded_contents)
            except Exception:
                try:
                    content_of_mail['text'] += str(part_decoded_contents)
                except ValueError:
                    content_of_mail['text'] += "Error decoding mail contents."
                    print("Error decoding mail contents")
            continue
        elif part_content_type == 'text/html':
            part_decoded_contents = part.get_payload(decode=True)
            content_of_mail['html'] += (part_decoded_contents).decode()
        else:
            inline_attachment = False
            if part.get_content_maintype() == 'multipart':
                continue
            content_disp = part.get('Content-Disposition')
            if content_disp == None:
                continue

            if 'inline' in content_disp:
                inline_attachment = True

            decoded_filename = part.get_filename()
            filename_header = None
            try:
                filename_header = decode_header(part.get_filename())
            except (UnicodeEncodeError, UnicodeDecodeError):
                filename_header = None

            if filename_header:
                filename_header = filename_header[0][0]
                att_filename = re.sub(
                    r'[^.a-zA-Z0-9 :;,\.\?]', "_", filename_header.replace(":", "").replace("/", "").replace("\\", ""))
            else:
                att_filename = re.sub(
                    r'[^.a-zA-Z0-9 :;,\.\?]', "_", decoded_filename.replace(":", "").replace("/", "").replace("\\", ""))

           # if last_att_filename == att_filename:
           #    att_filename = str(att_count) + "." + att_filename
           #
           # last_att_filename = att_filename
           # att_count += 1

            path = os.path.join(FOLDER_ROOT_DIR, folder)
            att_path = os.path.join(path, att_filename)

            with open(att_path, 'wb') as att_file:
                try:
                    att_file.write(part.get_payload(decode=True))
                except Exception as e:
                    att_file.write(
                        "Error writing attachment: " + str(e) + ".\n")
                    print("Error writing attachment: " + str(e) + ".\n")
                    return False
                att_file.close()

            if inline_attachment == True:
                cid = part.get('Content-Id')
                cid = cid.strip('<>')
                if debug:
                    content_of_mail['inline_attachments'].append(
                        (cid, att_path))
                else:
                    content_of_mail['inline_attachments'].append(
                        (cid, att_filename))
            else:
                if debug:
                    content_of_mail['attachments'].append(att_path)
                else:
                    content_of_mail['attachments'].append(att_filename)

    mail_html_page = os.path.join(dstdir, "index.html")
    with open(mail_html_page, 'w') as mail_page:
        mail_page.write(returnHeader(mail_subject))
        mail_page.write("<table>\n")
        mail_page.write("\t<tr>\n")
        mail_page.write("\t\t<td>From:&nbsp</td>\n")
        mail_page.write("\t\t<td>" + mail_from + "</td>\n")
        mail_page.write("\t</tr>\n")

       # mail_page.write("\t<tr>\n")
       # mail_page.write("\t\t<td>To: </td>\n")
       # mail_page.write("\t\t<td>" + mail_to + "</td>\n")
       # mail_page.write("\t</tr>\n")

        mail_page.write("\t<tr>\n")
        mail_page.write("\t\t<td>Subject:&nbsp</td>\n")
        mail_page.write("\t\t<td>" + mail_subject + "</td>\n")
        mail_page.write("\t</tr>\n")

        mail_page.write("\t<tr>\n")
        mail_page.write("\t\t<td>Date:&nbsp</td>\n")
        mail_page.write("\t\t<td>" + mail_date + "</td>\n")
        mail_page.write("\t</tr>\n")

        mail_page.write("</table>\n")

        if content_of_mail['html']:
            sh = content_of_mail['html']
            strip_header = re.sub(
                r"(?i)<html>.*?<head>.*?</head>.*?<body>", "", sh, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)</body>.*?</html>", "", strip_header, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)<!DOCTYPE.*?>", "", strip_header, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)POSITION: absolute;", "", strip_header, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)TOP: .*?;", "", strip_header, flags=re.DOTALL)

            if len(content_of_mail['inline_attachments']) > 0:
                for att_tuple in content_of_mail['inline_attachments']:
                    strip_header = re.sub(
                        '(<div.*<img.*src="([^"]+).*?</div>)', "", strip_header, re.DOTALL)
                    strip_header += '<br><div dir="ltr"><img src="{}"<br></div>'.format(
                        att_tuple[1])

            mail_page.write(strip_header)
        elif content_of_mail['text']:
            mail_page.write("<pre>")
            strip_header = re.sub(
                r"(?i)<html>.*?<head>.*?</head>.*?<body>", "", content_of_mail['text'], flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)</body>.*?</html>", "", strip_header, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)<!DOCTYPE.*?>", "", strip_header, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)POSITION: absolute;", "", strip_header, flags=re.DOTALL)
            strip_header = re.sub(
                r"(?i)TOP: .*?;", "", strip_header, flags=re.DOTALL)
            mail_page.write(str(strip_header))
            mail_page.write("</pre>\n")

        if len(content_of_mail['attachments']) > 0:
            mail_page.write("<br><h5>Attachments</h5>")
            mail_page.write("<table>\n")
            for att in content_of_mail['attachments']:
                mail_page.write("\t<tr>\n")
                if debug:
                    mail_page.write(
                        "\t\t<td><a href=" + '"' + att + '"' + ">" + att + "</a></td>\n")
                else:
                    mail_page.write(
                        "\t\t<td><a href=" + '"/' + folder + '/' + att + '"' + ">" + att + "</a></td>\n")
                mail_page.write("\t</tr>\n")
            mail_page.write("</table>\n")

        mail_page.write(returnFooter())

        mail_page.close()
    return True

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Redr-EmailHandler .')
    parser.add_argument(
        '-i', '--instance', help='Instance Num of this script ', required=True)
    parser.add_argument(
        '-d', '--debug', help='email dump file', required=False)
    args = parser.parse_args()
    argsdict = vars(args)
    instance = argsdict['instance']

    debugfile = ''
    if 'debug' in argsdict and argsdict['debug'] is not None:
        debugfile = argsdict['debug']
        print(debugfile)
        logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)

        with open(debugfile, 'r') as f:
            records = json.load(f)
            ev = records[0]
            f.close()
            emailHandler(ev, debug=True)
        exit()

    formatter = logging.Formatter(
        'REDR-MAILHANDLER-[' + instance + ']:%(asctime)s %(levelname)s - %(message)s')
    hdlr = logging.handlers.RotatingFileHandler(
        '/var/tmp/redrin_mailhandler_' + instance + '.log', maxBytes=FILESIZE, backupCount=10)
    hdlr.setFormatter(formatter)
    logger.addHandler(hdlr)
    logger.setLevel(logging.DEBUG)

    redrmailhandlerBackup = 'redrredrmailhandlerBackup_' + instance
    logger.info(
        "MailHandlerBackUp ListName : {} ".format(redrmailhandlerBackup))

    while True:
        backupmail = False
        if (rclient.llen(redrmailhandlerBackup)):
            logger.info("len of (" + redrmailhandlerBackup +
                        " ) is {} ".format(rclient.llen(redrmailhandlerBackup)))
            evt = rclient.brpop(redrmailhandlerBackup)
            backupmail = True
            ev = pickle.loads(evt[1])
            pickledEv = pickle.dumps(ev)
            logger.info("Getting events from {}".format(redrmailhandlerBackup))
        else:
            pickledEv = rclient.brpoplpush(
                'redrmailhandler', redrmailhandlerBackup)
            ev = pickle.loads(pickledEv)
            logger.info("Getting events from {}".format('redrmailhandler'))

        emailHandler(ev)

        if(not backupmail):
            logger.info('len of {} is : {}'.format(
                redrmailhandlerBackup, rclient.llen(redrmailhandlerBackup)))
            rclient.lrem(redrmailhandlerBackup, 0, pickledEv)
            logger.info('len of {} is : {}'.format(
                redrmailhandlerBackup, rclient.llen(redrmailhandlerBackup)))
