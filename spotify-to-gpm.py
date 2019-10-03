#!/bin/env python
# -*- coding: utf-8 -*-

import sys
import demjson
import re
from gmusicapi import Mobileclient
import logging
import argparse
import requests


def set_logging_handler(log_level=logging.INFO):
    if log_level == logging.INFO:
        LOG = logging.getLogger(__name__)
    # If you want to DEBUG, you might as well get the DEBUG logs from all modules
    if log_level == logging.DEBUG:
        LOG = logging.getLogger()
    LOG.setLevel(log_level)
    OUT_HANDLER = logging.StreamHandler(sys.stdout)
    OUT_HANDLER.setFormatter(logging.Formatter("%(asctime)s - [%(levelname)s] %(message)s"))
    LOG.addHandler(OUT_HANDLER)

"""
Spotify helper functions
"""
def get_longest_script_seq(html_str):
    LOG.debug("Finding longest <script>...</script> sequence in Spotify HTML")
    matches = re.findall(r'<script>(.*?)<\/script>', html_str, re.MULTILINE | re.DOTALL)
    longest_match = max(matches, key=len)
    return longest_match

def get_dict_from_script_seq(script_tag_contents):
    LOG.debug("Getting the relevant dictionary from the script sequence")
    longest_line = ""
    for i in script_tag_contents.split('\n'):
        if len(i) > len(longest_line):
            longest_line = i
    longest_line = longest_line.split(' = ')
    longest_line = ' = '.join(longest_line[1:])
    # Remove the trailing semicolon
    return longest_line[:-1]

"""
GPM helper functions
"""
def gmusic_login(g_user, g_pass):
    api = Mobileclient()
    logged_in = api.login(g_user, g_pass, Mobileclient.FROM_MAC_ADDRESS)
    if not logged_in:
        LOG.error("Unable to log in to Google Play Music. Exiting...")
        sys.exit(1)
    else:
        LOG.info("Logged into Google Play Music")
        return api

def gmusic_search(api_obj, search_str):
    full_ret = dict(api_obj.search(search_str, max_results=1))
    try:
        first_song_hit = full_ret['song_hits'][0]
        return first_song_hit['track']['storeId']
    except IndexError as err:
        LOG.warn("Could not find any song hits for search string: {}".format(search_str))

def gmusic_create_new_playlist(api_obj, playlist_name, spotify_external_url=None, spotify_description=None):
    new_playlist_description = "Auto-generated by {}.".format(__name__)
    if spotify_external_url:
        new_playlist_description += "\nOriginal Spotify URL: {}".format(spotify_external_url)
    if spotify_description:
        new_playlist_description += "\nOriginal Spotify description: {}".format(spotify_description)
    playlist_id = api_obj.create_playlist(playlist_name, description=new_playlist_description)
    return playlist_id

def gmusic_add_to_playlist(api_obj, playlist_id, song_id):
    api_obj.add_songs_to_playlist(playlist_id, song_id)
    return True



def main(spotify_type, spotify_source, g_user=None, g_pass=None, new_playlist_name=None, only_spotify=False):
    if spotify_type:
        with open(spotify_source, 'r') as fd:
            spotify_raw = fd.read()
    elif not spotify_type:
        ret = requests.get(spotify_source)
        spotify_raw = ret.text
    else:
        LOG.error("Spotify URL or HTML file required but none was given")
        sys.exit(1)

    script_seq = get_longest_script_seq(spotify_raw)
    dict_seq = get_dict_from_script_seq(script_seq)
    raw = demjson.decode(dict_seq)

    spotify_playlist = list()
    for item in raw['tracks']['items']:
        track_name = item['track']['name']
        album_name = item['track']['album']['name']
        artists = list()
        for artist in item['track']['artists']:
            artists.append(artist['name'])

        spotify_playlist.append((track_name, ', '.join(artists), album_name))

    # Get some Spotify metadata for posterity
    metadata = list()
    metadata.append(raw['description'])
    metadata.append(raw['external_urls']['spotify'])

    # Python verison < 3 requires explicit utf-8 encoding
    if sys.version_info[0] < 3:
        spotify_playlist = [(track[0].encode('utf-8'), track[1].encode('utf-8'), track[2].encode('utf-8')) for track in spotify_playlist]

    # Only output playlist to stdout- no Google Play Music stuff
    if only_spotify:
        print("TRACK | ARTIST | ALBUM")
        for track in spotify_playlist:
            print("{} | {} | {}".format(track[0], track[1], track[2]))
    else:
        if g_user is None or g_pass is None or new_playlist_name is None:
            LOG.error("A Google username, password, and playlist name is required")
            sys.exit(1)

        gmusic = gmusic_login(g_user, g_pass)

        song_id_list = list()
        for track in spotify_playlist:
            LOG.debug("Searching and adding: {}".format(track))
            first_song_hit_id = gmusic_search(gmusic, "{} {}".format(track[0], track[1]))
            song_id_list.append(first_song_hit_id)

        LOG.debug("Creating new playlist: {}".format(new_playlist_name))
        new_playlist_id = gmusic_create_new_playlist(gmusic, new_playlist_name, spotify_external_url=metadata[1], spotify_description=metadata[0])
        LOG.debug("Adding songs to new playlist by ID")
        gmusic_add_to_playlist(gmusic, new_playlist_id, song_id_list)

        LOG.info("Complete!")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Eats a Spotify open playlist and creates a Google Play Music playlist from it", fromfile_prefix_chars='@')

    p.add_argument("--spotify", help="Specify the type of Spotify object {url,file} and the source", metavar=("{url,file}", "SOURCE"), required=True, nargs=2)

    group1 = p.add_argument_group('GPM Authentication')
    group1.add_argument("--gmusic-username", help="Google Play Music username", required=False, default=None)
    group1.add_argument("--gmusic-password", help="Google Play Music password", required=False, default=None)
    p.add_argument("--spotify-songs-plain", help="Only reads the Spotify source and outputs the tracks in STDOUT without making a Google Play Music playlist", action="store_true", default=False)
    p.add_argument("--new-playlist-name", help="The new Google Play Music playlist name", required=False, default=None)
    p.add_argument("--verbose", '-v', help="Set logging level to DEBUG", action='store_true', default=False)

    a = p.parse_args()
    print(a)
    if a.verbose:
        set_logging_handler(logging.DEBUG)
    else:
        set_logging_handler(logging.INFO)

    # Checking for valid parameter combinations
    if a.spotify[0] == "url":
        spotify_type = 0
    elif a.spotify[0] == "file":
        spotify_type = 1
    else:
        LOG.error("First param of --spotify must either be 'url' or 'file'")
        sys.exit(1)

    if a.spotify_songs_plain:
        main(only_spotify=True, spotify_type=spotify_type, spotify_source=a.spotify[1])
    else:
        # Do Google Play Music stuff
        if not a.gmusic_username or not a.gmusic_password or not a.new_playlist_name:
            LOG.error("You need to provide a Google username, password (app password, most likely), and a new playlist name")
            sys.exit(1)
        else:
            main(g_user=a.gmusic_username, g_pass=a.gmusic_password, new_playlist_name=a.new_playlist_name, spotify_type=spotify_type, spotify_source=a.spotify[1])

