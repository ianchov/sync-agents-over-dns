## What it solves?
Lets imagine a scenario:
We have an app instances=1 which do some periodic job - checking a url, making an api call whatever and then reporting the status of the job/api response/etc. If this app is unavailable because it is being redeployed(in CF, a new diego cell, in k8s the pod is recreated) then for a brief period of time the job that we need to be executed, wont be executed. Image the whole landscape in that region being down..a total outage.
So the objective is to have a reliable way to sync several of those app instances so at least one to execute the job and notify for its status.
How do we do that without complicating the architecture and without using any 3rd party tools like zookeper, etcd, postgresql?

We need a fault tolerant, simple solution to have a consensus over job agents. They are solutions - like the paxos algorithm, raft algorith and others however they require a connection between the agents or a leader election.

What if we want to have several agents without any knowleadge between themselves for the existence of the others? And then deploy those "agents" in different iaas regions and providers?

## What is the idea?

How to cheaply and reliably synchronize independent agents, which need to do some task regularly? The trick is that the agents do not have connection between them or any other knowledge for each other existence. Also we do not use any 3rd party tool, like database, arbiter, queue or whatever.

* No matter what, the task must be executed by at least 1 agent
* The agents are started randomly but after the initial start they check the dns record every (50-60) seconds
* The agents are stateless. They can be killed/replaced at any moment.
* No instance affinity - any agent can execute the job.
* The job can be changed dynamically and be picked on each new run
* Agents don`t know anything regarding other agents nor do they have connection between them


### A DNS txt record as a an arbiter 

The DNS infrastructure is one of the most resilient today. The DNS is a core internet service, on which every other service is dependent. A dns record can hold different information and also can have a special TTL (time to live properly). The beauty of the dns is that everyone can check the record, but not everyone can write to it. All major hyperscalers have near infinite dns scalability and capacity.

Here i use a DNS txt record to store text with which i synchronize the different agents. 
All agents are checking regularly the dns txt record and update the record if their clock is bigger than the one in the record and execute the required job/task.
On every run (lets say every 60 seconds), the each agent checks the txt record which looks like:

```json
{"id":"name", "timer":Int, "timerOld":int}
```
where:
*  id is the id or the name of the agent
* the timer holds the EPOCH time when when the task will be executed
* timerOld is the old timer value or when last it was executed

```json
Example entry
{"id": "VDNDNQNWQY", "timer": 1641903970, "timerold": 1641903859}
```

## Architecture

All agents are totally independent and do not have any knowledge for each other. They synchronize themselves over a dns TXT record. The dns record can be checked remotely via regular dns query. This is useful for a 3rd party monitoring or other 3rd party that needs to know if and when the task has been executed ( getting the timerold value is the last time this has been update and timer value is the next time the task and the entry will be updated).

Of course we can encrypted the txt record, if we see a need for that.

```bash
# If we ask the local dns resolver
dig -t TXT canary.backupsol.com

# or if we ask directly the DNSaaS (in the example case Cloudflare)
dig  @1.1.1.1 -t canary.backupsol.com

# or if our solution is using google cloud
dig  @8.8.8.8 -t canary.backupsol.com
```

### DNS live check
```bash
→ dig -t TXT canary.backupsol.com

; <<>> DiG 9.16.1-Ubuntu <<>> -t txt canary.backupsol.com
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 19092
;; flags: qr rd ra; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 65494
;; QUESTION SECTION:
;canary.backupsol.com.          IN      TXT

;; ANSWER SECTION:
canary.backupsol.com.   60      IN      TXT     "{\"id\": \"MAWDAHDOQH\", \"timer\": 1642500093, \"timerold\": 1642500022, \"entryid\": \"1b603cac9e8aeb0510e97aced8b9a934\"}"

;; Query time: 28 msec
;; SERVER: 10.100.2.3#53(10.100.2.3)
;; WHEN: Tue Jan 18 10:01:33 UTC 2022
;; MSG SIZE  rcvd: 174
```

The dns call can be executed live to see the changes in real time.

### Monitoring

We can implement monitoring by just querying the dns record regularly and evaluating the different fields. The timer value is the value indicating when next the job would be executed, timerold indicated when last it was executed.

### API calls costs

According to the pricing of Route53 the cost for managing a dns zone is $0.50 per month and includes 1 000 000 api calls free.

For Cloudflare, an account can make 1200 free api calls per minute.

So the cost of ownership a solution that manages independent agents is close to ZERO.

### Block diagram

![alt text](https://github.com/ianchov/sync-agents-over-dns/blob/master/images/blockdiagram.png?raw=true "Block diagram")

### Activity diagram

![Activity diagram](https://github.com/ianchov/sync-agents-over-dns/blob/master/images/activity.png?raw=true "Activity diagram")


### Sequential diagram

![Sequential diagram](https://github.com/ianchov/sync-agents-over-dns/blob/master/images/sequencial.png?raw=true "Sequential diagram")


![visual of 3 agents](https://github.com/ianchov/sync-agents-over-dns/blob/master/images/agents_syncing_over_api_calls.JPG?raw=true "Visual")


