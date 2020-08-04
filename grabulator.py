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


SLEEP_TIME        = 0.25
VEHICLE_DATA_FILE = 'grabulator.json'
VEHICLE_DATA_LEN  = 18
SEPARATOR_THIN    = '----------------------------------------------------------------------------'
SEPARATOR_BOLD    = '============================================================================'



# return inventory filtered url set
def get_inventory_url_set(url_set):
    return [l for l in url_set if '/inventory/' in l]

# get count of found vehicles for more better user info
def get_inventory_count(url_set):
    return len(get_inventory_url_set(url_set))

def get_dict_subset_available(sorted_dict):
    return collections.OrderedDict({k:v for k,v in filter(lambda t: 'removed' not in t[1], sorted_dict.items())})

def get_dict_subset_not_available(sorted_dict):
    return collections.OrderedDict({k:v for k,v in filter(lambda t: 'removed' in t[1], sorted_dict.items())})

def get_dict_subset_specials(sorted_dict):
    return collections.OrderedDict({k:v for k,v in filter(lambda t: t[1]['special'], sorted_dict.items())})

def get_dict_subset_not_specials(sorted_dict):
    return collections.OrderedDict({k:v for k,v in filter(lambda t: not t[1]['special'], sorted_dict.items())})

# fetch the set of urls to each vehicle found on the index page(s)
def fetch_url_set(urls):
    count = 0
    url_set = set([])

    print('Fetching {} index pages...'.format(len(urls)))
    for url in urls:
        count += 1
        new_set = get_url_set(url)
        if new_set == None:
            print('Received no data for index page {}'.format(count))
            return None

        url_set |= new_set
        print('Found {} vehicles on index page {} of {}; {} total'.format(
            get_inventory_count(new_set),
            count,
            len(urls),
            get_inventory_count(url_set)))
        time.sleep(SLEEP_TIME)

    return url_set

# fetches python "set" of urls to vehicles from Rairdon's search index page specified by the url param.
# Rairdon's site allows the user to query on vehicles/attributes and returns 20 matches per page maximum,
# additional matches will be on subsequent pages. Rairdons is currently hovering between 20 and 40
# vehicle listings of interest so this method is called twice, once for each page of <= 20 results.
def get_url_set(url, tries=3):
    # iterate tries attempts
    for i in range(tries):
        # print('get_url_set: try {}'.format(i + 1))

        # reset everything just to be safe
        urls = set([])
        session = None
        r = None

        # attempt to fetch the resource (search results) at url
        try:
            session = HTMLSession()
            r = session.get(url)
            if r.status_code == 200:
                r.html.render(timeout=15)
                urls = r.html.absolute_links
            else:
                print('get_url_set: GET status code != 200: {}'.format(r.status_code))
        except:
            print('get_url_set: exception caught\n{}'.format(sys.exc_info()[0]))

        # clean up resources
        if r:
            r.close()
        if session:
            session.close()

        # return fetched urls if succesful, otherwise retry if applicable
        if get_inventory_count(urls) < 1:
            print('Web fetch failed; retry...')
            time.sleep(SLEEP_TIME)
        else:
            return urls

    return set([])

# fetch page/data for each vehicle found in the inventory list and put into vehicle_dict
# dict whose key is the VIN and value is another dict of vehicle attributes. Updates items
# to normalize between the "our_price" and "original_price" vehicle attributes which
# are kind of weird as delivered.
def fetch_urls_to_dict(url_set, start_time):
    count = 0
    vehicle_dict = {}
    total = get_inventory_count(url_set)

    for url in get_inventory_url_set(url_set):
        count += 1
        print('Fetching data for vehicle {} of {}...'.format(count, total))

        #if count < 4:
        data = get_vehicle_data(url)
        if data:
            data['url'] = url
            data['updated'] = start_time
            data['created'] = start_time
            data['ext_color'] = data['ext_color'][:-15]
            data['post_title'] = data['post_title'][:-4]
            data['history'] = []

            if data['original_price'] == 0:
                data['special'] = False
                data['original_price'] = data['our_price']
            else:
                data['special'] = True

            vehicle_dict[data['vin']] = data
        else:
            print('Received no data for vehicle {}'.format(count))
            return None

        # time.sleep(SLEEP_TIME)

    return vehicle_dict

# fetches vehicle json data from vehicle page at url
def get_vehicle_data(url, tries=3, verbose=True):
    # iterate tries attempts
    for i in range(tries):
        # print('get_vehicle_data: try {}'.format(i + 1))
        data = None
        session = None
        r = None

        # attempt to fetch the resource (json vehicle data) at url
        try:
            session = HTMLSession()
            r = session.get(url)
            if r.status_code == 200:
                # r.html.render(timeout=15)
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

# parses sorted vehicle dict into "specials" and "normal" offers and prints the two lists
# with specials printed before normal offers.
def parse_print_offers(vehicle_dict_sorted, start_time):
    available = get_dict_subset_available(vehicle_dict_sorted)
    specials = get_dict_subset_specials(available)
    normal = get_dict_subset_not_specials(available)
    print('Found {} specials'.format(len(specials)))
    print('Found {} regular offers'.format(len(normal)))
    print(SEPARATOR_THIN)
    print_vehicle_dict(collections.OrderedDict(sorted(specials.items())), start_time=start_time, history=True)
    print_vehicle_dict(collections.OrderedDict(sorted(normal.items())), start_time=start_time, history=True)

# helper to print the provided vehicle dict
def print_vehicle_dict(vehicle_dict, verify_url=False, start_time=None, history=False):
    for vehicle in vehicle_dict:
        # if the vehicle is a special add the price delta between msrp and special price
        delta = '       '
        if vehicle_dict[vehicle]['special']:
            delta = ' [{}]'.format(vehicle_dict[vehicle]['original_price'] - vehicle_dict[vehicle]['our_price'])

        # if requested do web lookup to see if vehicle page is gone (truly dead?)
        verified = ''
        if verify_url:
            if None == get_vehicle_data(vehicle_dict[vehicle]['url'], tries=1, verbose=False):
                verified = '- '
            else:
                verified = '+ '

        timestamp = ''
        if start_time:
            timestamp = 0
            if 'removed' in vehicle_dict[vehicle]:
                timestamp = datetime.datetime.strptime(vehicle_dict[vehicle]['removed'], '%Y-%m-%dT%H:%M:%S.%f')
            else:
                timestamp = datetime.datetime.strptime(vehicle_dict[vehicle]['created'], '%Y-%m-%dT%H:%M:%S.%f')

            now_timestamp = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%S.%f')
            timestamp = ' [age: {}]'.format(now_timestamp - timestamp)

        print('{}vin:{} stock:{} msrp:{} price:{}{} \"{}\" {:30s} {}{}'.format(
            verified,
            vehicle_dict[vehicle]['vin'],
            vehicle_dict[vehicle]['stock'],
            vehicle_dict[vehicle]['original_price'],
            vehicle_dict[vehicle]['our_price'],
            delta,
            vehicle_dict[vehicle]['post_title'],
            vehicle_dict[vehicle]['ext_color'][:-5],
            vehicle_dict[vehicle]['url'],
            timestamp))

        if history:
            print_history(vehicle_dict[vehicle]['history'])

def print_history(history):
    for item in history:
        print('   {} {} {}'.format(item[0], item[1], item[2]))

# persists received data and compares new results against previous results
def parse_persist_adds_deletes(vehicle_dict_sorted, start_time):
    # if the previous live vehicle data exists use it
    if os.path.exists('./{}'.format(VEHICLE_DATA_FILE)):
        lines_emitted = False

        # open and read the previous live vehicle data
        prev_live = {}
        with open('./{}'.format(VEHICLE_DATA_FILE)) as f:
            prev_live = json.load(f)

        # sort the previous live vehicle data by key/VIN
        prev_sorted = OrderedDict(sorted(prev_live.items()))
        prev_sorted_not_available = collections.OrderedDict(sorted(get_dict_subset_not_available(prev_sorted).items()))

        # iterate through the newly fetched data (vehicle_dict_sorted)
        for vehicle in vehicle_dict_sorted:
            # if vehicle is not in persisted data it is new
            if vehicle not in prev_sorted:
                lines_emitted = True
                vehicle_dict_sorted[vehicle]['history'].append( (start_time, 'created', '') )

                print('! {} new vehicle in inventory'.format(vehicle))
                print_history(vehicle_dict_sorted[vehicle]['history'])

            # elif vehicle in prev_sorted_available:
            #     print('{}: vehicle previously found and live, update created'.format(vehicle))

            elif vehicle in prev_sorted_not_available:
                lines_emitted = True
                diff_price, diff_msrp = diff_price_msrp(prev_sorted_not_available[vehicle], vehicle_dict_sorted[vehicle])
                vehicle_dict_sorted[vehicle]['history'].append( (start_time, 'added', 'diff price:{} msrp:{}'.format(diff_price, diff_msrp)) )
                vehicle_dict_sorted[vehicle]['created'] = prev_sorted_not_available[vehicle]['created']
                vehicle_dict_sorted[vehicle]['updated'] = start_time
                if 'removed' in prev_sorted[vehicle]:
                    del prev_sorted[vehicle]['removed']

                print('+ {} was removed, for sale again [diff price:{} msrp:{}]'.format(
                    vehicle,
                    diff_price,
                    diff_msrp))
                print_history(vehicle_dict_sorted[vehicle]['history'])

        # iterate through the persisted data (prev_sorted)
        for vehicle in prev_sorted:
            if vehicle not in vehicle_dict_sorted:
                if 'removed' not in prev_sorted[vehicle]:
                    lines_emitted = True
                    prev_sorted[vehicle]['removed'] = start_time
                    prev_sorted[vehicle]['history'].append( (start_time, 'removed', '') )

                    print('X {} no longer listed for sale'.format(vehicle))
                    print_history(prev_sorted[vehicle]['history'])

                prev_sorted[vehicle]['updated'] = start_time
                vehicle_dict_sorted[vehicle] = prev_sorted[vehicle]
            else:
                diff_price, diff_msrp = diff_price_msrp(prev_sorted[vehicle], vehicle_dict_sorted[vehicle])
                if diff_price != 0 or diff_msrp != 0:
                    lines_emitted = True
                    prev_sorted[vehicle]['history'].append( (start_time, 'price', 'diff price:{} msrp:{}'.format(diff_price, diff_msrp)) )

                    print('= {} still for sale [diff price:{} msrp:{}]'.format(
                        vehicle,
                        diff_price,
                        diff_msrp))
                    print_history(prev_sorted[vehicle]['history'])

                vehicle_dict_sorted[vehicle]['updated'] = start_time
                vehicle_dict_sorted[vehicle]['created'] = prev_sorted[vehicle]['created']
                vehicle_dict_sorted[vehicle]['history'] = prev_sorted[vehicle]['history']

        if not lines_emitted:
            print('Nothing of interest to report')

        # if there are any dead report on them
        dead = collections.OrderedDict(sorted(get_dict_subset_not_available(prev_sorted).items(), reverse=True, key=lambda x: x[1]['removed']))
        if len(dead) > 0:
            print('\nRemoved from inventory: {}'.format(len(dead)))
            print(SEPARATOR_THIN)
            print_vehicle_dict(dead, verify_url=True, start_time=start_time, history=True)
    else:
        print('Did not find {}, creating and skipping dead handling'.format(VEHICLE_DATA_FILE))

    # persist the current vehicle data
    with open('./{}'.format(VEHICLE_DATA_FILE), 'w') as f:
        json.dump(vehicle_dict_sorted, f, indent=4, sort_keys=True)

def diff_price_msrp(prev_sorted, vehicle_dict_sorted):
    last_price = prev_sorted['our_price']
    last_msrp = prev_sorted['original_price']
    new_price = vehicle_dict_sorted['our_price']
    new_msrp = vehicle_dict_sorted['original_price']
    return new_price - last_price, new_msrp - last_msrp

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

    # fetch the set of urls to each vehicle found on the index page(s)
    url_set = fetch_url_set(urls)
    if url_set == None:
        print('\nFATAL ERROR fetching index page; exiting...\n')
        exit(1)

    # exit if no vehicles were found on the index page(s)
    if get_inventory_count(url_set) == 0:
        print('\nFATAL ERROR no vehicles found; exiting...\n')
        exit(1)

    # fetch page/data for each vehicle found in the inventory list and put into vehicle_dict
    # dict whose key is the VIN and value is another dict of vehicle attributes. Updates 
    # items to normalize between the "our_price" and "original_price" vehicle attributes
    # which are kind of weird as delivered.
    vehicle_dict = fetch_urls_to_dict(url_set, start_time)
    if vehicle_dict == None:
        print('\nFATAL ERROR fetching vehicle page; exiting...\n')
        exit(1)

    # sort the vehicle dict by key/VIN
    vehicle_dict_sorted = OrderedDict(sorted(vehicle_dict.items()))
    if vehicle_dict_sorted == None:
        print('\nFATAL ERROR sorting vehicle list; exiting...\n')
        exit(1)

    # persists received data and compares new results against previous results
    print('\nProcess results against last results and dead list...')
    print(SEPARATOR_THIN)
    parse_persist_adds_deletes(vehicle_dict_sorted, start_time)
    print()

    # parses sorted vehicle dict into "specials" and "normal" offers and prints the two lists
    # with specials printed before normal offers.
    parse_print_offers(vehicle_dict_sorted, start_time)
    print()


if __name__ == '__main__':
    main()
