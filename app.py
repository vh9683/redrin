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
import tempman
from tornado.log import logging, gen_log
from tornado.httpclient import AsyncHTTPClient
from motor import MotorClient
from tornado.gen import coroutine
from redis import StrictRedis
from pathlib import Path

OUR_DOMAIN = "redr.in"
FOLDER_ROOT_DIR = "/tmp/redr/"

class SignupHandler(tornado.web.RequestHandler):
  def authenticatepost(self):
    gen_log.info('authenticatepost for ' + self.request.path)
    authkey = self.settings['Mandrill_Auth_Key'][self.request.path].encode()
    if 'X-Mandrill-Signature' in self.request.headers:
      rcvdsignature = self.request.headers['X-Mandrill-Signature']
    else:
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
    if domain in baddomains:
      msg = {'template_name': 'redrfailure', 'email': from_email, 'global_merge_vars': [{'name': 'reason', 'content': "This Domain is not Supported."}]}
      count = rclient.publish('mailer',pickle.dumps(msg))
      gen_log.info('message ' + str(msg))
      gen_log.info('message published to ' + str(count))
      self.set_status(200)
      self.write({'status': 200})
      self.finish()
      return
    redrdb = self.settings['redrdb']
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
    badreq = rclient.get(self.request.headers['X-Real-IP'])
    if badreq:
      self.finish()
    return None

  @coroutine
  def get(self,token):
    folder = Path(FOLDER_ROOT_DIR+token)
    if folder.exists():
      self.render(token+'/index.html')
      return
    redrdb = self.settings['redrdb']
    valid = yield redrdb.tokens.find_one({'token': token})
    if valid:
      self.finish()
      return
    else:
      gen_log.info('invalid access from ' + self.request.headers['X-Real-IP'])
      rclient.setex(self.request.headers['X-Real-IP'],600,pickle.dumps('BadGuy'))
      self.finish()
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
      self.write({'status': 400})
      self.finish()
      return
    tokenfactory = self.settings['tokenfactory']
    token = tokenfactory.create_temp_dir().path
    reused = yield redrdb.tokens.find_one({'token': token})
    if not reused:
      yield redrdb.tokens.insert({'token': token})
    self.write({'status': 200, 'url': self.request.host + '/' + token})
    self.finish()
    return

logging.basicConfig(stream=sys.stdout,level=logging.DEBUG)

redrdb = MotorClient().redrdb

rclient = StrictRedis()

settings = {"static_path": FOLDER_ROOT_DIR,
            "template_path": FOLDER_ROOT_DIR,
            "redrdb": redrdb,
            "rclient": rclient,
            "Mandrill_Auth_Key": {"/recv": "27pZHL5IBNxJ_RS7PKdsMA",
                                  "/signup": "ZWNZCpFTJLg7UkJCpEUv9Q"},
}

application = tornado.web.Application([
    (r"/([a-z0-9_]{6})", TokenHandler),
    (r"/recv", RecvHandler),
    (r"/signup", SignupHandler),
    (r"/(.*)", tornado.web.StaticFileHandler,dict(path=settings['static_path'])),
], **settings)

if __name__ == "__main__":
    application.listen(8986)
    tornado.ioloop.IOLoop.current().start()