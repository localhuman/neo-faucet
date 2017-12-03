"""
Minimal NEO node with custom code in a background thread.

It will log events from all smart contracts on the blockchain
as they are seen in the received blocks.
"""
import threading
from time import sleep
import os

from logzero import logger
from twisted.internet import reactor, task

from neo.Network.NodeLeader import NodeLeader
from neo.Core.Blockchain import Blockchain
from neo.Implementations.Blockchains.LevelDB.LevelDBBlockchain import LevelDBBlockchain
from neo.Settings import settings

from neo.Implementations.Wallets.peewee.UserWallet import UserWallet

# If you want the log messages to also be saved in a logfile, enable the
# next line. This configures a logfile with max 10 MB and 3 rotations:
# settings.set_logfile("/tmp/logfile.log", max_bytes=1e7, backup_count=3)


from twisted.web.static import File


from klein import Klein
import json
import pdb
app = Klein()


wallet = None

from jinja2 import Template,FileSystemLoader,Environment

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

j2_env = Environment(loader=FileSystemLoader(BASE_DIR),
                     trim_blocks=True)

@app.route('/')
def app_home(request):



    template = Template('./index.html')
    output = template.render(msg='hello!!')
    print("111 output: %s" %output)

    return template.render(msg="hello")

@app.route('/index.html')
def app_home(request):


    global j2_env

    output = j2_env.get_template('index.html').render(msg='Hello!!')
    return output


@app.route('/ask', methods=['POST'])
def ask_for_assets(request):

    success=''
    error = ''
    addr = ''
    try:
        addr = request.args.get(b'coz_addr')[0]
        agree = request.args.get(b'do_agree')[0]
#        pdb.set_trace()
        print("addr: %s " % addr)

        if not agree:

            print("must agree to guidelines")
            error = 'You must agree to the guidelines'
        else:
            print("OK!!!")
            success = 'Your request has been granted!'

    except Exception as e:
        error = 'Could not process request. %s ' % e

    return "RETURNING %s %s %s " % (addr, success, error)

@app.route('/about')
def app_about(request):
    return 'I am about!'

@app.route('/static/', branch=True)
def static(request):
    return File("./static")




def custom_background_code():
    """ Custom code run in a background thread.

    This function is run in a daemonized thread, which means it can be instantly killed at any
    moment, whenever the main thread quits. If you need more safety, don't use a  daemonized
    thread and handle exiting this thread in another way (eg. with signals and events).
    """

    while True:
        logger.info("Block %s / %s", str(Blockchain.Default().Height), str(Blockchain.Default().HeaderHeight))

        global wallet
        if wallet is None:

            try:

                passwd = os.environ.get('FAUCET_WALLET_PASSWORD','')

                if len(passwd) < 1:
                    raise Exception("Please set FAUCET_WALLET_PASSWORD in your ENV vars")

                wallet = UserWallet.Open(path='faucet.db3', password=passwd)
                print("WALLET: %s " % wallet)
            except Exception as e:
                print("Couldnt open wallet: %s " % e)
        sleep(10)



    pass


def main():
    # Setup the blockchain
    settings.setup('protocol.faucet.json')

    blockchain = LevelDBBlockchain(settings.LEVELDB_PATH)
    Blockchain.RegisterBlockchain(blockchain)
    dbloop = task.LoopingCall(Blockchain.Default().PersistBlocks)
    dbloop.start(.1)
    NodeLeader.Instance().Start()

    # Start a thread with custom code
    d = threading.Thread(target=custom_background_code)
    d.setDaemon(True)  # daemonizing the thread will kill it when the main thread is quit
    d.start()

    # Run all the things (blocking call)
    #reactor.run()

    app.run('localhost', 8080)

    logger.info("Shutting down.")


if __name__ == "__main__":
    main()
