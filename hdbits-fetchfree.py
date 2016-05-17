import json, requests, sys, urllib2, pprint, sqlite3, getopt, os, textwrap, datetime
from lxml import etree

def ifDownloaded(id):
	#checks if the id is in the downloaded list
	cur.execute('SELECT * FROM complete WHERE id=?', (id,))
	return False if len(cur.fetchall()) == 0 else True

def ifWatched(id):
	#checks if the id is in the watchlist
	cur.execute('SELECT * FROM watched WHERE id=?', (id,))
	return False if len(cur.fetchall()) == 0 else True

def fetchTorrent(id,watchdir,sslVerify=True):
	#fetches torrent based on the given torrent id.  checks the database if it's already been downloaded.
	#if not, it downloads it.
	
	apiUrl = 'https://hdbits.org/api/torrents'
	if ifDownloaded(id) == False or allowDupes:
		fetchPayload = {"username":username,"passkey":passkey,"limit":"1","id":id}
		fetchResponse = requests.post(apiUrl, data=json.dumps(fetchPayload), headers=headers, verify=sslVerify)
		fetchData = json.loads(fetchResponse.text)
		torrentUrl = "https://hdbits.org/download.php?id=" + str(fetchData['data'][0]['id']) + "&passkey=" + passkey
		idStr = str(fetchData['data'][0]['id'])
		nameStr = fetchData['data'][0]['filename']
		fullStr = os.path.abspath(watchdir) + nameStr

		if verbose:
			print "fetching: " + nameStr + " at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		#save .torrent file
		torrentFile = urllib2.urlopen(torrentUrl)
		try:
			with open(fullStr,'wb') as output:
				output.write(torrentFile.read())
			if verbose:
				print "writing .torrent file to " + fullStr
		except IOError:
			print "ERROR: could not write " + fullStr
			exit(1) 
		#log download to database
		cur.execute('''INSERT INTO complete(id, name) VALUES(?,?)''', (idStr, nameStr))
		conn.commit()
	elif debug:
		print "already fetched: " + str(id)

def populateWatchlist(queueFilename):
	#checks queue.html, extracts all the ID #s from the links, and adds that list to the db
	parser = etree.HTMLParser()
	parsedPage = etree.parse(queueFilename, parser)
	hyperlinks = parsedPage.xpath("/html/body/table[3]/tr/td[2]/table/tr/td/table/tr/td/table/tr/td[1]/a/@href") 
	names = parsedPage.xpath("/html/body/table[3]/tr/td[2]/table/tr/td/table/tr/td/table/tr/td[1]/a/text()")
	cur.execute('''DROP TABLE watched''')
	cur.execute('''CREATE TABLE IF NOT EXISTS watched(idx INT, id INT, name TEXT)''')
	i=0;
	for x in hyperlinks:
		if not ifDownloaded(x[15:]) and not ifWatched(x[15:]):
			print names[i] + " added to watchlist"
			idStr = str(x[15:])
			indexStr = str(i)
			nameStr = names[i].encode('ascii', 'ignore').decode('ascii')
			cur.execute('''INSERT INTO watched(idx,id,name) VALUES(?,?,?)''', (indexStr, idStr, nameStr))
		i+=1
	conn.commit()	
	exit(0)

def generateConfigFile(sslVerify=True):
	isCorrect = False
	fileBasePath = os.path.dirname(os.path.realpath(__file__))
	usernameDefaultInput = ""
	passkeyDefaultInput = "" 
	watchdirDefaultInput = "watchdir/"

	while True:
		usernameInput = raw_input("Please input your hdbits username: [" + usernameDefaultInput + "] ")
		passkeyInput = raw_input("Please input your hdbits passkey: [" + passkeyDefaultInput + "] ")
		watchdirInput = raw_input(".torrent file output directory (relative or absolute): [" + watchdirDefaultInput + "] ") 

		#if no input, go with default input
		if len(usernameInput) == 0:
			usernameInput = usernameDefaultInput
		if len(passkeyInput) == 0:
			passkeyInput = passkeyDefaultInput
		if len(watchdirInput) == 0:
			watchdirInput = watchdirDefaultInput

		print "\n\nUsername: " + usernameInput
		print "Passkey: " + passkeyInput
		print "Output Directory: " + os.path.abspath(watchdirInput)

		#check if data input is correct
		while True:
			a = raw_input("\nIs this correct? (y/n) ")
			if a == 'y':
				#checks api if the user/passkey is valid
				apiUrl = "https://hdbits.org/api/test"
				payload = {"username":usernameInput,"passkey":passkeyInput}
				headers = {'content-type': 'application/json'}
				response = requests.post(apiUrl, data=json.dumps(payload), headers=headers, verify=sslVerify)
				testData = json.loads(response.text)
				if testData['status'] == 0:
					isCorrect = True
					break
				else:
					print "ERROR: API authentication failure. Check username and passkey and try again"
					break
			elif a == 'n':
				#save inputs as defaults for next try
				usernameDefaultInput = usernameInput
				passkeyDefaultInput = passkeyInput
				watchdirDefaultInput = watchdirInput
				break
		if isCorrect:
			break

	data = {'username':usernameInput,'passkey':passkeyInput,'output_dir':watchdirInput}
	#write config file
	try:
		with open(fileBasePath + "/config.json", 'w') as outfile:
			json.dump(data, outfile)
	except IOError:
		print "ERROR: Cannot write config.json"
		exit(1)
	#remove world read from config file to keep passkey a little more secure
	os.chmod('config.json', 0660)
	exit(0)

def displayHelp():
	print textwrap.dedent("""\
    hdbits-fetchfree.py [OPTIONS] [FILE]

	RUN MODES

	-f, --fetch-free
		Checks the most recent 30 uploads and downloads any that are freeleech

	-F, --fetch-featured
		Checks the list of upcoming featured torrents and downloads any that are freeleech. High number 
		of API calls. Not recommended to be run more than once every 5 minutes.

	-h, --help
		display this help and exits

	--makeconf
		Generates json.config and exits

	-t, -torrentid ######
		Download .torrent file of the matching id

	-u, --update-featured filename.html
		Processes the "Featured Torrents Queue"	page from hdbits and adds them to a watchlist. Local
		files only. Does not accept URLs to not break rule prohibiting site scraping.

	--version
		Shows version number

	MODIFIERS

	--allowdupes
		Bypasses checks to not download dupes

	--noverify
		Skips SSL verification for API queries

	-v
		Verbose output

    """)
	exit(1)

def main():
	global cur, username, passkey, headers, verbose, conn, debug
	
	VERSION = 'build 051716 alpha'

	#default options
	makeConf = updateFeatured = fetchFeatured = verbose = showVersion = dispHelp = allowDupes = singleTorrent = False
	fetchFree = debug = False
	sslVerify = True

	#argument option handling
	options, remainder = getopt.getopt(sys.argv[1:], 'u:hs:VfFv', ['update-featured=','fetch-featured','makeconf',
		'noverify','help','single-torrent','allowdupes','fetch-free','version','debug'])
	for opt, arg in options:
		if opt in ('-v'):
			verbose = True
		elif opt in ('--noverify'):
			sslVerify = False
		elif opt in ('--makeconf'):
			makeConf = True
		elif opt in ('--allowdupes'):
			allowDupes = True
		elif opt in ('-u', '--update-featured'):
			updateFeatured = True
			queueFilename = arg
		elif opt in ('-F','--fetch-featured'):
			fetchFeatured = True
		elif opt in ('-h', '--help'):
			dispHelp = True
		elif opt in ('-s','--single-torrent'):
			singleTorrent = True
			torrentID = arg
		elif opt in ('-f','--fetch-free'):
			fetchFree = True
		elif opt in ('-V','--version'):
			showVersion = True
		elif opt in ('--debug'):
			debug = True

	if debug:
		print "starting run at " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

	if showVersion:
		print "hdbits-fetchfree " + VERSION
		exit(0)

	if makeConf:
		generateConfigFile(sslVerify=sslVerify)

	if dispHelp:
		displayHelp()

	#importing json.config
	fileBasePath = os.path.dirname(os.path.realpath(__file__))
	try:
		with open(fileBasePath + "/config.json",'r') as json_data:
			jsonConfig = json.load(json_data)
			json_data.close()
	except IOError:
		print "config.json not found or not readable. Please run again with --makconf"
		exit(1)
	except:
		print "config.json is invalid. Please recreate with --makeconf"
		exit(1)

	username = jsonConfig['username']
	passkey = jsonConfig['passkey']
	watchdir = jsonConfig['output_dir']

	headers = {'content-type': 'application/json'}

	#connect to database and create tables if they don't exist
	try:
		conn = sqlite3.connect(fileBasePath + "/hdbits.db")
	except IOError:
		print "Permissions error at " + fileBasePath + "/hdbits.db"
		exit(1) 

	cur = conn.cursor()
	cur.execute("CREATE TABLE IF NOT EXISTS complete(id INT, name TEXT)")
	cur.execute("CREATE TABLE IF NOT EXISTS watched(id INT, name TEXT)")

	if(singleTorrent):
		fetchTorrent(torrentID, watchdir,sslVerify=sslVerify)
		exit(1)

	if updateFeatured:
		populateWatchlist(queueFilename)

	#fetch any freeleech in newest 30
	if fetchFree:
		apiUrl = 'https://hdbits.org/api/torrents'
		payload = {"username":username,"passkey":passkey,"limit":"30"}
		response = requests.post(apiUrl, data=json.dumps(payload), headers=headers, verify=sslVerify)
		torrentData = json.loads(response.text)

		for x in torrentData['data']:
			if x['freeleech'] == 'yes':
				fetchTorrent(x['id'],watchdir,sslVerify=sslVerify)

	#Checks the first 7 entries in the watchlist and downloads them if freeleech
	if fetchFeatured:
		watchListTorrents = cur.execute('SELECT * FROM watched LIMIT 7')
		i = 0
		for row in watchListTorrents:
			apiUrl = 'https://hdbits.org/api/torrents'
			payload = {"username":username,"passkey":passkey,"limit":"1","id":row[1]}
			response = requests.post(apiUrl, data=json.dumps(payload), headers=headers, verify=sslVerify)
			torrentData = json.loads(response.text)

			if torrentData['data'][0]['freeleech'] == "yes":
				fetchTorrent(torrentData['data'][0]['id'],watchdir,sslVerify=sslVerify)
				cur.execute('DELETE FROM watched WHERE id=?', (row[1],))
				conn.commit()
			i+=1
		if i == 0:
			print "Warning: watchlist is empty"
		conn.commit()

	if not (updateFeatured or fetchFeatured or fetchFree or singleTorrent or makeConf or showVersion or dispHelp):
		print "ERROR: No runmode specified"
		displayHelp()

	conn.commit()
	conn.close()

if __name__ == "__main__":
    main()