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
from tornado.log import logging, gen_log
from tornado.httpclient import AsyncHTTPClient
from motor import MotorClient
from tornado.gen import coroutine
from redis import StrictRedis
from pathlib import Path
from random import Random

OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

if hasattr(os, 'TMP_MAX'):
    TMP_MAX = os.TMP_MAX
else:
    TMP_MAX = 10000

characters = "abcdefghijklmnopqrstuvwxyz"

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
    gen_log.info('rcvdsignature ' + str(rcvdsignature))
    gen_log.info('asignature ' + str(asignature))
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
    gen_log.info('rcvdsignature ' + str(rcvdsignature))
    gen_log.info('asignature ' + str(asignature))
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
    tdata = rclient.get(token)
    if tdata:
      tdata = pickle.loads(tdata)
    if not tdata or pin != tdata['pin']:
      if 'X-Real-IP' in self.request.headers:
        rclient.set(self.request.headers['X-Real-IP'],pickle.dumps('BadGuy'))
      self.render('sorry.html',reason='Invalid PIN')
      return
    self.redirect('/'+tdata['folder'])
    return

class ApiHandler(tornado.web.RequestHandler):
  def newtempname(self,ln=4):
    choose = Random().choice
    letters = [choose(characters) for dummy in range(ln)]
    return ''.join(letters)

  def newtoken(self):
    rclient = self.settings['rclient']
    for seq in range(TMP_MAX):
        name = self.newtempname()
        inuse = rclient.get(name)
        if not inuse:
            return name
        else:
            continue    # try again
    return None

  def gettoken(self):
    rclient = self.settings['rclient']
    token = rclient.lpop('tokenfreelist')
    if not token:
      return self.newtoken()
    return pickle.loads(token)

  @coroutine
  def getpin(self,reused,token):
    tkey = reused['tkey']
    for seq in range(TMP_MAX):
      usecount = reused['usecount'] + 1
      pin = oath.hotp(tkey,usecount)
      if not 'pins' in reused or pin not in reused['pins']:
        yield redrdb.tokens.update({'token': token},{'$set': {'usecount': usecount}, '$push': {'pins': pin}})
        return pin
    return None

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
    token = self.gettoken()
    if not token:
      self.write({'status': 500})
      self.finish()
      return
    reused = yield redrdb.tokens.find_one({'token': token})
    if not reused:
      usecount = 0
      tkey = uuid.uuid4().hex
      yield redrdb.tokens.insert({'token': token, 'usecount': usecount, 'tkey': tkey})
      reused = yield redrdb.tokens.find_one({'token': token})
    pin = yield self.getpin(reused,token)
    if not pin:
      self.write({'status': 500})
      self.finish()
      return
    rclient = self.settings['rclient']
    folder = uuid.uuid4().hex
    tdata = {'pin': pin, 'folder': folder}
    gen_log.info('tdata ' + str(tdata))
    rclient.setex(token,604800,pickle.dumps(tdata))
    rclient.setex(folder,604800,pickle.dumps(token))
    self.write({'status': 200, 'url': self.request.host + '/' + token, 'pin': pin})
    self.finish()
    return

class UrlHandler(tornado.web.RequestHandler):
  def get(self,folder):
    dir = Path(os.path.join(FOLDER_ROOT_DIR, folder)+'/index.html')
    if dir.exists():
      self.render(str(dir.resolve()))
    else:
      self.render('sorry.html',reason='Not Found')
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
    (r"/token", ApiHandler),
    (r"/mailer", RecvHandler),
    (r"/signup", SignupHandler),
    (r"/(.*)", tornado.web.StaticFileHandler,dict(path=settings['static_path'])),
], **settings)

if __name__ == "__main__":
    application.listen(8986)
    tornado.ioloop.IOLoop.current().start()
