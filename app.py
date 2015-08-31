import tornado.ioloop
import tornado.web
import json
import sys
import uuid
import pickle
import hashlib
import hmac
import base64
import datetime
import os
import oath
import email
import smtplib
from tornado.log import logging,gen_log
from tornado.httpclient import AsyncHTTPClient
from motor import MotorClient
from tornado.gen import coroutine
from redis import StrictRedis
from pathlib import Path
from random import Random,randint
from shutil import rmtree
from validate_email import validate_email


OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

class SignupHandler(tornado.web.RequestHandler):
    def authenticatepost(self):
        gen_log.info('authenticatepost for ' + self.request.path)
        authkey = self.settings['Mandrill_Auth_Key'][self.request.path].encode()
        if 'X-Mandrill-Signature' in self.request.headers:
            rcvdsignature = self.request.headers['X-Mandrill-Signature']
        else:
            if 'X-Real-IP' in self.request.headers:
                gen_log.info('Invalid post from ' + self.request.headers['X-Real-IP'])
                return False
            data = self.request.full_url()
            argkeys = sorted(self.request.arguments.keys())
            for arg in argkeys:
                data += arg
            for args in self.request.arguments[arg]:
                data += args.decode()
            hashed = hmac.new(authkey,data.encode(),hashlib.sha1)
            asignature = base64.b64encode(hashed.digest()).decode()
        return asignature == rcvdsignature

    def write_error(self,status_code,**kwargs):
        self.set_status(200)
        self.write({'status': 200})
        self.finish()
        return
  
    def getdomain(self,a):
        return a.split('@')[-1]
  
    @coroutine
    def post(self):
        if self.authenticatepost():
            gen_log.info('post authenticated successfully')
        else:
            if 'X-Real-IP' in self.request.headers:
                gen_log.info('post authentication failed, remote ip ' + self.request.headers['X-Real-IP'])
            self.set_status(400)
            self.write('Bad Request')
            self.finish()
            return
        ev = self.get_argument('mandrill_events',False)
        if not ev:
            self.set_status(200)
            self.write({'status': 200})
            self.finish()
            return
            ev = json.loads(ev, "utf-8")
            ev = ev[0]
            from_email = ev['msg']['from_email']
            domain = self.getdomain(from_email)
            redrdb = self.settings['redrdb']
            baddomains = redrdb.baddomains.find({'domain': domain})
            if baddomains:
                msg = {'template_name': 'redrfailure', 'email': from_email, 'global_merge_vars': [{'name': 'reason', 'content': "This Domain is not Supported."}]}
                count = rclient.publish('mailer',pickle.dumps(msg))
                gen_log.info('message ' + str(msg))
                gen_log.info('message published to ' + str(count))
                self.set_status(200)
                self.write({'status': 200})
                self.finish()
                return
            user = yield redrdb.clients.find_one({'domain': domain})
            if not user:
                apikey = uuid.uuid4().hex
                yield redrdb.clients.insert({'domain': domain, 'apikey': apikey})
            else:
                apikey = user['apikey']
                msg = {'template_name': 'redrsignup', 'email': from_email, 'global_merge_vars': [{'name': 'key', 'content': apikey}]}
                count = rclient.publish('mailer',pickle.dumps(msg))
                gen_log.info('message ' + str(msg))
                gen_log.info('message published to ' + str(count))
                self.set_status(200)
                self.write({'status': 200})
                self.finish()
                return    

class RecvHandler(tornado.web.RequestHandler):
    def authenticatepost(self):
        gen_log.info('authenticatepost for ' + self.request.path)
        authkey = self.settings['Mandrill_Auth_Key'][self.request.path].encode()
        if 'X-Mandrill-Signature' in self.request.headers:
            rcvdsignature = self.request.headers['X-Mandrill-Signature']
        else:
            if 'X-Real-IP' in self.request.headers:
                gen_log.info('Invalid post from ' + self.request.headers['X-Real-IP'])
            return False
        data = self.request.full_url()
        argkeys = sorted(self.request.arguments.keys())
        for arg in argkeys:
            data += arg
            for args in self.request.arguments[arg]:
                data += args.decode()
                hashed = hmac.new(authkey,data.encode(),hashlib.sha1)
                asignature = base64.b64encode(hashed.digest()).decode()
        return asignature == rcvdsignature

    def write_error(self,status_code,**kwargs):
        self.set_status(200)
        self.write({'status': 200})
        self.finish()
        return
  
    def post(self):
        if self.authenticatepost():
            gen_log.info('post authenticated successfully')
        else:
            if 'X-Real-IP' in self.request.headers:
                gen_log.info('post authentication failed, remote ip ' + self.request.headers['X-Real-IP'])
            self.set_status(400)
            self.write('Bad Request')
            self.finish()
            return
        ignored = ['signup@redr.in', 'noreply@redr.in']
        ev = self.get_argument('mandrill_events',False)
        if not ev:
            self.set_status(200)
            self.write({'status': 200})
            self.finish()
            return
        else:
            ev = json.loads(ev, "utf-8")
            ev = ev[0]

            for to,toname in ev['msg']['to']:
                if to in ignored:
                    self.set_status(200)
                    self.write({'status': 200})
                    self.finish()
                    return
     
            ''' stage 1 do mail archive for all mails '''
            rclient = self.settings['rclient']
            ''' Push the entire json to redrmailhandler thread through redis list'''
            pickledEv = pickle.dumps(ev)
            rclient.lpush('redrmailhandler', pickledEv)

            self.set_status(200)
            self.write({'status': 200})
            self.finish()
            return

    def head(self):
        gen_log.info('recv head hit!')
        self.set_status(200)
        self.write({'status': 200})
        self.finish()
        return
 
class TokenHandler(tornado.web.RequestHandler):
    def prepare(self):
        rclient = self.settings['rclient']
        if 'X-Real-IP' in self.request.headers:
            badreq = rclient.get(self.request.headers['X-Real-IP'])
            if badreq:
                self.finish()
                return None

    def get(self,token):
        gen_log.info("URI : {}".format(token))
        self.render('verify.html',url=self.request.uri)

    @coroutine
    def post(self,token):
        pin = self.get_argument('pin',None)
        rclient = self.settings['rclient']
        if not pin:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        redrdb = self.settings['redrdb']
        tdata = yield redrdb.tokens.find_one({'token': token})
        if not tdata:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        pdata = yield redrdb.pins.find_one({"pin": pin})
        if not pdata:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        folder = base64.b32encode((token+pin).encode()).decode()
        rclient.setex(folder,300,pickle.dumps(token+pin))
        self.redirect('/'+folder)
        return

class ApiHandler(tornado.web.RequestHandler):
    @coroutine
    def get(self):
        apikey = self.get_argument('apikey',False)
        if not apikey:
            self.write({'status': 400})
            self.finish()
            return
        redrdb = self.settings['redrdb']
        client = yield redrdb.clients.find_one({'apikey': apikey})
        if not client:
            self.write({'status': 401})
            self.finish()
            return
        rclient = self.settings['rclient']
        lasttid = rclient.get('lasttokenid')
        if not lasttid:
            lasttid = 0
        else:
            lasttid = pickle.loads(lasttid)
        rclient.set('lasttokenid',pickle.dumps((lasttid+1)%(26**4)))
        gen_log.info('get token with id ' + str(lasttid))
        token = yield redrdb.tokens.find_one({'tokenid': lasttid})
        if not token:
            gen_log.info('failed to token with id ' + str(lasttid))
            self.write({'status': 500})
            self.finish()
            return
        yield redrdb.tokens.update({'tokenid': lasttid},{'$set': {'usecount': ((token['usecount']+1)%(10**6))}})
        pin = yield redrdb.pins.find_one({'pinid': token['usecount']})
        if not pin:
            gen_log.info('failed to get pin with id ' + str(token['usecount']))
            self.write({'status': 500})
            self.finish()
            return
        
        folder = base64.b32encode((token['token']+pin['pin']).encode()).decode()
        self.write({'status': 200, 'url': self.request.host + '/' + token['token'], 'pin': pin['pin'], 'userid': folder})
        self.finish()
        return

class UrlHandler(tornado.web.RequestHandler):
    def prepare(self):
        rclient = self.settings['rclient']
        if 'X-Real-IP' in self.request.headers:
            badreq = rclient.get(self.request.headers['X-Real-IP'])
            if badreq:
                self.finish()
                return None

    @coroutine
    def get(self,folder):
        rclient = self.settings['rclient']
        fdata = rclient.get(folder)
        if not fdata:
            tpin = base64.b32decode(folder.encode()).decode()
            redrdb = self.settings['redrdb']
            link = yield redrdb.tokens.find_one({'token': tpin[:4]})
            if link:
                self.redirect('/'+link['token'])
            else:
                if 'X-Real-IP' in self.request.headers:
                    rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
                self.set_status(403)
                self.write('Forbidden')
                self.finish()                
            return
        folpath = os.path.join(FOLDER_ROOT_DIR, folder)
        if not os.path.isdir(folpath):
            gen_log.info("sorry.html")
            self.render('sorry.html',reason='Not Found')
            return
   
        directory = Path(folpath + '/index.html')
        if directory.exists():
            self.render(str(directory.resolve()))
        else:
            self.render('sorry.html',reason='Not Found')
        return

class AttachmentHandler(tornado.web.RequestHandler):
    def prepare(self):
        rclient = self.settings['rclient']
        if 'X-Real-IP' in self.request.headers:
            badreq = rclient.get(self.request.headers['X-Real-IP'])
            if badreq:
                self.finish()
                return None

    @coroutine
    def get(self,folder,filename):
        rclient = self.settings['rclient']
        fdata = rclient.get(folder)
        if not fdata:
            tpin = base64.b32decode(folder.encode()).decode()
            redrdb = self.settings['redrdb']
            link = yield redrdb.tokens.find_one({'token': tpin[:4]})
            if link:
                self.redirect('/'+link['token'])
            else:
                if 'X-Real-IP' in self.request.headers:
                    rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
                self.set_status(403)
                self.write('Forbidden')
                self.finish()                
            return
        if not filename:
            gen_log.info("sorry.html")
            self.render('sorry.html',reason='Not Found')
            return
        folpath = os.path.join(FOLDER_ROOT_DIR, folder)
        if not os.path.isdir(folpath):
            gen_log.info("sorry.html")
            self.render('sorry.html',reason='Not Found')
            return
   
        directory = Path(folpath + filename)
        if directory.exists():
            self.write(str(directory.resolve()))
        else:
            self.render('sorry.html',reason='Not Found')
        return

class DeleteMailHandler(tornado.web.RequestHandler):
    def prepare(self):
        rclient = self.settings['rclient']
        if 'X-Real-IP' in self.request.headers:
            badreq = rclient.get(self.request.headers['X-Real-IP'])
            if badreq:
                self.finish()
                return None

    @coroutine
    def get(self,token):
        redrdb = self.settings['redrdb']
        tdata = yield redrdb.tokens.find_one({'token': token})
        if not tdata:
          self.render('sorry.html',reason='Invalid Token, Cannot Delete')
          return
        else:
          self.render('verify.html',url=self.request.uri)

    @coroutine
    def post(self,token):
        pin = self.get_argument('pin',None)
        rclient = self.settings['rclient']
        if not pin:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        redrdb = self.settings['redrdb']
        tdata = yield redrdb.tokens.find_one({'token': token})
        if not tdata:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        pdata = yield redrdb.pins.find_one({'pin': pin})
        if not pdata:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        folder = base64.b32encode((tdata['token']+pdata['pin']).encode()).decode()
        rclient.delete(folder)
        rmtree(FOLDER_ROOT_DIR+folder,ignore_errors=True)   
        self.render('success.html', reason='Successfully Deleted mail')
        return


class ForwardMailHandler(tornado.web.RequestHandler):
    def prepare(self):
        rclient = self.settings['rclient']
        if 'X-Real-IP' in self.request.headers:
            badreq = rclient.get(self.request.headers['X-Real-IP'])
            if badreq:
                self.finish()
                return None

    @coroutine
    def get(self,token):
        self.render('fwdmail.html',url=self.request.uri)

    @coroutine
    def post(self,token):
        rcptemail = self.get_argument('email',None)
        pin = self.get_argument('pin',None)

        if rcptemail is None or not validate_email(rcptemail):
            self.render('sorry.html',reason='Invalid Email Id Cannot Forward Email To {}'.format(rcptemail))
            return
        
        if not pin:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return

        redrdb = self.settings['redrdb']
        tdata = yield redrdb.tokens.find_one({'token': token})
        if not tdata:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return
        pdata = yield redrdb.pins.find_one({'pin': pin})
        if not pdata:
            if 'X-Real-IP' in self.request.headers:
                rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
            self.render('sorry.html',reason='Invalid PIN')
            return

        rclient = self.settings['rclient']
        folder = base64.b32encode((token+pin).encode()).decode()
        fdata = rclient.get(folder)
        if not fdata:
            self.redirect('/'+token)
            return
        # Fwd mailto mail address
        emailfilepath = os.path.join(FOLDER_ROOT_DIR,  tdata['folder'])

        emailfilepath = os.path.join(emailfilepath, 'email.dump')

        gen_log.info("Emailfile :{}".format(emailfilepath))

        mailstring = ""
        with open(emailfilepath, 'r') as fp:
          mailstring = fp.read()
          fp.close()

        mail = email.message_from_string(mailstring)

        server = smtplib.SMTP('smtp.mandrillapp.com', 587)
        try:
          server.ehlo()

          # If we can encrypt this session, do it
          if server.has_extn('STARTTLS'):
            server.starttls()
            server.ehlo() # re-identify ourselves over TLS connection
            server.login('vidyartibng@gmail.com', 'c3JOgoZZ9BmKN4swnnBEpQ')

          gen_log.info('Fwd EmailId : {}'.format(rcptemail))

          composed = mail.as_string()

          sub = mail.get('Subject')
          if not sub:
            sub = "Email Forwarded from Redr.in"  
          else:
            del mail['Subject']
            sub = "Fwd: " + sub
            mail['Subject'] = sub

          mail_from = email.utils.parseaddr(mail.get('From'))[1]

          server.sendmail(mail_from, rcptemail, composed)
          ## Should we Capture this mail if for data analysis
          ## add for readdress.io
        finally:
          server.quit()

        self.render('success.html', reason='Successfully Forwarded mail')
        return



class MainHandler(tornado.web.RequestHandler):
    def get(self):
        self.render("index.html")

logging.basicConfig(stream=sys.stdout,level=logging.DEBUG)

redrdb = MotorClient().redrdb

rclient = StrictRedis()

settings = {"static_path": FOLDER_ROOT_DIR,
            "template_path": os.path.join(FOLDER_ROOT_DIR, 'html'),
            "redrdb": redrdb,
            "rclient": rclient,
            "Mandrill_Auth_Key": {"/mailer": "ruL49F78tETKF8bsFEFT0A",
                                  "/signup": "40qQ1GnCxDZ4AEQ2_pul0Q"},
}

application = tornado.web.Application([
    (r"/", MainHandler),
    (r"/([a-z]{4})", TokenHandler),
    (r"/([a-f0-9]{32})", UrlHandler),
    (r"/([a-f0-9]{32})/(.*)", AttachmentHandler),
    (r"/token", ApiHandler),
    (r"/mailer", RecvHandler),
    (r"/signup", SignupHandler),
    (r"/forwardmail/(.*)", ForwardMailHandler),
    (r"/delete/([a-z]{4})", DeleteMailHandler),
    (r"/(.*)", tornado.web.StaticFileHandler,dict(path=settings['static_path'])),
], **settings)

if __name__ == "__main__":
    application.listen(8986)
    tornado.ioloop.IOLoop.current().start()
