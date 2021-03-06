#!/usr/bin/python

import cherrypy as http
import cherrypy.lib.cptools
from jinja2 import Template
from jinja2 import Environment, PackageLoader
from datetime import date
import time
import datetime
import json
import base64
import os
import os.path
import thread
from subprocess import Popen, PIPE
from peewee import *
import shutil
import shlex


#-------------------CONFIGURATION-----------------------------

ALLOW_IPs=["127.0.0.1","10.10.1.1"] # List of IP addresses that can access the API and GUI.
CONF_REISSUE_DAYS_BEFORE=83 # reisue certificates after XX days. (XX days before 90 day expiration date)
CONF_PROCESSING_LOOP_TIME=10 # Run the bacground processing thread each X seconds.
CONF_RENEW_CERTIFICATE_DAYS_BEFORE=7 # Number of days before the processing hread will try to re_issue certifcates.
CONF_WEBROOT_PATH="/var/www/html/" # Path to Webroot for autentification. See instalation notes for info.
CONF_LE_PATH="/etc/letsencrypt/" # Path to LetsEncrypt directory
CONF_LETSENCRYPT_ACME_CLIENT_BINARY="/root/.local/share/letsencrypt/bin/letsencrypt"
CONF_SQLITE_FILE="./data/main.db" # Path where to store the SQLite file as database backend
CONF_DEBUG_OUTPUT=True # writes output from CLI clommands to directory /debug
CONF_RUN_REISSUE_ON_LOOP_NO=1000 #this is only for fine-tuning the daemin process, leave this as it is!
APP_VERSION="0.1 free"
#-------------------CONFIG END--------------------------------


db = SqliteDatabase(CONF_SQLITE_FILE)

MY_START_TIME=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
MY_START_TIME_UNIX=time.localtime()
APP_TMP_LOOP_RUN=CONF_RUN_REISSUE_ON_LOOP_NO


class Cert(Model):
    rootdomain = CharField()
    hostname = CharField(unique=True)
    status = CharField()
    validto = CharField(default="")
    updated = IntegerField(default=0)
    pooltag = IntegerField(default=0)
    class Meta:
        database = db

class Log(Model):
    hostname = CharField()
    source = CharField()
    timestamp = CharField()
    message = CharField()
    class Meta:
        database = db


#this checks if the SQLfile exist, if not the tables will be created
if (os.path.exists(CONF_SQLITE_FILE)<>True):
    print "Database file not exist. Creating it!"
    db.create_tables([Cert,Log])

db.connect()


env = Environment(loader=PackageLoader('app', 'templates'))


def check_ip():
    print "Request From: "+cherrypy.request.remote.ip

    if cherrypy.request.remote.ip in ALLOW_IPs:
	return
    else:
        raise cherrypy.HTTPError("403 Forbidden", "You are not allowed to access this resource. Please update config. ( Your IP: "+cherrypy.request.remote.ip+" )")


def log_log(hostname="",source="",message=""):
    print ("log: [source="+source+"] ("+hostname+") "+message)
    NEW_LOG = Log(hostname=hostname.lower(), source=source, message=message,timestamp=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    NEW_LOG.save()


def log_debug(action="",output="",hostname=""):
    if CONF_DEBUG_OUTPUT==True:
	timestamp=str(int(time.time()))
	f = open('./debug/'+timestamp+"_"+action+"_"+hostname+".txt", 'w')
	f.write(output)
	f.close()

class lesslserver:


    @http.expose
    def docs(self):
	check_ip()
	template = env.get_template('docs.html')
	return template.render()




    @http.expose
    def api_cert_info(self,hostname=""):
	check_ip()
	hostname=hostname.lower()
	RESPONSE_STATUS="error"
	RESPONSE_MESSAGE="No valid hostname provided!"

	if (hostname<>""):
    	    try:
		CERT_INFO = Cert.get(Cert.hostname == hostname )
		RESPONSE_STATUS=CERT_INFO.status
		RESPONSE_MESSAGE=""
		if "error" in CERT_INFO.status:
		    RESPONSE_STATUS=CERT_INFO.status
		    RESPONSE_MESSAGE="Certificate Issue Error. See backed for details. (status details="+CERT_INFO.status+")"

		if "_create" in CERT_INFO.status:
		    RESPONSE_STATUS="processing"
		    RESPONSE_MESSAGE="Certificate is processing at this time! (status details="+CERT_INFO.status+")"

		if "delete" in CERT_INFO.status:
		    RESPONSE_STATUS="processing"
		    RESPONSE_MESSAGE="Certificate is processing at this time! (status details="+CERT_INFO.status+")"

		if (CERT_INFO.status=="created"):
		    RESPONSE_STATUS="created"
		    RESPONSE_MESSAGE="Certificate created, looks ok."

		    CERT_CERT_FILE=open(CONF_LE_PATH+"live/"+hostname+"/cert.pem", 'r')
		    CERT_CERT=base64.b64encode(CERT_CERT_FILE.read())
		    CERT_CERT_FILE.close()

		    CERT_CHAIN_FILE=open(CONF_LE_PATH+"live/"+hostname+"/chain.pem", 'r')
		    CERT_CHAIN=base64.b64encode(CERT_CHAIN_FILE.read())
		    CERT_CHAIN_FILE.close()

		    CERT_FULLCHAIN_FILE=open(CONF_LE_PATH+"live/"+hostname+"/fullchain.pem", 'r')
		    CERT_FULLCHAIN=base64.b64encode(CERT_FULLCHAIN_FILE.read())
		    CERT_FULLCHAIN_FILE.close()

		    CERT_PRIVKEY_FILE=open(CONF_LE_PATH+"live/"+hostname+"/privkey.pem", 'r')
		    CERT_PRIVKEY=base64.b64encode(CERT_PRIVKEY_FILE.read())
		    CERT_PRIVKEY_FILE.close()
		
	    except:
		RESPONSE_STATUS="error"
		RESPONSE_MESSAGE="No such certificate!"


	if (RESPONSE_STATUS<>"created"):
	    message = {"human_message" : RESPONSE_MESSAGE, "status":RESPONSE_STATUS}

	if (RESPONSE_STATUS=="created"):
	    message = {"human_message" : RESPONSE_MESSAGE, "status":RESPONSE_STATUS,"cert_cert": CERT_CERT,"cert_chain":CERT_CHAIN,"cert_fullchain":CERT_FULLCHAIN,"cert_privkey":CERT_PRIVKEY}

        return json.dumps(message)



    @http.expose
    def gui_cert_manage(self,hostname="",pool="",op=""):
	check_ip()
	hostname=hostname.lower()
	RESPONSE_STATUS="error"
	RESPONSE_MESSAGE="No valid hostname provided!"
	CERT_CERT=""
	CERT_CHAIN=""
	CERT_PRIVKEY=""
	CERT_FULLCHAIN=""

	if (hostname<>""):
	    if (pool=="tag"):
		POOL_CERT = Cert.get(Cert.hostname == hostname )
		POOL_CERT.pooltag=1
		POOL_CERT.save()
		raise cherrypy.HTTPRedirect('/gui_cert_manage?hostname='+hostname)

	    if (op=="validdate"):
		POOL_CERT = Cert.get(Cert.hostname == hostname )
		POOL_CERT.validto=str(check_cert_valid_date(hostname))
		POOL_CERT.save()
		raise cherrypy.HTTPRedirect('/gui_cert_manage?hostname='+hostname)

	    if (op=="to_delete"):
		POOL_CERT = Cert.get(Cert.hostname == hostname )
		POOL_CERT.status="to_delete"
		POOL_CERT.save()
		raise cherrypy.HTTPRedirect('/gui_certs')

	    if (op=="renew"):
		POOL_CERT = Cert.get(Cert.hostname == hostname )
		POOL_CERT.status="to_re_create"
		POOL_CERT.save()
		raise cherrypy.HTTPRedirect('/gui_cert_manage?hostname='+hostname)


    	    try:
		CERT_INFO = Cert.get(Cert.hostname == hostname )
	    

		if (CERT_INFO.status=="created"):
		    RESPONSE_STATUS="created"

		    CERT_CERT_FILE=open(CONF_LE_PATH+"live/"+hostname+"/cert.pem", 'r')
		    CERT_CERT=CERT_CERT_FILE.read()
		    CERT_CERT_FILE.close()

		    CERT_CHAIN_FILE=open(CONF_LE_PATH+"live/"+hostname+"/chain.pem", 'r')
		    CERT_CHAIN=CERT_CHAIN_FILE.read()
		    CERT_CHAIN_FILE.close()

		    CERT_FULLCHAIN_FILE=open(CONF_LE_PATH+"live/"+hostname+"/fullchain.pem", 'r')
		    CERT_FULLCHAIN=CERT_FULLCHAIN_FILE.read()
		    CERT_FULLCHAIN_FILE.close()

		    CERT_PRIVKEY_FILE=open(CONF_LE_PATH+"live/"+hostname+"/privkey.pem", 'r')
		    CERT_PRIVKEY=CERT_PRIVKEY_FILE.read()
		    CERT_PRIVKEY_FILE.close()
		
	    except:
		RESPONSE_STATUS="error_no_certificate"
	updated_date=datetime.datetime.fromtimestamp(CERT_INFO.updated).strftime('%Y-%m-%d %H:%M:%S')
	template = env.get_template('gui_cert_manage.html')
	return template.render(cert=CERT_INFO,cert_cert=CERT_CERT,cert_chain=CERT_CHAIN,cert_fullchain=CERT_FULLCHAIN,cert_privkey=CERT_PRIVKEY,updated_date=updated_date)




    @http.expose
    def api_cert_create(self,subdomain="",root_domain=""):

	hostname=root_domain.strip()
	if (subdomain.strip()<>""):
	    hostname=subdomain.strip().lower()+"."+root_domain.strip().lower()

	OUT_STATUS="already_exist"
	OUT_NOTE="Cert for "+hostname+" already exist!"
    
	try:
    	    GET_HOSTNAME = Cert.get(Cert.hostname == hostname.lower())
	except:
    	    OUT_STATUS="create_job_scheduled"
    	    OUT_NOTE=""

	if (root_domain.strip()==""):
    	    OUT_STATUS="error"
    	    OUT_NOTE="Root_Domain not defined!"


	if (OUT_STATUS=="create_job_scheduled"):
    	    print "Certificate create scheduled in DB."
    	    NEW_DOMAIN = Cert(rootdomain=root_domain.lower(), hostname=hostname.lower(), status='to_create')
    	    NEW_DOMAIN.save() 
	
	log_log(hostname,"api","Create Request (result="+OUT_STATUS+") .")
	message = {"status" : OUT_STATUS,"note": OUT_NOTE,"hostname":hostname }
        return json.dumps(message)


    @http.expose
    def api_cert_revoke(self,hostname=""):
	check_ip()
	hostname=hostname.strip()
	OUT_STATUS="no_certificate"
	OUT_NOTE="Cert "+hostname+" not exist or is already deleted/revoked!"

	try:
	    GET_CERT = Cert.get(Cert.hostname == hostname)
	except:
	    OUT_STATUS="no_certificate"
	    OUT_NOTE="Cert "+hostname+" not exist or is already deleted/revoked!"

	try:
	    if (GET_CERT.status=="created" or "error" in GET_CERT.status):
	        GET_CERT.status="to_delete"
	        GET_CERT.save()
	        OUT_STATUS="revoke_job_scheduled"
	        OUT_NOTE=""
	    else:
	        OUT_STATUS="no_certificate"
	        OUT_NOTE="Cert "+hostname+" not exist or is already deleted/revoked!"
	except:
	    pass


	log_log(hostname,"api","Revoke Request (result="+OUT_STATUS+") .")

	message = {"status" : OUT_STATUS,"note": OUT_NOTE,"hostname":hostname }
        return json.dumps(message)



    @http.expose
    def gui_certs(self):
	check_ip()
	template = env.get_template('gui_certs.html')
	return template.render(domain_list=Cert.select())


    @http.expose
    def api_pool(self,limit=1):
	check_ip()
	if limit==0: limit=1
	POOL_DATA=Cert.select().where(Cert.pooltag==1).limit(limit)
	POOL_LIST=","
	POOL_COUNT=POOL_DATA.count()
	print "Pool size:"+str(POOL_COUNT)
	for CERT in POOL_DATA:
	    POOL_LIST=POOL_LIST+","+CERT.hostname
	    CERT.pooltag=0
	    CERT.save()
	POOL_LIST=POOL_LIST.replace(",,","")
	message = {"pool_size" : POOL_COUNT,"pool_data": POOL_LIST }
        return json.dumps(message)


    @http.expose
    def gui_log(self,hostname=""):
	check_ip()
	template = env.get_template('gui_log.html')
	ALL_HOSTS=Log.select(fn.Distinct(Log.hostname))
	if (hostname=="*"):
		LOG_DATA=Log.select().order_by(-Log.id).limit(3000)
	else:
		LOG_DATA=Log.select().where(Log.hostname==hostname).order_by(-Log.id)


	return template.render(log_data=LOG_DATA,log_hosts=ALL_HOSTS,hostname=hostname)


    @http.expose
    def gui_dashboard(self):
	check_ip()
	template = env.get_template('gui_dashboard.html')

	MY_DATA={
	    "uptime_from":MY_START_TIME,
	    "uptime_from_unix":MY_START_TIME_UNIX,
	    "sqlite_size":os.stat('./data/main.db'),
	    "cert_count": Cert.select().count(),
	    "cert_all": len(Log.select(fn.Distinct(Log.hostname))),
	    "log_count": Log.select().count(),
	    "config_log_error": http.config["log.error_file"],
	    "config_log_access": http.config["log.access_file"],
	    "app_version": APP_VERSION,
	}

#	return template.render(uptime_from=MY_START_TIME,uptime_from_unix=MY_START_TIME_UNIX,sqlite_size=os.stat('./data/main.db'))
	return template.render(MY_DATA)

    @http.expose
    def index(self):
	check_ip()
	template = env.get_template('gui_index.html')
	return template.render()




def exe_cert_cmd_create(hostname,event="issue"):

    CERT = Cert.get(Cert.hostname==hostname)
    OLD_STATUS=CERT.status
    CERT.status="error:unknow"

    cmd = CONF_LETSENCRYPT_ACME_CLIENT_BINARY+" certonly --webroot --webroot-path "+CONF_WEBROOT_PATH+" -d "+hostname+" --renew-by-defaul"
    output=Popen(shlex.split(cmd), stdin=PIPE, stdout=PIPE, stderr=PIPE).communicate()[0]
    log_debug("issue",output,hostname)
    print "--------------LetsEncrypt CLI Output------------------"
    print output
    print "------------------------------------------------------"

    if "error:unauthorized" in output:
	CERT.status="error:unauthorized"

    if "error:connection" in output:
	CERT.status="error:connection"

    if "too many requests" in output:
	CERT.status="error:too_many_requests"

    if "Congratulations" in output:
	CERT.status="created"
	CERT.pooltag=1
	CERT.updated=int(time.time())
	CERT.validto=str(check_cert_valid_date(hostname))

    CERT.save()
    log_log(CERT.hostname,"automat",event+" Cert. Status Change:("+OLD_STATUS+" -> "+CERT.status+").")





def check_cert_valid_date(hostname=""):
    hostname=hostname.lower()
    print "check validity"


    cmd = "openssl x509 -noout -dates -in "+CONF_LE_PATH+"live/"+hostname+"/cert.pem"
    output=Popen(shlex.split(cmd), stdin=PIPE, stdout=PIPE, stderr=PIPE).communicate()[0]
    print "----------------OpenSSL CLI Output--------------------"
    print output
    print "------------------------------------------------------"
    for line in output.splitlines():
	if "notAfter" in line:
	    NOT_AFTER=line
	    NOT_AFTER=NOT_AFTER.replace("notAfter","")
	    NOT_AFTER=NOT_AFTER.replace("=","")
	    NOT_AFTER=NOT_AFTER.replace("  "," ")

    print "Checking Certificate Valid Date for "+hostname+", is valid to: " +NOT_AFTER
    return NOT_AFTER

def delete_certificate(hostname):
    try:
	cmd = CONF_LETSENCRYPT_ACME_CLIENT_BINARY+" revoke --cert-path "+CONF_LE_PATH+"live/"+hostname+"/cert.pem"
	output=Popen(shlex.split(cmd), stdin=PIPE, stdout=PIPE, stderr=PIPE).communicate()[0]
	log_debug("issue",output,hostname)
	print "--------------LetsEncrypt CLI Output------------------"
	print output
	print "------------------------------------------------------"
    except:
	pass

    print cmd
    try:
	shutil.rmtree(CONF_LE_PATH+"live/"+hostname+"/", ignore_errors=True)
	shutil.rmtree(CONF_LE_PATH+"archive/"+hostname+"/", ignore_errors=True)
	os.remove(CONF_LE_PATH+"renewal/"+hostname+".conf")
    except:
	pass
    print "deleting certificate " + hostname

def DaemonFunc():
    time.sleep(5)
    while True:
	global APP_TMP_LOOP_RUN
#	print "Daemon function RUN! [advanced call at "+str(APP_TMP_LOOP_RUN)+" of "+str(CONF_RUN_REISSUE_ON_LOOP_NO)+"]"
	if APP_TMP_LOOP_RUN==CONF_RUN_REISSUE_ON_LOOP_NO:
	    APP_TMP_LOOP_RUN=1
	    print "Checking for certificates to be re-issued. ["+str(CONF_REISSUE_DAYS_BEFORE)+" days old]"
	    REISSUE_CERTS=Cert.select().where(Cert.updated<(int(time.time())-(CONF_REISSUE_DAYS_BEFORE*84600)),Cert.status=="created",Cert.updated>1)
	    for CERT in REISSUE_CERTS:
		print "Time to reissue for:"+CERT.hostname
		CERT.status="to_re_create"
		CERT.save()
		log_log(CERT.hostname,"automat","Time to re-issue this cert.")
		
	APP_TMP_LOOP_RUN=APP_TMP_LOOP_RUN+1

	TMP_TODO_TOCREATE=Cert.select().where(Cert.status=="to_create").limit(2)
	for CERT_TOCREATE in TMP_TODO_TOCREATE:
	    exe_cert_cmd_create(CERT_TOCREATE.hostname,"Issue")

	TMP_TODO_TOCREATE=Cert.select().where(Cert.status=="to_re_create").limit(2)
	for CERT_TOCREATE in TMP_TODO_TOCREATE:
	    exe_cert_cmd_create(CERT_TOCREATE.hostname,"Re-Issue")

	TMP_TODO_TODELETE=Cert.select().where(Cert.status=="to_delete").limit(2)
	for CERT_TODELETE in TMP_TODO_TODELETE:
	    print CERT_TODELETE.hostname
	    delete_certificate(CERT_TODELETE.hostname)
	    CERT_TODELETE.status="deleted"
	    CERT_TODELETE.save()
	    log_log(CERT_TODELETE.hostname,"automat","Revoking/Deleting certificate ("+CERT_TODELETE.hostname+").")

	
	#clean db. Delete rows with status=deleted.
	clear=Cert.delete().where(Cert.status=="deleted")
	clear.execute()

	#output = Popen(["mycmd", "myarg"], stdout=PIPE).communicate()[0]
	time.sleep(CONF_PROCESSING_LOOP_TIME)
        
if __name__ == "__main__":


    thread.start_new_thread(DaemonFunc, ())

    http.config.update("config.conf")

    print http.config["log.error_file"]

    http.quickstart( lesslserver() )




