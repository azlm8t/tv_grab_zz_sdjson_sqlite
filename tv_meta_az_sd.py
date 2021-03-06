#! /usr/bin/env python
# Retrieve details for a movie from Schedules Direct database.
# This program is in python (not perl) so it can integrate
# nicer with the Tvheadend metadata fetcher (tvhmeta).
#
# Usage:
# If using with Tvheadend (4.3+) then all you need to do
# is put this program in the same directory as the Tvheadend's
# file "tvhmeta", possibly /usr/bin or /usr/local/bin.
#
# There is no need to run the program manually since it is
# automatically called by Tvheadend.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os,sys
import json
import logging

def get_capabilities():
    return {
        "name": "tv_meta_az_sd",
        "version": "0.1",
        "description": "Grab movie details from SchedulesDirect database.",
        "supports_tv": True,
        "supports_movie": True,
    }


class Tv_meta_az_sd(object):
  def __init__(self, args):
      self.args = args
      self.database = None
      if 'database' in args: self.database = args["database"]
      if self.database is None:
        self.database = os.path.join(os.path.expanduser("~"), ".xmltv", "SchedulesDirect.DB")

  def _image_url(self, uri):
    if uri is None: return uri
    if not uri.startswith("http"): uri = 'https://json.schedulesdirect.org/20141201/image/' + uri
    return uri

  def _fetch_from_sd(self, programid):
    # For episodes, fan artwork is generally better on the show.
    # So we try the show first.
    if programid.startswith("EP"):
        showid = "SH" + programid[2:10] + "0000"
        logging.info("For episode %s trying show %s first" % (programid, showid))
        ret = self._fetch_from_sd(showid)
        if ret is not None:
            return ret

    import sqlite3
    import json
    if not os.path.exists (self.database) or os.path.getsize(self.database) == 0:
        msg = "Database file {} is not valid (running as incorrect user?)".format(self.database)
        logging.error(msg)
        raise RuntimeError(msg)
    logging.debug("Opening database %s" % self.database)
    conn = sqlite3.connect(self.database)
    c = conn.cursor()
    programid = programid.replace(".", "")
    logging.info("Searching for %s", programid)
    c.execute("select details from artwork where program = ? limit 1", (programid,))
    res = c.fetchone()
    if res is not None and res[0] is not None:
        res = res[0]
        logging.debug("Got result %s" % res)
        js = json.loads(res)
        logging.debug("JSON decode %s", js)
        # Two possibilities: errors are returned as a dict
        # {u'programID': u'EP00000000000', u'data': {u'message':....
        # success is returned as a list:
        # {u'programID': u'MV000000000000', u'data': [{u'category
        if js is not None and js["data"] and isinstance(js["data"], list):
            return js

    return None

  def _artwork_from_dict(self, art, required_aspect, required_tier = None):
    if art is None:
        return
    uri = None
    fallback_uri = None
    logging.debug(art["data"])
    logging.debug("Length=%s" % len(art["data"]))
    # Testing suggests that for long running shows, we should take the
    # _last_ item we find rather than the first. It appears artwork
    # is appended to the list by Schedules Direct. So, if we take the
    # first good match, then we get images showing people who are
    # no longer with the show. If we take the last image, then it
    # seems better.
    for required_size in ['Ms', 'Lg']:
      if uri:
          break
      logging.debug("Trying URLs with size %s and aspect %s" % (required_size, required_aspect))
      for details in reversed(art["data"]):
        # Each entry is similar to {u'category': u'Banner-L1', u'width': u'1920', u'size': u'Ms', u'aspect': u'16x9', u'tier': u'Series', u'text': u'yes', u'height': u'1080', u'uri': u'https://....', u'primary': u'true'}
        # With have an exception loop since some images are missing size.
        try:
            size = details["size"]
            if (size != required_size):
                continue
            text = details["text"]
            logging.debug("Trying %s" % details)
            logging.debug("URL %s %s %sx%s (%s/%s) text: %s"% (self._image_url(details["uri"]), details["category"], details["width"], details["height"], details["size"], details["aspect"], text)) # , details["caption"]))
            if required_tier is not None:
                # Movies do not have tiers so try/except.
                try:
                    tier = details["tier"]
                    if tier not in required_tier:
                        continue
                except:
                    pass
            category = details["category"]
            aspect = details["aspect"]
            if aspect in required_aspect:
                # We prefer good artwork
                if category == 'Poster Art' or category == 'Box Art' or category == 'VOD Art' or category == 'Staple' or category.startswith('Banner-L') or category == 'Logo':
                    uri = details["uri"]
                    break
                elif category == 'Iconic' or category == 'Cast Ensemble':
                    # Iconic (typically screenshot equivalents), and 'Cast
                    # Ensemble' for shows can be from an old series, do we
                    # carry on searching though for a better image.
                    # We prefer the first one we find.
                    if uri is None:
                        uri = details["uri"]
                    # And continue to find a better one
            elif fallback_uri is None and aspect == '3x4' and (
                category == 'Iconic' or
                category == 'Cast in Character'):  # This is a poor choice, but better than nothing
                fallback_uri = details["uri"]
                # Continue to try and find a better uri.
        except Exception as e:
            logging.debug("Got exception %s during loop" % e)

    logging.info("Finished loop with URLs uri: %s fallback_uri: %s req_aspect: %s req_tier: %s" %(self._image_url(uri), self._image_url(fallback_uri), required_aspect, required_tier))
    if uri is None: uri = fallback_uri
    if uri:
        return self._image_url(uri);
    else:
        return None

  def _artwork_from_dict_with_fallback(self, art, required_aspect, required_tier = None):
    """Try specific tier, fallback to any tier"""
    art = self._artwork_from_dict(art, required_aspect, required_tier)
    # No artwork in tier, so try any tier
    if art is None and required_tier is not None:
        logging.debug("Could not find any appropriate fanart at tier, trying any tier")
        art = self._artwork_from_dict(art, required_aspect)
    return art

  def fetch_details(self, args):
    logging.debug("Fetching with details %s " % args);
    programid = args["programid"]
    if programid is None:
        logging.critical("Need a programid");
        raise RuntimeError("Need a programid");

    # Tvheadend returns programid such as "ddprogid://xmltv/MV00000000.0000"
    # so need to just take the bit after the last slash. However, we want
    # to exclude "crid://" scheme (TVheadend OTA), and not specifically hard-code
    # the ddprogid:// schema, so we check programid is a recognized format
    sd_programid = programid.split('/')[-1]
    if programid.startswith("crid://") or (not sd_programid.startswith("EP") and not sd_programid.startswith("SH") and not sd_programid.startswith("MV") and not sd_programid.startswith("SP")):
        logging.error("We only handle SchedulesDirect programids not %s" % programid)
        raise RuntimeError("The programid format is not supported %s" % programid)

    res = self._fetch_from_sd(sd_programid)
    # Got a dict like {u'programID': u'MV000000000000', u'data': [{u'category
    # We prefer Series tier (instead of Season tier) since some programmes will have
    # season posters with text such as "Season 9", even though we might be season 12.
    # Whereas the Series tier is just a generic poster. So, prefer those.
    poster = self._artwork_from_dict_with_fallback(res, ['3x2', '2x3', '3x4'], required_tier = ['Series'])
    fanart = self._artwork_from_dict_with_fallback(res, ['16x9'], required_tier = ['Series'])
    logging.debug(fanart)

    logging.debug("URL poster=%s fanart=%s" % (poster, fanart))
    return {"poster": poster, "fanart": fanart}

if __name__ == '__main__':
  def process(argv):
    from optparse import OptionParser
    import os.path
    optp = OptionParser()
    optp.add_option('--database',
                    default=None,
                    help='Specify the SchedulesDirect xmltv database.')
    # Search by title/year is not currently supported,
    # only by programid
    #
    # optp.add_option('--title', default=None,
    #                 help='Title to search for.')
    # optp.add_option('--year', default=None, type="int",
    #                 help='Year to search for.')
    optp.add_option('--programid', default=None,
                    help='Program id to search for.')
    optp.add_option('--capabilities', default=None, action="store_true",
                    help='Display program capabilities (for PVR grabber)')
    optp.add_option('--debug', default=None, action="store_true",
                    help='Enable debug.')
    (opts, args) = optp.parse_args(argv)
    if (opts.debug):
        logging.root.setLevel(logging.DEBUG)

    grabber = Tv_meta_az_sd({"database" : opts.database})

    if opts.capabilities:
        # Output a program-parseable format. Might be useful for enumerating in PVR.
        print(json.dumps(get_capabilities()))
        return 0
    print(json.dumps(grabber.fetch_details({
        "programid": opts.programid
        })))

  try:
      logging.basicConfig(level=logging.INFO, format='%(asctime)s:%(levelname)s:%(module)s:%(message)s')
      sys.exit(process(sys.argv))
  except KeyboardInterrupt: pass
  except (RuntimeError,LookupError):
      sys.exit(1)
