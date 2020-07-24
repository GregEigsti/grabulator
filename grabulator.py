#!/usr/bin/env python

import collections
import copy
import datetime
import json
import os
import time
import sys
from collections import OrderedDict
from requests_html import HTMLSession


SLEEP_TIME        = 1.00
VEHICLE_DATA_FILE = 'grabulator.json'
VEHICLE_DATA_LEN  = 18
SEPARATOR_THIN    = '----------------------------------------------------------------------------'
SEPARATOR_BOLD    = '============================================================================'



# fetches python "set" of links to vehicles from Rairdon's search index page specified by the url param.
# Rairdon's site allows the user to query on vehicles/attributes and returns 20 matches per page maximum,
# additional matches will be on subsequent pages. Rairdons is currently hovering between 20 and 40
# vehicle listings of interest so this method is called twice, once for each page of <= 20 results.
def get_url_set(url, tries=3):
    # iterate tries attempts
    for i in range(tries):
        # print('get_url_set: try {}'.format(i + 1))

        # reset everything just to be safe
        links = set([])
        session = None
        r = None

        # attempt to fetch the resource (search results) at url
        try:
            session = HTMLSession()
            r = session.get(url)
            if r.status_code == 200:
                r.html.render()
                links = r.html.absolute_links
            else:
                print('get_url_set: GET status code != 200: {}'.format(r.status_code))
        except:
            print('get_url_set: exception caught\n{}'.format(sys.exc_info()[0]))

        # clean up resources
        if r:
            r.close()
        if session:
            session.close()

        # return fetched links if succesful, otherwise retry if applicable
        if get_inventory_count(links) < 1:
            print('Web fetch failed; retry...')
            time.sleep(SLEEP_TIME)
        else:
            return links

    return set([])

# fetches vehicle json data from vehicle page at url
def get_vehicle_data(url, tries=3, verbose=True):
    # iterate tries attempts
    for i in range(tries):
        # print('get_vehicle_data: try {}'.format(i + 1))

        # reset everything just to be safe
        data = None
        session = None
        r = None

        # attempt to fetch the resource (json vehicle data) at url
        try:
            session = HTMLSession()
            r = session.get(url)
            if r.status_code == 200:
                r.html.render()
                vehicle_data = r.html.search('"vehicle":{};')[0]
                data = json.loads(vehicle_data[:-1])
            else:
                if verbose:
                    print('get_vehicle_data: GET status code != 200: {}'.format(r.status_code))
        except: # <class 'pyppeteer.errors.TimeoutError'>
            if verbose:
                print('get_vehicle_data: exception caught\n{}'.format(sys.exc_info()[0]))

        # clean up resources
        if r:
            r.close()
        if session:
            session.close()

        # return fetched json vehicle data if succesful, otherwise retry if applicable
        if not data or len(data) != VEHICLE_DATA_LEN:
            if verbose:
                print('Web fetch failed; retry...')
            time.sleep(SLEEP_TIME)
        else:
            return data

    return None

# helper to print the provided vehicle dict
def print_vehicle_dict(vehicle_dict, verify_link=False, start_time=None):
    for vehicle in vehicle_dict:
        # if the vehicle is a special add the price delta between msrp and special price
        delta = '       '
        if vehicle_dict[vehicle]['special']:
            delta = ' [{}]'.format(vehicle_dict[vehicle]['original_price'] - vehicle_dict[vehicle]['our_price'])

        # if requested do web lookup to see if vehicle page is gone (truly dead?)
        verified = ''
        if verify_link:
            if None == get_vehicle_data(vehicle_dict[vehicle]['link'], tries=1, verbose=False):
                verified = '- '
            else:
                verified = '+ '

        timestamp = ''
        if start_time:
            removed_timestamp = datetime.datetime.strptime(vehicle_dict[vehicle]['removed'], '%Y-%m-%dT%H:%M:%S.%f')
            now_timestamp = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%S.%f')
            timestamp = ' [dead: {}]'.format(now_timestamp - removed_timestamp)

        print('{}vin:{} stock:{} msrp:{} price:{}{} \"{}\" {:30s} {}{}'.format(
            verified,
            vehicle_dict[vehicle]['vin'],
            vehicle_dict[vehicle]['stock'],
            vehicle_dict[vehicle]['original_price'],
            vehicle_dict[vehicle]['our_price'],
            delta,
            vehicle_dict[vehicle]['post_title'],
            vehicle_dict[vehicle]['ext_color'][:-5],
            vehicle_dict[vehicle]['link'],
            timestamp))

    return True

# fetch the set of links/urls to each vehicle found on the index page(s)
def fetch_link_set(urls):
    count = 0
    link_set = set([])

    for url in urls:
        count += 1
        url_set = get_url_set(url)
        if url_set == None:
            print('Received no data for index page {}'.format(count))
            return None

        link_set |= url_set
        print('Found {} vehicles on page {} of {} for a total of {}'.format(
            get_inventory_count(url_set),
            count,
            len(urls),
            get_inventory_count(link_set)))
        time.sleep(SLEEP_TIME)

    return link_set

# return inventory filtered link set
def get_inventory_link_set(link_set):
    return [l for l in link_set if '/inventory/' in l]

# get count of found vehicles for more better user info
def get_inventory_count(link_set):
    return len(get_inventory_link_set(link_set))

# fetch page/data for each vehicle found in the inventory list and put into vehicle_dict
# dict whose key is the VIN and value is another dict of vehicle attributes
def fetch_links_to_dict(link_set, start_time):
    count = 0
    vehicle_dict = {}
    total = get_inventory_count(link_set)
    print('Found a total of {} vehicles'.format(total))

    for link in get_inventory_link_set(link_set):
        count += 1
        print('Fetching data for vehicle {} of {}...'.format(count, total))

        #if count < 4:
        data = get_vehicle_data(link)
        if data:
            data['link'] = link
            data['updated'] = start_time
            data['created'] = start_time
            data['special'] = False
            data['available'] = True
            data['ext_color'] = data['ext_color'][:-15]
            data['post_title'] = data['post_title'][:-4]
            vehicle_dict[data['vin']] = data
        else:
            print('Received no data for vehicle {}'.format(count))
            return None

        time.sleep(SLEEP_TIME)

    return vehicle_dict

# parses sorted vehicle dict into "specials" and "normal" offers and prints the two lists
# with specials printed before normal offers. Updates vehicle_dict_sorted dict items
# to normalize between the "our_price" and "original_price" vehicle attributes which
# are kind of weird as delivered.
def parse_print_offers(vehicle_dict_sorted):
    specials = {}
    for vehicle in vehicle_dict_sorted:
        if vehicle_dict_sorted[vehicle]['original_price'] != 0:
            specials[vehicle] = vehicle_dict_sorted[vehicle]
            vehicle_dict_sorted[vehicle]['special'] = True

    normal = {}
    for vehicle in vehicle_dict_sorted:
        if vehicle_dict_sorted[vehicle]['original_price'] == 0:
            vehicle_dict_sorted[vehicle]['original_price'] = vehicle_dict_sorted[vehicle]['our_price']
            normal[vehicle] = vehicle_dict_sorted[vehicle]

    print('\nFound {} specials'.format(len(specials)))
    print('Found {} regular offers'.format(len(normal)))
    print(SEPARATOR_THIN)
    print_vehicle_dict(collections.OrderedDict(sorted(specials.items())))
    print_vehicle_dict(collections.OrderedDict(sorted(normal.items())))

def get_dict_subset_available(sorted_dict):
    return collections.OrderedDict({k:v for k,v in filter(lambda t: t[1]['available'], sorted_dict.items())})

def get_dict_subset_not_available(sorted_dict):
    return collections.OrderedDict({k:v for k,v in filter(lambda t: not t[1]['available'], sorted_dict.items())})

# persists received data and compares new results against previous results
def parse_persist_adds_deletes(vehicle_dict_sorted, start_time):
    # if the previous live vehicle data exists use it
    if os.path.exists('./{}'.format(VEHICLE_DATA_FILE)):
        # open and read the previous live vehicle data
        prev_live = {}
        with open('./{}'.format(VEHICLE_DATA_FILE)) as f:
            prev_live = json.load(f)

        # sort the previous live vehicle data by key/VIN
        prev_sorted = OrderedDict(sorted(prev_live.items()))
        prev_sorted_not_available = collections.OrderedDict(sorted(get_dict_subset_not_available(prev_sorted).items()))

        for vehicle in vehicle_dict_sorted:
            if vehicle not in prev_sorted:
                print('! {} new vehicle in inventory'.format(vehicle))
            # elif vehicle in prev_sorted_available:
            #     print('{}: vehicle previously found and live, update created'.format(vehicle))
            elif vehicle in prev_sorted_not_available:
                last_price = prev_sorted_not_available[vehicle]['our_price']
                last_msrp = prev_sorted_not_available[vehicle]['original_price']
                new_price = vehicle_dict_sorted[vehicle]['our_price']
                new_msrp = vehicle_dict_sorted[vehicle]['original_price']
                print('+ {} was dead, for sale again [diff price:{} msrp:{}]'.format(
                    vehicle,
                    new_price - last_price,
                    new_msrp - last_msrp))
                vehicle_dict_sorted[vehicle]['created'] = vehicle_dict_sorted[vehicle]['created']
                if 'removed' in vehicle_dict_sorted[vehicle]:
                    del prev_sorted[vehicle]['removed']
                vehicle_dict_sorted[vehicle]['updated'] = start_time
                vehicle_dict_sorted[vehicle]['available'] = True

        for vehicle in prev_sorted:
            if vehicle not in vehicle_dict_sorted:
                if 'removed' not in prev_sorted[vehicle]:
                    print('X {} no longer listed for sale'.format(vehicle))
                    prev_sorted[vehicle]['removed'] = start_time
                prev_sorted[vehicle]['updated'] = start_time
                prev_sorted[vehicle]['available'] = False
                vehicle_dict_sorted[vehicle] = prev_sorted[vehicle]
            else:
                last_price = prev_sorted[vehicle]['our_price']
                last_msrp = prev_sorted[vehicle]['original_price']
                new_price = vehicle_dict_sorted[vehicle]['our_price']
                new_msrp = vehicle_dict_sorted[vehicle]['original_price']
                print('= {} still for sale [diff price:{} msrp:{}]'.format(
                    vehicle,
                    new_price - last_price,
                    new_msrp - last_msrp))
                vehicle_dict_sorted[vehicle]['created'] = prev_sorted[vehicle]['created']
                vehicle_dict_sorted[vehicle]['updated'] = start_time

        # if there are any dead report on them
        dead = collections.OrderedDict(sorted(get_dict_subset_not_available(prev_sorted).items(), reverse=True, key=lambda x: x[1]['removed']))
        if len(dead) > 0:
            print('\nRemoved from inventory: {}'.format(len(dead)))
            print(SEPARATOR_THIN)
            print_vehicle_dict(dead, verify_link=True, start_time=start_time)
    else:
        print('Did not find {}, creating and skipping dead handling'.format(VEHICLE_DATA_FILE))

    # persist the current vehicle data
    with open('./{}'.format(VEHICLE_DATA_FILE), 'w') as f:
        json.dump(vehicle_dict_sorted, f, indent=4, sort_keys=True)

    # put an empty line at bottom of output
    print()


def main():
    start_time = datetime.datetime.utcnow().isoformat()
    print(SEPARATOR_BOLD)
    print('Rairdon\'s Totem Lake Gladiator Rubicon Grabulator')
    print(start_time)
    print(SEPARATOR_BOLD)

    # urls of the known search results pages (index pages). Current inventory is 27 Gladiator
    # Rubicons which spans two index pages (20 vehicles per page). If results = 40 manually
    # look for page 3, if < 20 remove second page. Manual process...
    urls = [
        'https://www.dodgechryslerjeepofkirkland.com/new-vehicles/gladiator-2/?_dFR%5Bmodel%5D%5B0%5D=Gladiator&_dFR%5Btrim%5D%5B0%5D=Rubicon&_dFR%5Btype%5D%5B0%5D=New&_paymentType=our_price',
        'https://www.dodgechryslerjeepofkirkland.com/new-vehicles/gladiator-2/?_p=1&_dFR%5Bmodel%5D%5B0%5D=Gladiator&_dFR%5Btrim%5D%5B0%5D=Rubicon&_dFR%5Btype%5D%5B0%5D=New&_paymentType=our_price'
    ]

    # print('Choochin on {} index pages...'.format(len(urls)))

    # fetch the set of links/urls to each vehicle found on the index page(s)
    link_set = fetch_link_set(urls)
    if link_set == None:
        print('FATAL ERROR fetching index page; exiting...')
        exit(1)

    # fetch page/data for each vehicle found in the inventory list and put into vehicle_dict
    # dict whose key is the VIN and value is another dict of vehicle attributes
    vehicle_dict = fetch_links_to_dict(link_set, start_time)
    if vehicle_dict == None:
        print('FATAL ERROR fetching vehicle page; exiting...')
        exit(1)

    # sort the vehicle dict by key/VIN
    vehicle_dict_sorted = OrderedDict(sorted(vehicle_dict.items()))
    if vehicle_dict_sorted == None:
        print('FATAL ERROR sorting vehicle list; exiting...')
        exit(1)

    # parses sorted vehicle dict into "specials" and "normal" offers and prints the two lists
    # with specials printed before normal offers. Updates vehicle_dict_sorted dict items
    # to normalize between the "our_price" and "original_price" vehicle attributes which
    # are kind of weird as delivered.
    parse_print_offers(vehicle_dict_sorted)

    # persists received data and compares new results against previous results
    print('\nProcess results against last results and dead list...')
    print(SEPARATOR_THIN)
    parse_persist_adds_deletes(vehicle_dict_sorted, start_time)
    

if __name__ == '__main__':
    main()
