import base64
import hashlib
import logging
import os
import re
from html import entities as htmlentitydefs

import cherrypy
import requests
from jwkest import as_bytes

logger = logging.getLogger(__name__)


def handle_error():
    cherrypy.response.status = 500
    cherrypy.response.body = [
        b"<html><body>Sorry, an error occured</body></html>"
    ]


def get_symkey(link):
    md5 = hashlib.md5()
    md5.update(link.encode("utf-8"))
    return base64.b16encode(md5.digest()).decode("utf-8")


# this pattern matches substrings of reserved and non-ASCII characters
pattern = re.compile(r"[&<>\"\x80-\xff]+")

# create character map
entity_map = {}

for i in range(256):
    entity_map[chr(i)] = "&#%d;" % i

for entity, char in htmlentitydefs.entitydefs.items():
    if char in entity_map:
        entity_map[char] = "&%s;" % entity


def escape_entity(m, get=entity_map.get):
    return "".join(map(get, m.group()))


def escape(string):
    return pattern.sub(escape_entity, string)


def create_result_page(userinfo, access_token, client):
    """
    Display information from the Authentication.
    """
    element = ["<h2>You have successfully logged in!</h2>",
               "<dl><dt>Accesstoken</dt><dd>{}</dd>".format(access_token),
               "<h3>Endpoints</h3>"]

    try:
        text = str(client.authorization_endpoint)
        element.append(
            "<dt>Authorization endpoint</dt><dd>{}</dd>".format(text))
    except:
        pass
    try:
        text = str(client.registration_endpoint)
        element.append("<dt>Registration endpoint</dt><dd>{}</dd>".format(text))
    except:
        pass
    try:
        text = str(client.token_endpoint)
        element.append("<dt>Token endpoint</dt><dd>{}</dd>".format(text))
    except:
        pass
    try:
        text = str(client.userinfo_endpoint)
        element.append("<dt>User info endpoint</dt><dd>{}</dd>".format(text))
    except:
        pass
    element.append('</dl>')
    element.append('<h3>User information</h3>')
    element.append('<dl>')
    for key, value in userinfo.items():
        element.append("<dt>" + escape(str(key)) + "</dt>")
        element.append("<dd>" + escape(str(value)) + "</dd>")
    element.append('</dl>')

    return "\n".join(element)


class Root(object):
    @cherrypy.expose
    def index(self):
        response = [
            '<html><head>',
            '<title>My OpenID Connect RP</title>',
            '<link rel="stylesheet" type="text/css" href="/static/theme.css">'
            '</head><body>'
            "<h1>Welcome to my OpenID Connect RP</h1>",
            '</body></html>'
        ]
        return '\n'.join(response)


class Consumer(Root):
    _cp_config = {'request.error_response': handle_error}

    def __init__(self, rph, html_home='.', static_dir='static'):
        self.rph = rph
        self.html_home = html_home
        self.static_dir = static_dir

    @cherrypy.expose
    def index(self, uid='', iss=''):
        link = ''
        if iss:
            link = iss
        elif uid:
            try:
                link = self.rph.find_srv_discovery_url(
                    resource="acct:{}".format(uid))
            except requests.ConnectionError:
                raise cherrypy.HTTPError(
                    message="Webfinger lookup failed, connection error")
            else:
                logger.info('Issuer ID: {}'.format(link))
        else:
            fname = os.path.join(self.html_home, 'opbyuid.html')
            return as_bytes(open(fname, 'r').read())

        if link:
            try:
                _url = self.rph.begin(link)
            except Exception as err:
                raise cherrypy.HTTPError(err)
            else:
                raise cherrypy.HTTPRedirect(_url)

    @cherrypy.expose
    def acb(self, op_hash='', **kwargs):
        try:
            rp = self.rph.issuer2rp[self.rph.hash2issuer[op_hash]]
        except KeyError:
            raise cherrypy.HTTPError(400,
                                     "Response to something I hadn't asked for")

        x = rp.client_info.state_db[kwargs['state']]

        res = self.rph.phaseN(x['as'], kwargs)

        if res[0] is True:
            fname = os.path.join(self.html_home, 'opresult.html')
            _pre_html = open(fname, 'r').read()
            _html = _pre_html.format(result=create_result_page(*res[1:]))
            return as_bytes(_html)
        else:
            raise cherrypy.HTTPError(400, res[1])

    def _cp_dispatch(self, vpath):
        # Only get here if vpath != None
        ent = cherrypy.request.remote.ip
        logger.info('ent:{}, vpath: {}'.format(ent, vpath))

        if vpath[0] in self.static_dir:
            return self
        elif len(vpath) == 2:
            a = vpath.pop(0)
            b = vpath.pop(0)
            if a == 'rp':
                cherrypy.request.params['uid'] = b
                return self
            elif a == 'authz_cb':
                cherrypy.request.params['op_hash'] = b
                return self.acb
            elif a == 'authz_im_cb':
                cherrypy.request.params['op_hash'] = b
                return self.ihcb

        return self

    @cherrypy.expose
    def ihcb(self, **kwargs):
        """ Implicit and hybrid callback """
        return self._load_HTML_page_from_file("html/repost_fragment.html",
                                              op_hash=kwargs['op_hash'])

    def _load_HTML_page_from_file(self, path, **kwargs):
        if not path.startswith("/"): # relative path
            # prepend the root package dir
            path = os.path.join(os.path.dirname(__file__), path)

        with open(path, "r") as f:
            txt = f.read()
            txt = txt % kwargs['op_hash']
            return txt

    @cherrypy.expose
    def repost_fragment(self, **kwargs):
        try:
            rp = self.rph.issuer2rp[self.rph.hash2issuer[kwargs['op_hash']]]
        except KeyError:
            raise cherrypy.HTTPError(400,
                                     "Response to something I hadn't asked for")

        res = self.rph.phaseN(rp, kwargs['url_fragment'])

        if res[0] is True:
            fname = os.path.join(self.html_home, 'opresult.html')
            _pre_html = open(fname, 'r').read()
            _html = _pre_html.format(result=create_result_page(*res[1:]))
            return as_bytes(_html)
        else:
            raise cherrypy.HTTPError(400, res[1])
