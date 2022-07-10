import json
import logging
import os
import random
import string
import sys
import time
from configparser import ConfigParser
from dataclasses import asdict, dataclass, field
from logging import log
from typing import Optional

import CloudFlare
import dns.resolver
import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from loguru import logger

logger.remove()
logger.add(sys.stderr, level=os.environ.get("LOGLEVEL", "INFO"))
try:
    parser = ConfigParser()
    thisfolder = os.path.dirname(os.path.abspath(__file__))
    initfile = os.path.join(thisfolder, "config.ini")
    parser.read(initfile)
except Exception as e:
    logger.error(f"Problem with loading config.ini {e}")
    sys.exit(1)

try:
    SUBDOMAIN = parser.get("Default", "SUBDOMAIN")
    DOMAIN = parser["Default"]["DOMAIN"]
    FULLDNS = SUBDOMAIN + "." + DOMAIN
    USEDNSRESOLVER = os.environ.get(
        "USEDNSRESOLVER", parser["Default"]["USEDNSRESOLVER"]
    )
    CLOUDFLARE_TOKEN = parser["Default"]["CLOUDFLARE_TOKEN"]
    URL_POST = parser["Default"]["URL"]
except Exception as e:
    logger.error(f"Cannot load some variables from the config: {e}")
    sys.exit(1)

ZONEID = ""

AGENTID = "".join(random.choice(string.ascii_uppercase) for i in range(10))


@dataclass
class agentClass:
    id: str = field(init=False)
    timer: int
    timerold: Optional[int]
    entryid: str = field(default="", init=False)

    def __post_init__(self):
        self.id = AGENTID


def call_dns_resolver():
    """Make a dns resolver call (regular dns query)"""
    try:
        resolver = dns.resolver.Resolver(configure=False)
        resolver.nameservers = ["1.1.1.1"]
        answers = resolver.resolve(FULLDNS, "TXT")
        logger.debug(f"dns query qname: {answers.qname}  num ans. {len(answers)}")

        for rdata in answers:
            for txt_string in rdata.strings:
                logger.info(f' TXT: {txt_string.decode("utf-8")}')
                return txt_string
    except dns.resolver.NXDOMAIN:
        logger.warning(f"P{FULLDNS} does not exist..creating now")
        return False

    # return dnsdata


def get_zone_id(DOMAIN):
    """Get the zoneid of the domain from the cloudflare api"""

    try:
        r = cf.zones.get(params={"name": DOMAIN})
    except CloudFlare.CloudFlareAPIError as e:
        exit("/zones.get %s - %d %s" % (DOMAIN, e, e))
    except Exception as e:
        exit("/zones.get %s - %s" % (DOMAIN, e))

    return r[0]["id"]


def call_dns_api(ZONEID):
    """Call the cloudflare api for the dns entry of zoneid..each domain has zoneid"""

    try:
        dns_records = cf.zones.dns_records.get(ZONEID)
    except CloudFlare.exceptions.CloudFlareAPIError as e:
        exit("/zones/dns_records.get %d %s - api call failed" % (e, e))

    our_entry = next((item for item in dns_records if item["name"] == FULLDNS), False)
    return our_entry


def main():
    """Main function that should be executed via the apsheduler"""

    global ZONEID  # this can be moved to the agent attributes

    logger.info(f"Looking for subdomain {SUBDOMAIN}")

    logger.info(f"agent {agent.id} is here")
    logger.debug(f"{ZONEID=}")
    if not ZONEID:
        ZONEID = get_zone_id(DOMAIN=DOMAIN)

    dns_call = call_dns_resolver()  # check if the subdomain exists
    if not dns_call:
        logger.debug(f"It seems the dns zone(subdomain) is not there {dns_call=}")
        create_dns_entry(ZONEID, agent)
    else:
        our_entry = json.loads(dns_call)
        agent.entryid = our_entry["entryid"]

    logger.debug(f"{USEDNSRESOLVER=}")
    if USEDNSRESOLVER == "False" or not agent.entryid:
        # if the subdomain is newly created, the first dns resolver will have entryid as ''
        logger.info("Querying for the dns entry via api call")
        our_entry_response = call_dns_api(ZONEID)
        if our_entry_response:  # response is not False, else it is a first run
            our_entry = json.loads(our_entry_response["content"])
            agent.entryid = our_entry_response["id"]
            agent.timerold = our_entry["timerold"]
            agent.timer = our_entry["timer"]
            logger.debug(f"{agent=}")

    # rand_num = random.randint(1, 10)  # used to add to each agent new timer
    rand_num = 0

    currenttime = int(time.time())
    total = int(currenttime) + rand_num + 60
    logger.info(f"{total=} - {rand_num=}")
    logger.info(
        f'Current time is: {time.strftime("%b %d %Y %H:%M:%S", time.localtime(currenttime))} '
        f' vs new time: {time.strftime("%b %d %Y %H:%M:%S", time.localtime(agent.timer))}'
    )
    if currenttime >= agent.timer:
        logger.debug("Current timer >= agent.timer")
        agent.timerold = agent.timer
        agent.timer = total
        dns_record = {
            "name": SUBDOMAIN,
            "type": "TXT",
            "content": json.dumps(asdict(agent)),
            "ttl": 60,
        }
        logger.debug(f"Patching...with {agent=}")
        try:
            r = cf.zones.dns_records.patch(
                ZONEID, identifier2=agent.entryid, data=dns_record
            )
        except CloudFlare.exceptions.CloudFlareAPIError as e:
            logger.error(f"Couldnt patch the dns record: api error: {e}")

        logger.debug(
            f'Patched with a new time {time.strftime("%b %d %Y %H:%M:%S", time.localtime(total))}'
        )
        execute_task()


def create_dns_entry(ZONEID, agent):
    """Create the txt record for the subdomain via an api call to cloudflare"""
    dns_record = {
        "name": SUBDOMAIN,
        "type": "TXT",
        "content": json.dumps(asdict(agent)),
        "ttl": 60,
    }
    try:
        r = cf.zones.dns_records.post(ZONEID, data=dns_record)
        logger.debug(f"Created dns entry {dns_record=} with return {r=}")
    except CloudFlare as e:
        logger.error(f"Couldn`t craete the dns entry {dns_record=}..error {e}")
        return False

    return True


def execute_task():
    """An example task that each agent needs to execute"""
    data = {
        "name": agent.id,
        "timer": agent.timer,
        "timerold": agent.timerold,
        "passcode": 1641466583,
    }
    logger.debug(f"Sending json {data=}")
    r = requests.post(
        URL_POST, json=data, headers={"Content-Type": "application/json; charset=utf-8"}
    )
    logger.debug(f"POST sent {r.text}")
    return True


if __name__ == "__main__":

    cf = CloudFlare.CloudFlare(
        token=CLOUDFLARE_TOKEN,
        debug=os.environ.get("CFDEBUG", False),
        use_sessions=True,
    )
    agent = agentClass(timer=int(time.time()), timerold=0)
    sched = BlockingScheduler(standalone=True, timezone="Europe/Berlin")
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    r = random.randint(1, 60)
    logger.info(f"Sleeping for {r}")
    time.sleep(r)
    # main()
    sched.add_job(main, "interval", seconds=random.randint(50, 60))
    # sched.add_job(main, "interval", seconds=60)
    try:
        logger.debug("Starting scheduler")
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info(f"Cancelling with the remaing: {sched.print_jobs()}")
        sched.shutdown()
        sys.exit()
