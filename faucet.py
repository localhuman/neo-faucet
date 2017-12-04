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
from neo.Fixed8 import Fixed8
from neo.Core.Helper import Helper
from neo.Core.TX.Transaction import TransactionOutput,ContractTransaction
from neo.Implementations.Wallets.peewee.UserWallet import UserWallet
from neo.SmartContract.ContractParameterContext import ContractParametersContext

# If you want the log messages to also be saved in a logfile, enable the
# next line. This configures a logfile with max 10 MB and 3 rotations:
# settings.set_logfile("/tmp/logfile.log", max_bytes=1e7, backup_count=3)


from twisted.web.static import File
from twisted.internet.defer import succeed

from klein import Klein
from jinja2 import Template,FileSystemLoader,Environment

import json
import pdb


wallet = None



settings.set_logfile("logfile.log", max_bytes=1e7, backup_count=3)


class ItemStore(object):
    app = Klein()

    wallet = None

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

    j2_env = Environment(loader=FileSystemLoader(BASE_DIR),
                         trim_blocks=True)


    sent_tx = None

    def __init__(self):

        wallet_path = os.environ.get('FAUCET_WALLET_PATH','')
        passwd = os.environ.get('FAUCET_WALLET_PASSWORD', '')

        if len(passwd) < 1 or len(wallet_path) < 1:
            raise Exception("Please set FAUCET_WALLET_PASSWORD and FAUCET_WALLET_PATH in your ENV vars")

        self.wallet = UserWallet.Open(path=wallet_path, password=passwd)

        dbloop = task.LoopingCall(self.wallet.ProcessBlocks)
        dbloop.start(.1)

        self.wallet.Rebuild()
        print("created wallet: %s " % self.wallet)

    def _get_context(self):

        neo_balance = Fixed8.Zero()
        for coin in self.wallet.FindUnspentCoinsByAsset(Blockchain.SystemShare().Hash):
            neo_balance += coin.Output.Value

        gas_balance = Fixed8.Zero()
        for coin in self.wallet.FindUnspentCoinsByAsset(Blockchain.SystemCoin().Hash):
            gas_balance += coin.Output.Value

        return {
            'message':'Hello',
            'height':Blockchain.Default().Height,
            'neo': neo_balance.ToInt(),
            'gas': gas_balance.ToInt(),
            'wallet_height': self.wallet.WalletHeight
        }

    def _make_tx(self, addr_to):

        output1 = TransactionOutput(
            AssetId = Blockchain.SystemCoin().Hash,
            Value = Fixed8.FromDecimal(2000),
            script_hash = addr_to
        )
        output2 = TransactionOutput(
            AssetId = Blockchain.SystemShare().Hash,
            Value = Fixed8.FromDecimal(100),
            script_hash = addr_to
        )

        contract_tx = ContractTransaction()
        contract_tx.outputs = [output1, output2]
        contract_tx = self.wallet.MakeTransaction(contract_tx)

        print("tx to json: %s " % json.dumps(contract_tx.ToJson(), indent=4))

        context = ContractParametersContext(contract_tx, isMultiSig=False)
        self.wallet.Sign(context)

        if context.Completed:

            contract_tx.scripts = context.GetScripts()

            self.wallet.SaveTransaction(contract_tx)

            #            print("will send tx: %s " % json.dumps(tx.ToJson(),indent=4))

            relayed = NodeLeader.Instance().Relay(contract_tx)

            if relayed:
                print("Relayed Tx: %s " % contract_tx.Hash.ToString())
                return contract_tx
            else:

                print("Could not relay tx %s " % contract_tx.Hash.ToString())

        else:
            print("Transaction initiated, but the signature is incomplete")
            print(json.dumps(context.ToJson(), separators=(',', ':')))
            return False

        return False

    @app.route('/')
    def app_home(self, request):

        ctx = self._get_context()
        output = self.j2_env.get_template('index.html').render(ctx)
        return output

    @app.route('/index.html')
    def app_home(self, request):

        ctx = self._get_context()

        if ctx['neo'] < 100 or ctx['gas'] < 2000:
            print("NO ASSETS AVALAIBLE")

        ctx['come_back'] = True

        print("contex:%s " % json.dumps(ctx, indent=4))
        output = self.j2_env.get_template('index.html').render(ctx)
        return output


    @app.route('/ask', methods=['POST'])
    def ask_for_assets(self, request):
        self.sent_tx = None
        ctx = self._get_context()
        ctx['error'] = True
        addr = None
        try:

            if b'coz_addr' in request.args:
                addr = request.args.get(b'coz_addr')[0]
                ctx['addr'] = addr.decode('utf-8')

            if b'do_agree' in request.args:

                agree = request.args.get(b'do_agree')[0]
                if agree != b'on':
                    print("must agree to guidelines")
                    ctx['message_error'] = 'You must agree to the guidelines to proceed'
                else:

                    addr_shash = self.wallet.ToScriptHash(addr.decode('utf-8'))

                    tx = self._make_tx(addr_shash)

                    if type(tx) is ContractTransaction:
                        print("ALL OK!!!!!")
                        self.sent_tx = tx
                        request.redirect('/success')
                        return succeed(None)

                    else:
                        ctx['message_error'] = 'Error constructing transaction: %s ' % tx
            else:
                print("NO AGGREEEEE!!!!")
                ctx['message_error'] = 'You must agree to the guidelines to proceed'


        except Exception as e:
            error = 'Could not process request. %s ' % e
            print("excetption: %s " % e)
            ctx['message_error'] = 'Could not process your request: %s ' % e



        output = self.j2_env.get_template('index.html').render(ctx)
        return output

    @app.route('/success')
    def app_success(self, request):
        ctx = self._get_context()
        if not self.sent_tx:
            print("NO SENT TX:")
            request.redirect('/')
            return succeed(None)

        senttx_json = json.dumps(self.sent_tx.ToJson(), indent=4)
        ctx['tx_json'] = senttx_json
        ctx['message_success'] = "Your request has been relayed to the network. Transaction: %s " % self.sent_tx.Hash.ToString()

        output = self.j2_env.get_template('success.html').render(ctx)

        self.sent_tx = None
        self.wallet.Rebuild()

        return output

    @app.route('/about')
    def app_about(self,request):
        return 'I am about!'

    @app.route('/static/', branch=True)
    def static(self, request):
        return File("./static")





def main():
    # Setup the blockchain
    settings.setup('protocol.faucet.json')

    blockchain = LevelDBBlockchain(settings.LEVELDB_PATH)
    Blockchain.RegisterBlockchain(blockchain)
    dbloop = task.LoopingCall(Blockchain.Default().PersistBlocks)
    dbloop.start(.1)
    NodeLeader.Instance().Start()

    # Start a thread with custom code
#    d = threading.Thread(target=custom_background_code)
#    d.setDaemon(True)  # daemonizing the thread will kill it when the main thread is quit
#    d.start()

    # Run all the things (blocking call)
    #reactor.run()

    store = ItemStore()
    store.app.run('localhost', 8080)

    logger.info("Shutting down.")


if __name__ == "__main__":
    main()
